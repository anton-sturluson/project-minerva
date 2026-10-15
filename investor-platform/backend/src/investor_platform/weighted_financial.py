"""Build reproducible annual ratio reports from explicit values and saved profiles."""

import re
from datetime import date
from decimal import Context, Decimal, localcontext

from .financial import (
    FORMULA_VERSION,
    Json,
    Record,
    basic_share_reason,
    record,
    records,
    validate_capital_spending,
)
from .financial import calculations as company_calculations

WEIGHT_FORMULA_VERSION: str = "annual-market-value-weighting-v1"
RATIO_LABELS: dict[str, str] = {
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "net_margin": "Consolidated net margin",
    "net_margin_common": "Common-shareholder net margin",
    "cfo_margin": "Consolidated CFO margin",
    "fcf_margin_after_ppe": "FCF margin after cash PP&E capex",
    "fcf_margin_after_disclosed_capex": "FCF margin after disclosed cash capital spending",
}
PER_SHARE_METRICS: dict[str, tuple[str, str]] = {
    "weighted_company_eps": ("Weighted company basic EPS", "basic_eps"),
    "weighted_company_fcf_per_share": (
        "Weighted company FCF per basic share",
        "allocated_fcf_after_disclosed_capex_per_basic_share",
    ),
}
COMPANY_LABELS: dict[str, str] = {
    "fcf_after_ppe": "FCF after cash PP&E capex",
    "allocated_cfo_per_basic_share": "Allocated consolidated CFO per basic share",
    "allocated_fcf_after_ppe_per_basic_share": "Allocated FCF after cash PP&E per basic share",
}


def decimal_string(value: Json) -> Decimal:
    """Read a finite unformatted decimal string without binary-float conversion."""
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        raise ValueError("Use an unformatted finite decimal string")
    return Decimal(value)


def eligible_profile(profile: Record, year: int) -> str | None:
    """Check coherent review and the selected calendar year's financial period."""
    if profile.get("review_status") != "reviewed":
        return "Financial publication has not completed independent review"
    period: Record = record(profile["period"])
    start: date = date.fromisoformat(str(period["start"]))
    end: date = date.fromisoformat(str(period["end"]))
    if period.get("kind") != "year" or start >= end or end.year != year:
        return "Annual financial period does not end in the selected calendar year"
    issuer: Record = record(profile["issuer"])
    if issuer.get("reporting_currency") != "USD" or issuer.get("accounting_basis") != "US_GAAP":
        return "Financial profile requires USD US-GAAP facts"
    return None


def ratio_value(profile: Record, key: str) -> tuple[Decimal | None, str | None]:
    """Resolve a calculated ratio only when its declared observation inputs match."""
    calculations: Record = record(profile["calculations"])
    if key not in calculations:
        return None, "Company calculation is absent"
    calculation: Record = record(calculations[key])
    if calculation.get("status") != "calculated":
        return None, str(calculation.get("reason", "Company calculation is unavailable"))
    if calculation.get("formula_version") != FORMULA_VERSION:
        return None, "Unsupported company formula version"
    facts: Record = record(profile["facts"])
    sources: set[str] = {str(s["source_id"]) for s in records(profile["sources"])}
    inputs: list[Record] = records(calculation["inputs"])
    if not inputs:
        return None, "Calculation has no observation inputs"
    item: Record
    for item in inputs:
        if "component_key" in item:
            spending: Record = record(profile["capital_spending"])
            component_key: str = str(item["component_key"])
            components: Record = record(spending["components"])
            component: Record = record(components.get(component_key))
            if (
                item.get("component_ref")
                != f"{profile['bundle_id']}#/capital_spending/components/{component_key}"
                or any(
                    item.get(field) != component.get(field)
                    for field in ("value", "source_id", "locator")
                )
                or str(item.get("source_id")) not in sources
            ):
                return None, "Capital spending component/source provenance does not match"
            continue
        metric: str = str(item["metric_key"])
        if metric not in facts:
            return None, "Calculation references an absent observation"
        fact: Record = record(facts[metric])
        if (
            fact.get("status") != "reported"
            or fact.get("observation_id") != item.get("observation_id")
            or fact.get("source_id") != item.get("source_id")
            or str(item.get("source_id")) not in sources
            or "value" in item
            and item.get("value") != fact.get("value")
            or "locator" in item
            and item.get("locator") != fact.get("locator")
        ):
            return None, "Calculation observation/source provenance does not match"
    return decimal_string(calculation["value"]), None


