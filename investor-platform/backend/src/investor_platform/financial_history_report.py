"""Calculate the five reviewed measures using one account's dated equity weights."""

from decimal import Decimal, localcontext

from .financial import Record, record, records
from .financial_history import METRICS, fund_listings, number

RATIOS: dict[str, str] = {
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "fcf_margin_after_disclosed_capex": "FCF margin",
}
SHARES: dict[str, str] = {
    "basic_eps": "weighted_company_eps",
    "fcf_per_basic_share": "weighted_company_fcf_per_share",
}


def comparison(current: Decimal | None, prior: Decimal | None, year: int) -> Record:
    """Keep prior amounts while withholding meaningless percentage changes."""
    status: str = "unavailable"
    reason: str | None = "Comparable prior financial data unavailable"
    change: Decimal | None = None
    if current is not None and prior is not None:
        if prior <= 0:
            status, reason = "not_meaningful", "Prior amount is not positive"
        else:
            status, reason = "calculated", None
            change = current / prior - 1
    return {
        "prior_year": year - 1,
        "prior_value": format(prior, "f") if prior is not None else None,
        "status": status,
        "percent_change": format(change, "f") if change is not None else None,
        "reason": reason,
    }


def measure(source: Record | None, key: str, prior: bool, rates: dict[str, Decimal]) -> Record:
    """Convert source common-share amounts without changing native ratio measures."""
    missing: Record = {
        "status": "unavailable",
        "value": None,
        "reason": "Reviewed financial data unavailable",
    }
    if source is None or source["instrument_type"] == "fund":
        missing["reason"] = "Fund excluded" if source else missing["reason"]
        return missing
    result: Record = dict(record(record(source["prior_metrics" if prior else "metrics"])[key]))
    if result["status"] != "available" or key not in SHARES:
        return result
    currency: str = str(source["currency"])
    factor: object = source.get("shares_per_traded_unit")
    if factor is None or currency not in rates:
        return {
            **result,
            "status": "unavailable",
            "value": None,
            "reason": "Verified traded-share conversion or currency rate unavailable",
        }
    native: Decimal = number(result["value"])
    result.update(
        native_value=format(native, "f"),
        currency=currency,
        value=format(native * number(factor) * rates[currency], "f"),
        unit="USD_per_company_share",
        share_basis=source["share_basis"],
    )
    return result


def amount(metric: Record) -> Decimal | None:
    """Read only admitted available values."""
    return number(metric["value"]) if metric.get("status") == "available" else None


def build_report(
    release: Record | None,
    snapshot: Record,
    year: int,
    account_id: str,
    rates: dict[str, Decimal],
    *,
    pricing_complete: bool = True,
) -> Record:
    """Use all equities in coverage, and covered companies in each weighted mean."""
    with localcontext() as context:
        context.prec = 40
        return _build_report(release, snapshot, year, account_id, rates, pricing_complete)


