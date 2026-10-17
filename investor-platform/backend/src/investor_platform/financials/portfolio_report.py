"""Calculate the five reviewed measures using one account's dated equity weights."""

import json
from decimal import Context, Decimal, localcontext
from urllib.parse import SplitResult, urlsplit

from investor_platform.financials.arithmetic import comparison_values, weighted_mean
from investor_platform.financials.reviewed_releases import METRICS, fund_listings, number, resolve
from investor_platform.financials.types import Json, Record, record, records

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
    status: str
    change: Decimal | None
    status, change = comparison_values(current, prior)
    reason: str | None = (
        "Current or prior financial data unavailable"
        if status == "unavailable"
        else "Prior amount is not positive"
        if status == "not_meaningful"
        else None
    )
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
    factor: Json = source.get("shares_per_traded_unit")
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


def source_urls(documents: dict[str, Record], source: Record | None) -> list[str]:
    """Return document links tied to the company's current and prior input evidence."""
    if source is None:
        return []
    urls: set[str] = set()
    group: str
    for group in ("metrics", "prior_metrics"):
        metric: Record
        for metric in records(list(record(source[group]).values())):
            proof: Record
            for proof in records(metric.get("inputs", [])):
                packet: Record = documents[str(proof["packet_sha256"])]
                identifier: Json
                for identifier in proof["ids"]:
                    node: Record = resolve(packet, str(identifier))
                    candidates: list[Record] = [node] + [
                        item
                        for item in records(packet.get("sources", []))
                        if item.get("source_id") == node.get("source_id") and node.get("source_id")
                    ]
                    candidate: Record
                    for candidate in candidates:
                        raw: Json = candidate.get("url", candidate.get("source_url"))
                        if isinstance(raw, str):
                            parts: SplitResult
                            try:
                                parts = urlsplit(raw)
                            except ValueError:
                                continue
                            if (
                                parts.scheme in {"https", "http"}
                                and parts.hostname
                                and not parts.username
                            ):
                                urls.add(raw)
    return sorted(urls)


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
    context: Context
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
    documents: dict[str, Record] = (
        {
            sha: record(json.loads(str(payload)))
            for sha, payload in record(record(release["evidence"])["packets"]).items()
        }
        if release
        else {}
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
                compared: Record = comparison(now, before, year)
                if before is None and old.get("reason"):
                    compared["reason"] = old["reason"]
                comparisons[key] = compared
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
                "source_urls": source_urls(documents, source),
                "metrics": metrics,
                "per_share_metrics": values,
                "per_share_comparisons": comparisons,
            }
        )
    ratios: Record = {}
    shares: Record = {}
    for key in METRICS:
        value: Decimal | None
        covered: Decimal
        value, covered = weighted_mean(current[key], weights, complete=complete)
        exclusions: list[Record] = []
        conventions: list[Record] = []
        basis_notes: list[Record] = []
        company: Record
        for company in companies:
            metric: Record = record(record(company["metrics"])[key])
            if metric.get("convention") == "zero_revenue_margin":
                conventions.append(
                    {
                        "issuer_key": company["issuer_key"],
                        "ticker": company["ticker"],
                        "equity_weight": company["equity_weight"],
                        "convention": "zero_revenue_margin",
                    }
                )
            if metric["status"] == "available" and metric.get("basis_note"):
                basis_notes.append({"ticker": company["ticker"], "note": metric["basis_note"]})
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
            "conventions": conventions,
            "unit": "fraction" if key in RATIOS else "USD_per_company_share",
        }
        if basis_notes:
            output["basis_notes"] = basis_notes
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
    context: Context
    with localcontext() as context:
        context.prec = 40
        group: str
        key: str
        for group in ("weighted_ratios", "weighted_company_per_share"):
            for key in record(current[group]):
                metric: Record = record(record(current[group])[key])
                old: Record | None = record(record(prior[group])[key]) if prior else None
                now: Decimal | None = (
                    number(metric["value"]) if metric["value"] is not None else None
                )
                before: Decimal | None = (
                    number(old["value"]) if old and old["value"] is not None else None
                )
                compared: Record = comparison(now, before, year)
                compared["coverage"] = old["coverage"] if old else None
                compared["exclusions"] = old["exclusions"] if old else []
                compared["basis_notes"] = old.get("basis_notes", []) if old else []
                compared["conventions"] = old.get("conventions", []) if old else []
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
                    "weighted_ratios",
                )
            }
            if prior
            else None
        )
        if reason and current["api_status"] == "available":
            current["api_status"] = "partial"