def reported_basic_eps(profile: Record) -> tuple[Decimal | None, str | None]:
    """Read one reported basic EPS measure with its class, split and source evidence."""
    fact: Record = record(record(profile["facts"]).get("basic_eps", {}))
    if fact.get("status") != "reported":
        return None, str(fact.get("reason", "Reported basic EPS is unavailable"))
    if (
        fact.get("unit") != "USD_per_share"
        or fact.get("entity_scope") != "attributable_common"
        or fact.get("measurement_basis") != "duration"
    ):
        return None, "Basic EPS requires annual USD per common share"
    # EPS can be negative or zero; only the shared class/split safeguards apply here.
    reason: str | None = basic_share_reason(fact, require_positive=False)
    if reason is not None:
        return None, reason
    if (
        not fact.get("observation_id")
        or not fact.get("locator")
        or fact.get("source_id") not in {s["source_id"] for s in records(profile["sources"])}
    ):
        return None, "Basic EPS observation/source provenance does not match"
    return decimal_string(fact["value"]), None


def build_weighted_report(snapshot: Record, profiles: list[Record]) -> Record:
    """Weight reviewed ratios by each metric's covered equity value and show coverage."""
    holdings_date: date = date.fromisoformat(str(snapshot["holdings_date"]))
    if holdings_date.month != 12 or holdings_date.day != 31:
        raise ValueError("This annual report requires explicit calendar year-end market values")
    if snapshot.get("base_currency") != "USD":
        raise ValueError("Supply market values already converted to USD")
    if not isinstance(snapshot.get("synthetic"), bool) or not snapshot.get("source"):
        raise ValueError("Declare whether values are synthetic and identify their source")
    holdings: list[Record] = records(snapshot["holdings"])
    values: dict[str, Decimal] = {}
    valuation_errors: list[str] = []
    holding: Record
    for holding in holdings:
        issuer_key: str = str(holding.get("issuer_key", ""))
        if not issuer_key:
            valuation_errors.append("A holding has no confirmed issuer key")
            continue
        try:
            value: Decimal = decimal_string(holding.get("market_value"))
            if value <= 0:
                raise ValueError("Market value must be positive")
        except ValueError:
            valuation_errors.append(f"{issuer_key}: market value is missing or not positive")
            continue
        context: Context
        with localcontext() as context:
            context.prec = 64
            values[issuer_key] = values.get(issuer_key, Decimal(0)) + value
    if not holdings:
        valuation_errors.append("No selected equity holdings")
    by_issuer: dict[str, Record] = {}
    profile: Record
    for profile in profiles:
        issuer_key = str(record(profile["issuer"])["issuer_key"])
        if issuer_key in by_issuer:
            raise ValueError("Supply one coherent financial publication per issuer and year")
        if eligible_profile(profile, holdings_date.year) is None:
            validate_capital_spending(profile)
            recomputed: Record = company_calculations(
                {k: record(v) for k, v in record(profile["facts"]).items()},
                record(profile["issuer"])["business_type"] == "insurer",
                record(profile["capital_spending"]) if profile.get("capital_spending") else None,
                str(profile["bundle_id"]),
            )
            key: str
            saved: Json
            for key, saved in record(profile["calculations"]).items():
                saved_calculation: Record = record(saved)
                if saved_calculation.get("status") != "calculated":
                    continue
                expected: Record = record(recomputed[key])
                if (
                    expected.get("status") != "calculated"
                    or decimal_string(saved_calculation["value"])
                    != decimal_string(expected["value"])
                    or saved_calculation.get("formula") != expected.get("formula")
                    or "disclosed_capex" in key
                    and any(
                        saved_calculation.get(field) != expected.get(field)
                        for field in (
                            "inputs",
                            "scope",
                            "review_note",
                            "capital_spending_total",
                            "share_basis",
                        )
                    )
                ):
                    raise ValueError("Saved company calculation does not match observation inputs")
        by_issuer[issuer_key] = profile
    companies: list[Record] = []
    for issuer_key in dict.fromkeys(str(h.get("issuer_key", "")) for h in holdings):
        profile = by_issuer.get(issuer_key, {})
        reason: str | None = (
            eligible_profile(profile, holdings_date.year) if profile else "No financial profile"
        )
        companies.append(
            {
                "issuer_key": issuer_key,
                "market_value": format(values[issuer_key], "f") if issuer_key in values else None,
                "financial_status": "eligible" if reason is None else "unavailable",
                "reason": reason,
                "profile": profile or None,
            }
        )
    ratios: Record = {}
    per_share: Record = {}
    with localcontext() as context:
        context.prec = 64
        total: Decimal = sum(values.values(), Decimal(0))
        company: Record
        for company in companies:
            issuer_key = str(company["issuer_key"])
            company["equity_weight"] = (
                format(values[issuer_key] / total, "f")
                if not valuation_errors and total and issuer_key in values
                else None
            )
        key: str
        label: str
        source_key: str
        for key, (label, source_key) in (
            {k: (v, k) for k, v in RATIO_LABELS.items()} | PER_SHARE_METRICS
        ).items():
            covered: Decimal = Decimal(0)
            numerator: Decimal = Decimal(0)
            contributions: list[Record] = []
            exclusions: list[Record] = []
            company: Record
            for company in companies:
                issuer_key = str(company["issuer_key"])
                reason = str(company["reason"]) if company["reason"] is not None else None
                ratio: Decimal | None = None
                if reason is None:
                    selected_profile: Record = record(company["profile"])
                    ratio, reason = (
                        reported_basic_eps(selected_profile)
                        if source_key == "basic_eps"
                        else ratio_value(selected_profile, source_key)
                    )
                if reason is not None:
                    exclusions.append({"issuer_key": issuer_key, "reason": reason})
                elif ratio is not None and issuer_key in values:
                    covered += values[issuer_key]
                    numerator += values[issuer_key] * ratio
                    selected: Record = record(company["profile"])
                    contributions.append(
                        {
                            "issuer_key": issuer_key,
                            "bundle_id": selected["bundle_id"],
                            "market_value": format(values[issuer_key], "f"),
                            "company_ratio" if key in RATIO_LABELS else "company_value": format(
                                ratio, "f"
                            ),
                            "observation" if source_key == "basic_eps" else "calculation": (
                                record(selected["facts"])[source_key]
                                if source_key == "basic_eps"
                                else record(selected["calculations"])[source_key]
                            ),
                        }
                    )
            available: bool = not valuation_errors and covered > 0
            result: Record = {
                "label": label,
                "status": "calculated" if available else "unavailable",
                "value": format(numerator / covered, "f") if available else None,
                "coverage": format(covered / total, "f")
                if not valuation_errors and total
                else None,
                "covered_market_value": format(covered, "f") if not valuation_errors else None,
                "total_selected_equity_value": format(total, "f") if not valuation_errors else None,
                "formula_version": WEIGHT_FORMULA_VERSION,
                "formula": (
                    "sum(company_market_value * company_ratio) / covered_market_value"
                    if key in RATIO_LABELS
                    else "sum(company_market_value * company_value) / covered_market_value"
                ),
                "reason": None
                if available
                else (
                    "Incomplete or invalid market valuation"
                    if valuation_errors
                    else "No financial coverage for this metric"
                ),
                "contributions": contributions,
                "exclusions": exclusions,
            }
            if key in RATIO_LABELS:
                ratios[key] = result
            else:
                result["unit"] = "USD_per_company_share"
                per_share[key] = result
    return {
        "report_version": "annual-weighted-financial-report-v1",
        "synthetic": snapshot["synthetic"],
        "label": "SYNTHETIC WEIGHTS — not actual portfolio exposure"
        if snapshot["synthetic"]
        else "Supplied dated market values",
        "holdings_date": holdings_date.isoformat(),
        "calendar_year": holdings_date.year,
        "base_currency": "USD",
        "weight_source": snapshot["source"],
        "market_value_snapshot": snapshot,
        "valuation_status": "unavailable" if valuation_errors else "complete",
        "valuation_errors": valuation_errors,
        "publication_policy": "Retrospective: supplied reviewed coherent publications; "
        "annual financial periods ending in the selected calendar year; no publication-date cutoff",
        "cash_flow_comparability": "Insurer reported consolidated CFO is included. Cross-sector "
        "cash-flow comparability remains unverified. "
        "These accounting ratios are not owner earnings.",
        "companies": companies,
        "weighted_ratios": ratios,
        "weighted_company_per_share": per_share,
    }


