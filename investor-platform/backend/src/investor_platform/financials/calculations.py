"""Pure annual company formulas and basic-share eligibility."""

from decimal import Context, Decimal, localcontext
from typing import cast

from investor_platform.financials.types import Json, Record, record

FORMULA_VERSION: str = "annual-financial-formulas-v2"


def basic_share_reason(fact: Record, *, require_positive: bool = True) -> str | None:
    """Require a reported common-class basis and, for share counts, a positive value."""
    if fact.get("status") != "reported":
        return "Reported annual basic weighted-average shares are unavailable"
    if require_positive and Decimal(str(fact["value"])) <= 0:
        return "A positive annual basic-share denominator is required"
    if not fact.get("share_basis"):
        return "Reported common-class and split basis is unavailable"
    basis: Record = record(fact["share_basis"])
    classes: list[Json] = cast(list[Json], basis["classes"])
    if not classes or not basis.get("split_adjusted_through"):
        return "Reported common-class and split basis is unavailable"
    if len(classes) > 1 and not basis.get("equivalence_note"):
        return "Common-class economic equivalence has not been established"
    return None


def disclosed_capex_calculations(
    facts: dict[str, Record],
    spending: Record | None,
    bundle_id: str | None,
) -> Record:
    """Subtract evidenced disclosed capital-spending components without inventing a reported sum."""
    outputs: Record = {}
    key: str
    for key in (
        "fcf_after_disclosed_capex",
        "fcf_margin_after_disclosed_capex",
        "allocated_fcf_after_disclosed_capex_per_basic_share",
    ):
        denominator: str | None = (
            "revenue"
            if key == "fcf_margin_after_disclosed_capex"
            else "basic_weighted_average_shares"
            if key.endswith("per_basic_share")
            else None
        )
        names: list[str] = ["operating_cash_flow"] + ([denominator] if denominator else [])
        inputs: list[Record] = [
            {
                "metric_key": name,
                "observation_id": facts[name]["observation_id"],
                "value": facts[name].get("value"),
                "source_id": facts[name].get("source_id"),
                "locator": facts[name].get("locator"),
            }
            for name in names
        ]
        reason: str | None = None
        if not spending or not bundle_id:
            reason = "Disclosed cash capital spending components are unavailable"
        elif any(facts[name]["status"] != "reported" for name in names):
            reason = (
                "Required annual inputs are unavailable"
                if key.endswith("per_basic_share")
                else ("Reported annual cash flow or revenue is unavailable")
            )
        elif (
            key == "fcf_margin_after_disclosed_capex"
            and Decimal(str(facts["revenue"]["value"])) <= 0
        ):
            reason = "A positive revenue denominator is required"
        if denominator == "basic_weighted_average_shares":
            reason = reason or basic_share_reason(facts[denominator])
            inputs[-1]["share_basis"] = facts[denominator].get("share_basis")
        components: Record = record(spending["components"]) if spending else {}
        component_key: str
        for component_key in sorted(components):
            component: Record = record(components[component_key])
            inputs.append(
                {
                    "component_key": component_key,
                    "component_ref": f"{bundle_id}#/capital_spending/components/{component_key}",
                    "value": component["value"],
                    "source_id": component["source_id"],
                    "locator": component["locator"],
                }
            )
        result: Record = {
            "formula_version": FORMULA_VERSION,
            "formula": f"(CFO - sum(disclosed cash capital spending components)) / {denominator}"
            if denominator
            else "CFO - sum(disclosed cash capital spending components)",
            "inputs": inputs,
            "scope": spending["scope"] if spending else None,
            "review_note": spending["review_note"] if spending else None,
        }
        if reason:
            result.update(status="unavailable", reason=reason)
        else:
            context: Context
            with localcontext() as context:
                context.prec = 38
                total: Decimal = sum(
                    (Decimal(str(record(value)["value"])) for value in components.values()),
                    Decimal(0),
                )
                value: Decimal = Decimal(str(facts["operating_cash_flow"]["value"])) - total
                if denominator:
                    value /= Decimal(str(facts[denominator]["value"]))
            result.update(
                status="calculated",
                value=format(value, "f"),
                capital_spending_total=format(total, "f"),
            )
        if denominator == "basic_weighted_average_shares":
            result["share_basis"] = facts[denominator].get("share_basis")
        outputs[key] = result
    return outputs