def _build_report(
    release: Record | None,
    snapshot: Record,
    year: int,
    account_id: str,
    rates: dict[str, Decimal],
    pricing_complete: bool,
) -> Record:
    """Build one bounded response without changing the annual-only report contract."""
    available: dict[tuple[str, str, int], Record] = (
        {
            (str(row["ticker"]), str(row["exchange"]), int(str(row["year"]))): row
            for row in records(release["records"])
            if release is not None
        }
        if release
        else {}
    )
    funds: set[tuple[str, str]] = fund_listings(release)
    holdings: list[Record] = [
        holding
        for holding in records(snapshot["holdings"])
        if (str(holding["ticker"]), str(holding["exchange"])) not in funds
    ]
    snapshot = {**snapshot, "holdings": holdings}
    total: Decimal = sum(
        (number(h["market_value"]) for h in holdings if h.get("market_value") is not None),
        Decimal(0),
    )
    complete: bool = (
        pricing_complete
        and total > 0
        and all(
            h.get("market_value") is not None and number(h["market_value"]) > 0 for h in holdings
        )
    )
    companies: list[Record] = []
    current: dict[str, dict[str, Decimal]] = {key: {} for key in METRICS}
    weights: dict[str, Decimal] = {}
    holding: Record
    for holding in holdings:
        identity: tuple[str, str] = (str(holding["ticker"]), str(holding["exchange"]))
        source: Record | None = available.get((*identity, year))
        issuer: str = str(source["issuer_key"]) if source else "listing:" + ":".join(identity[::-1])
        holding["issuer_key"] = issuer
        # Each traded listing remains separate, even when two classes share an issuer.
        listing: str = ":".join(identity)
        weight: Decimal | None = number(holding["market_value"]) / total if complete else None
        if weight is not None:
            weights[listing] = weight
        values: Record = {}
        comparisons: Record = {}
        metrics: Record = {}
        key: str
        for key in METRICS:
            present: Record = measure(source, key, False, rates)
            old: Record = measure(source, key, True, rates)
            now: Decimal | None = amount(present)
            before: Decimal | None = amount(old)
            if now is not None:
                current[key][listing] = now
            metrics[key] = present
            if key in SHARES:
                values[key] = present
                comparisons[key] = comparison(now, before, year)
        companies.append(
            {
                "issuer_key": issuer,
                "ticker": identity[0],
                "exchange": identity[1],
                "name": holding.get("name", identity[0]),
                "financial_status": "eligible"
                if source and identity not in funds
                else "unavailable",
                "equity_weight": format(weight, "f") if weight is not None else None,
                "period": source.get("period") if source else None,
                "prior_period": source.get("prior_period") if source else None,
                "metrics": metrics,
                "per_share_metrics": values,
                "per_share_comparisons": comparisons,
            }
        )
    ratios: Record = {}
    shares: Record = {}
    for key in METRICS:
        covered: Decimal = sum((weights.get(k, Decimal(0)) for k in current[key]), Decimal(0))
        value: Decimal | None = (
            sum((v * weights[k] for k, v in current[key].items()), Decimal(0)) / covered
            if complete and covered > 0
            else None
        )
        exclusions: list[Record] = []
        company: Record
        for company in companies:
            metric: Record = record(record(company["metrics"])[key])
            if metric["status"] != "available":
                exclusions.append(
                    {
                        "issuer_key": company["issuer_key"],
                        "ticker": company["ticker"],
                        "equity_weight": company["equity_weight"],
                        "reason": metric.get("reason"),
                    }
                )
        output: Record = {
            "label": RATIOS.get(
                key, "Weighted company EPS" if key == "basic_eps" else "Weighted company FCF/share"
            ),
            "status": "calculated" if value is not None else "unavailable",
            "value": format(value, "f") if value is not None else None,
            "coverage": format(covered, "f") if complete else None,
            "exclusions": exclusions,
            "unit": "fraction" if key in RATIOS else "USD_per_company_share",
        }
        if key in SHARES:
            output["comparison"] = comparison(value, None, year)
            shares[SHARES[key]] = output
        else:
            ratios[key] = output
    results: list[Record] = [record(v) for v in [*ratios.values(), *shares.values()]]
    count: int = sum(result["status"] == "calculated" for result in results)
    return {
        "account_id": account_id,
        "holdings_date": snapshot["holdings_date"],
        "reporting_fx": {currency: format(rate, "f") for currency, rate in rates.items()},
        "company_comparison_basis": "Same company, selected snapshot FX and traded-share units",
        "calendar_year": year,
        "synthetic": False,
        "release_id": release.get("release_id") if release else None,
        "market_value_snapshot": snapshot,
        "companies": companies,
        "weighted_ratios": ratios,
        "weighted_company_per_share": shares,
        "api_status": "unavailable"
        if not complete or not count
        else "partial"
        if any(result["exclusions"] for result in results)
        else "available",
        "availability_reason": "Market prices unavailable for held securities"
        if not pricing_complete
        else "Reviewed financial data unavailable"
        if not count
        else None,
    }


def add_portfolio_comparisons(
    current: Record, prior: Record | None, year: int, *, reason: str | None = None
) -> None:
    """Compare independent portfolio snapshots, allowing holdings and weights to change."""
    with localcontext() as context:
        context.prec = 40
        key: str
        for key in SHARES.values():
            metric: Record = record(record(current["weighted_company_per_share"])[key])
            old: Record | None = (
                record(record(prior["weighted_company_per_share"])[key]) if prior else None
            )
            now: Decimal | None = number(metric["value"]) if metric["value"] is not None else None
            before: Decimal | None = (
                number(old["value"]) if old and old["value"] is not None else None
            )
            compared: Record = comparison(now, before, year)
            compared["exclusions"] = old["exclusions"] if old else []
            if reason:
                compared["reason"] = reason
            metric["comparison"] = compared
        current["comparison_basis"] = "Each portfolio's own dated holdings, weights and FX"
        current["comparison_inputs"] = (
            {
                key: prior[key]
                for key in (
                    "calendar_year",
                    "release_id",
                    "market_value_snapshot",
                    "reporting_fx",
                    "weighted_company_per_share",
                )
            }
            if prior
            else None
        )
        if reason and current["api_status"] == "available":
            current["api_status"] = "partial"