def change_result(current: Json, prior: Json, year: int, reason: str | None) -> Record:
    """Compare available annual values; a nonpositive baseline has no meaningful rate."""
    result: Record = {
        "prior_year": year,
        "prior_value": prior,
        "status": "unavailable",
        "percent_change": None,
        "reason": reason,
        "formula": "current_value / prior_value - 1",
        "formula_version": "annual-per-share-change-v1",
    }
    if reason is not None or current is None or prior is None:
        result["reason"] = reason or "Current or prior annual measure is unavailable"
        return result
    baseline: Decimal = decimal_string(prior)
    if baseline <= 0:
        result.update(status="not_meaningful", reason="Prior annual value is zero or negative")
        return result
    context: Context
    with localcontext() as context:
        context.prec = 64
        result.update(
            status="calculated",
            percent_change=format(decimal_string(current) / baseline - 1, "f"),
            reason=None,
        )
    return result


def share_comparison_reason(current: Record, prior: Record, metric: str) -> str | None:
    """Require compatible classes and an explicitly common split-adjustment basis."""
    basis_key: str = "basic_eps" if metric == "basic_eps" else "basic_weighted_average_shares"
    current_basis: Record = record(record(record(current["facts"])[basis_key])["share_basis"])
    prior_basis: Record = record(record(record(prior["facts"])[basis_key])["share_basis"])
    if sorted(str(c) for c in current_basis["classes"]) != sorted(
        str(c) for c in prior_basis["classes"]
    ) or current_basis.get("split_adjusted_through") != prior_basis.get("split_adjusted_through"):
        return "Comparable common-class and stock-split bases are not established"
    return None


