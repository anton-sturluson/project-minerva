"""SEC EDGAR helpers that aggregate multi-step edgartools workflows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from edgar import Company


def get_13f_comparison(cik: int | str) -> dict[str, pd.DataFrame]:
    """Fetch latest 13-F and compare with previous quarter.

    Aggregates: Company lookup -> get_filings -> obj() -> compare_holdings()
    -> split by status.

    Returns dict with keys: 'current', 'previous', 'comparison',
    plus filtered views: 'new', 'exited', 'increased', 'decreased'.
    """
    company: Company = Company(str(cik))
    filings_13f = company.get_filings(form="13F-HR").latest(2)

    filing_list: list = list(filings_13f)
    if len(filing_list) < 2:
        raise ValueError(f"Need at least 2 13-F filings for comparison, found {len(filing_list)}")

    current_filing = filing_list[0].obj()
    previous_filing = filing_list[1].obj()

    current_df: pd.DataFrame = current_filing.holdings
    previous_df: pd.DataFrame = previous_filing.holdings

    # edgartools uses capitalized column names: Cusip, Value, Issuer, etc.
    merge_key: str = "Cusip" if "Cusip" in current_df.columns else "cusip"
    value_col: str = "Value" if "Value" in current_df.columns else "value"

    merged: pd.DataFrame = current_df.merge(
        previous_df,
        on=[merge_key],
        how="outer",
        suffixes=("_current", "_previous"),
        indicator=True,
    )

    new_positions: pd.DataFrame = merged[merged["_merge"] == "left_only"].copy()
    exited_positions: pd.DataFrame = merged[merged["_merge"] == "right_only"].copy()

    both: pd.DataFrame = merged[merged["_merge"] == "both"].copy()
    val_current: str = f"{value_col}_current"
    val_previous: str = f"{value_col}_previous"
    increased: pd.DataFrame = both[both[val_current] > both[val_previous]].copy()
    decreased: pd.DataFrame = both[both[val_current] < both[val_previous]].copy()

    return {
        "current": current_df,
        "previous": previous_df,
        "comparison": merged,
        "new": new_positions,
        "exited": exited_positions,
        "increased": increased,
        "decreased": decreased,
    }


def get_10k_items(
    ticker_or_cik: str, items: list[str] | None = None
) -> dict[str, str]:
    """Extract specific items from the most recent 10-K filing.

    Aggregates: Company lookup -> latest 10-K -> obj() -> per-item text extraction.
    Items default to ["1", "1A", "7"] (Business, Risk Factors, MD&A).

    Returns dict mapping item number to text content.
    """
    if items is None:
        items = ["1", "1A", "7"]

    company: Company = Company(ticker_or_cik)
    filing_10k = company.get_filings(form="10-K").latest(1)

    filing_obj = filing_10k.obj() if hasattr(filing_10k, "obj") else list(filing_10k)[0].obj()

    result: dict[str, str] = {}
    for item_num in items:
        try:
            item_text: str = str(filing_obj[f"Item {item_num}"])
            result[item_num] = item_text
        except (KeyError, IndexError, TypeError):
            result[item_num] = ""

    return result


def get_recent_filings(
    ticker_or_cik: str,
    *,
    forms: list[str] | None = None,
    since: date | str | None = None,
    until: date | str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List recent filings for a company in a date window.

    Returns a normalized list of small filing records so higher-level CLI
    orchestration can filter and persist SEC activity without duplicating
    edgartools traversal logic.
    """
    normalized_since: date | None = _coerce_date(since)
    normalized_until: date | None = _coerce_date(until)
    company: Company = Company(ticker_or_cik)
    filings = company.get_filings(form=forms or ["8-K", "10-K", "10-Q"]).latest(limit)

    records: list[dict[str, Any]] = []
    for filing in _iter_filings(filings):
        filing_date: date | None = _coerce_date(getattr(filing, "filing_date", getattr(filing, "date", None)))
        if normalized_since and filing_date and filing_date < normalized_since:
            continue
        if normalized_until and filing_date and filing_date > normalized_until:
            continue
        records.append(
            {
                "ticker_or_cik": str(ticker_or_cik),
                "form": str(getattr(filing, "form", getattr(filing, "form_type", "")) or ""),
                "filing_date": filing_date.isoformat() if filing_date else "",
                "accession_number": str(getattr(filing, "accession_number", "") or ""),
                "primary_document": str(getattr(filing, "primary_document", "") or ""),
                "description": str(getattr(filing, "description", getattr(filing, "title", "")) or ""),
                "url": str(
                    getattr(filing, "filing_url", getattr(filing, "url", getattr(filing, "homepage_url", ""))) or ""
                ),
            }
        )
    return records


def _iter_filings(filings: Any) -> list[Any]:
    if filings is None:
        return []
    if isinstance(filings, list):
        return filings
    try:
        return list(filings)
    except TypeError:
        return [filings]


def _coerce_date(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()