def calculations(
    facts: dict[str, Record],
    insurer: bool,
    capital_spending: Record | None = None,
    bundle_id: str | None = None,
) -> Record:
    """Compute declared ratios with pinned inputs, missingness and exact decimal arithmetic."""
    outputs: Record = {}
    formulas: dict[str, tuple[list[str], str]] = {
        "gross_margin": (["gross_profit", "revenue"], "gross_profit / revenue"),
        "operating_margin": (["operating_income", "revenue"], "operating_income / revenue"),
        "net_margin": (["net_income", "revenue"], "net_income / revenue"),
        "net_margin_common": (["net_income_common", "revenue"], "net_income_common / revenue"),
        "cfo_margin": (["operating_cash_flow", "revenue"], "operating_cash_flow / revenue"),
        "fcf_after_ppe": (["operating_cash_flow", "cash_capex_ppe"], "CFO - cash PP&E capex"),
        "fcf_margin_after_ppe": (
            ["operating_cash_flow", "cash_capex_ppe", "revenue"],
            "(CFO - cash PP&E capex) / revenue",
        ),
        "allocated_cfo_per_basic_share": (
            ["operating_cash_flow", "basic_weighted_average_shares"],
            "CFO / basic weighted shares",
        ),
        "allocated_fcf_after_ppe_per_basic_share": (
            ["operating_cash_flow", "cash_capex_ppe", "basic_weighted_average_shares"],
            "(CFO - cash PP&E capex) / basic weighted shares",
        ),
    }
    key: str
    inputs: list[str]
    formula: str
    for key, (inputs, formula) in formulas.items():
        if (
            key == "gross_margin"
            and not insurer
            and facts["gross_profit"]["status"] == "not_disclosed"
        ):
            inputs = ["revenue", "cost_of_revenue"]
            formula = "(revenue - cost_of_revenue) / revenue"
        reason: str | None = None
        if insurer and key == "gross_margin":
            reason = "Insurer gross margin is not applicable under the pilot definition"
        missing: list[str] = [name for name in inputs if facts[name]["status"] != "reported"]
        if missing and reason is None:
            reason = "Missing/applicability inputs: " + ", ".join(missing)
        denominator: str | None = (
            "basic_weighted_average_shares"
            if "per_basic_share" in key
            else ("revenue" if "margin" in key else None)
        )
        if denominator and facts[denominator]["status"] == "reported":
            if Decimal(str(facts[denominator]["value"])) <= 0:
                reason = "A positive denominator is required"
        if denominator == "basic_weighted_average_shares" and not missing:
            reason = reason or basic_share_reason(facts[denominator])
        result: Record = {
            "formula_version": FORMULA_VERSION,
            "formula": formula,
            "inputs": [
                {
                    "metric_key": name,
                    "observation_id": facts[name]["observation_id"],
                    "source_id": facts[name].get("source_id"),
                }
                for name in inputs
            ],
        }
        if reason:
            result.update(status="unavailable", reason=reason)
        else:
            amounts: list[Decimal] = [Decimal(str(facts[name]["value"])) for name in inputs]
            context: Context
            with localcontext() as context:
                context.prec = 38
                value: Decimal = amounts[0]
                if key == "gross_margin" and len(inputs) == 2 and inputs[0] == "revenue":
                    value = (amounts[0] - amounts[1]) / amounts[0]
                elif key.startswith("fcf_") or key.startswith("allocated_fcf"):
                    value -= amounts[1]
                    if denominator:
                        value /= amounts[-1]
                elif denominator:
                    value /= amounts[-1]
            result.update(status="calculated", value=format(value, "f"))
        outputs[key] = result
    outputs.update(disclosed_capex_calculations(facts, capital_spending, bundle_id))
    return outputs