def add_per_share_comparisons(current: Record, prior: Record) -> None:
    """Attach bounded company and weighted changes while retaining the full prior evidence."""
    year: int = int(str(current["calendar_year"])) - 1
    if prior["calendar_year"] != year:
        raise ValueError("Comparison requires the immediately preceding calendar year")
    current["comparison_inputs"] = prior
    prior_companies: dict[str, Record] = {
        str(c["issuer_key"]): c for c in records(prior["companies"])
    }
    company: Record
    for company in records(current["companies"]):
        previous: Record = prior_companies.get(str(company["issuer_key"]), {})
        comparisons: Record = {}
        metric: str
        for label, metric in PER_SHARE_METRICS.values():
            value: Decimal | None = None
            old_value: Decimal | None = None
            reason: str | None = None
            selected: Record = record(company.get("profile") or {})
            old: Record = record(previous.get("profile") or {})
            if company["financial_status"] == "eligible":
                value, reason = (
                    reported_basic_eps(selected)
                    if metric == "basic_eps"
                    else ratio_value(selected, metric)
                )
            else:
                reason = "Current reviewed annual company profile is unavailable"
            prior_reason: str | None = None
            if previous.get("financial_status") == "eligible":
                old_value, prior_reason = (
                    reported_basic_eps(old) if metric == "basic_eps" else ratio_value(old, metric)
                )
            else:
                prior_reason = "Prior reviewed annual company profile is unavailable"
            reason = reason or prior_reason
            if reason is None:
                reason = share_comparison_reason(selected, old, metric)
            comparisons[metric] = change_result(
                format(value, "f") if value is not None else None,
                format(old_value, "f") if old_value is not None else None,
                year,
                reason,
            )
        company["per_share_comparisons"] = comparisons
    key: str
    current_weights: dict[str, Json] = {
        str(c["issuer_key"]): c["equity_weight"] for c in records(current["companies"])
    }
    prior_weights: dict[str, Json] = {
        str(c["issuer_key"]): c["equity_weight"] for c in records(prior["companies"])
    }
    for key, (label, metric) in PER_SHARE_METRICS.items():
        result: Record = record(record(current["weighted_company_per_share"])[key])
        previous_result: Record = record(record(prior["weighted_company_per_share"])[key])
        contributors: dict[str, Json] = {
            str(c["issuer_key"]): current_weights[str(c["issuer_key"])]
            for c in records(result["contributions"])
        }
        old_contributors: dict[str, Json] = {
            str(c["issuer_key"]): prior_weights[str(c["issuer_key"])]
            for c in records(previous_result["contributions"])
        }
        reason = None
        if contributors != old_contributors:
            reason = "Weighted comparison requires identical contributors and market-value weights"
        elif result["status"] != "calculated" or previous_result["status"] != "calculated":
            reason = "Current or prior weighted company measure is unavailable"
        else:
            for company in records(current["companies"]):
                if str(company["issuer_key"]) in contributors:
                    comparison: Record = record(record(company["per_share_comparisons"])[metric])
                    if comparison["status"] == "unavailable":
                        reason = str(comparison["reason"])
                        break
        result["comparison"] = change_result(
            result["value"], previous_result["value"], year, reason
        )


def percent(value: Json) -> str:
    """Display a fraction as a percentage without changing stored precision."""
    return f"{decimal_string(value) * 100:.2f}%" if value is not None else "Unavailable"


def cited_sources(profile: Record, inputs: list[Record]) -> str:
    """Link precisely the document versions used by the displayed observation inputs."""
    source_ids: set[str] = {str(i.get("source_id")) for i in inputs}
    return (
        ", ".join(
            f"[{record(profile['issuer'])['name']} filing {s['published_on']}]({s['url']})"
            for s in records(profile["sources"])
            if str(s["source_id"]) in source_ids
        )
        or "—"
    )


def usd(value: Json, whole: bool = False) -> str:
    """Display USD with thousands separators; whole statement dollars retain their scale."""
    amount: Decimal = decimal_string(value)
    return f"USD {amount:,.0f}" if whole else f"USD {amount:,.2f}"


def short_reason(reason: Json) -> str:
    """Give a brief financial absence explanation while JSON retains the full reason."""
    text: str = str(reason or "No compatible reported measure").split(". ", 1)[0]
    key: str
    label: str
    for key, label in {
        "Missing/applicability inputs:": "Missing",
        "cash_capex_ppe": "cash PP&E spending",
        "basic_weighted_average_shares": "compatible basic shares",
        "net_income": "consolidated net income",
        "gross_profit": "compatible gross profit",
    }.items():
        text = text.replace(key, label)
    return text if len(text) <= 140 else text[:137].rstrip() + "…"


def render_weighted_report(report: Record) -> str:
    """Render concise cited tables while full JSON retains exact observation provenance."""
    lines: list[str] = [
        f"# Annual weighted financial profile {report['calendar_year']}",
        "",
        str(report["label"]),
        "",
        f"Holdings date: {report['holdings_date']}. Currency: USD. {report['weight_source']}.",
        "",
        str(report["publication_policy"]),
        "",
        "Weights use selected equity market value, excluding cash. Each ratio uses its own "
        "covered market-value denominator. Coverage uses all selected equity, including issuers "
        "with missing financial data. Missing valuation withholds every weighted result.",
    ]
    lines.extend(
        [
            "",
            "| Selected issuer | Supplied market value (USD) | Equity weight |",
            "| --- | ---: | ---: |",
        ]
    )
    company: Record
    for company in records(report["companies"]):
        name: str = (
            str(record(record(company["profile"])["issuer"])["name"])
            if company["profile"] is not None
            else str(company["issuer_key"])
        )
        lines.append(
            f"| {name} | "
            f"{usd(company['market_value'], True) if company['market_value'] else 'Unavailable'} | "
            f"{percent(company['equity_weight'])} |"
        )
    profiles: dict[str, Record] = {
        str(c["issuer_key"]): record(c["profile"])
        for c in records(report["companies"])
        if c["profile"] is not None
    }
    lines.extend(
        [
            "",
            "| Metric | Weighted ratio | Financial coverage | Sources |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    ratios: Record = record(report["weighted_ratios"])
    metric: Json
    for metric in ratios.values():
        result: Record = record(metric)
        citations: str = (
            "; ".join(
                dict.fromkeys(
                    cited_sources(
                        profiles[str(c["issuer_key"])], records(record(c["calculation"])["inputs"])
                    )
                    for c in records(result["contributions"])
                )
            )
            or "—"
        )
        lines.append(
            f"| {result['label']} | {percent(result['value'])} | {percent(result['coverage'])} | "
            f"{citations} |"
        )
    lines.extend(
        [
            "",
            str(report["cash_flow_comparability"]),
            "",
            "Company cash flow per basic share is allocated consolidated cash flow; "
            "it is not cash attributable to common owners. Weighted company per-share values "
            "depend on each company's share units and split basis; they are not portfolio-unit "
            "earnings or cash flow.",
        ]
    )
    references: dict[str, Record] = {}
    for company in records(report["companies"]):
        if company["profile"] is None:
            lines.extend(["", f"{company['issuer_key']}: no financial profile."])
            continue
        profile: Record = record(company["profile"])
        issuer: Record = record(profile["issuer"])
        sources: list[Record] = records(profile["sources"])
        for source in sources:
            references[str(source["document_id"])] = source | {"display_name": issuer["name"]}
        period: Record = record(profile["period"])
        lines.extend(
            [
                "",
                f"## {issuer['name']}",
                "",
                f"Financial period: {period['start']} through {period['end']} "
                f"({period['fiscal_label']}).",
                "",
                "| Company metric | Value | Missing-data reason | Sources |",
                "| --- | ---: | --- | --- |",
            ]
        )
        calculations: Record = record(profile["calculations"])
        for key, label in (RATIO_LABELS | COMPANY_LABELS).items():
            calculation: Record = record(calculations.get(key, {}))
            available: bool = company["financial_status"] == "eligible"
            value: Decimal | None
            reason: str | None
            value, reason = (
                ratio_value(profile, key) if available else (None, str(company["reason"]))
            )
            display: str = (
                percent(str(value))
                if value is not None and key in RATIO_LABELS
                else (
                    usd(format(value, "f"), key == "fcf_after_ppe")
                    if value is not None
                    else "Unavailable"
                )
            )
            missing: str = short_reason(reason) if value is None else "—"
            citations = cited_sources(profile, records(calculation.get("inputs", [])))
            lines.append(f"| {label} | {display} | {missing} | {citations} |")
        facts: Record = record(profile["facts"])
        for key, label in {
            "revenue": "Reported revenue",
            "operating_income": "Reported operating income",
            "net_income_common": "Reported common earnings",
            "operating_cash_flow": "Reported consolidated CFO",
            "cash_capex_ppe": "Reported cash PP&E capex",
            "basic_eps": "Reported basic EPS",
            "diluted_eps": "Reported diluted EPS",
        }.items():
            fact: Record = record(facts[key])
            if key.endswith("eps") and "share_basis" in fact:
                classes: Json = record(fact["share_basis"])["classes"]
                if isinstance(classes, list):
                    class_labels: list[str] = []
                    class_name: Json
                    for class_name in classes:
                        class_labels.append(str(class_name).replace("_", " ").title())
                    label += f" ({', '.join(class_labels)})"
            display = (
                usd(fact["value"], not key.endswith("eps"))
                if fact["status"] == "reported" and company["financial_status"] == "eligible"
                else "Unavailable"
            )
            citations = cited_sources(profile, [fact])
            missing = (
                short_reason(
                    company["reason"]
                    if company["financial_status"] != "eligible"
                    else fact.get("reason", fact["status"])
                )
                if display == "Unavailable"
                else "—"
            )
            lines.append(f"| {label} | {display} | {missing} | {citations} |")
    lines.extend(["", "## References", "", "### SEC filings", ""])
    source: Record
    for source in references.values():
        lines.append(
            f"- [{source['display_name']} filing {source['published_on']}]({source['url']}) "
            "— reported company financial statements and related notes."
        )
    if not references:
        lines.append("No company source documents were supplied.")
    return "\n".join(lines) + "\n"
