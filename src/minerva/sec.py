"""SEC EDGAR helpers that aggregate multi-step edgartools workflows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from edgar import Company

from minerva.formatting import (
    build_markdown_table,
    clean_text,
    format_delta_shares,
    format_millions,
    format_pct,
    format_pp,
    format_shares,
    format_signed_percent,
    is_empty,
    md_cell,
)


def get_13f_comparison(cik: int | str) -> dict[str, Any]:
    """Fetch latest 13-F and compare with previous quarter.

    Aggregates: Company lookup -> get_filings -> obj() -> compare holdings
    -> split by status.

    Returns dict with keys: 'current', 'previous', 'comparison',
    plus filtered views: 'new', 'exited', 'increased', 'decreased',
    and 'unchanged'. Increased/decreased classification uses share-count
    changes when available so price moves do not masquerade as trades.
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
    merge_key: str = _find_column(current_df.columns, ["Cusip", "cusip"]) or "Cusip"
    value_col: str = _find_column(current_df.columns, ["Value", "value"]) or "Value"
    share_col: str = _find_column(
        current_df.columns,
        ["SharesPrnAmount", "sharesPrnAmount", "shares_prn_amount", "sharesprnamount", "shares"],
    ) or value_col

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
    shares_current: str = f"{share_col}_current"
    shares_previous: str = f"{share_col}_previous"
    increased: pd.DataFrame = both[both[shares_current] > both[shares_previous]].copy()
    decreased: pd.DataFrame = both[both[shares_current] < both[shares_previous]].copy()
    unchanged: pd.DataFrame = both[both[shares_current] == both[shares_previous]].copy()

    return {
        "manager_name": _safe_attr_text(company, ["name", "display_name", "ticker"]) or str(cik),
        "current_period": _filing_period_label(current_filing, filing_list[0]),
        "previous_period": _filing_period_label(previous_filing, filing_list[1]),
        "current": current_df,
        "previous": previous_df,
        "comparison": merged,
        "new": new_positions,
        "exited": exited_positions,
        "increased": increased,
        "decreased": decreased,
        "unchanged": unchanged,
    }


def format_13f_report(comparison: dict[str, Any]) -> str:
    """Render a clean markdown report for a two-quarter 13F comparison."""
    current: pd.DataFrame = _comparison_frame(comparison, "current")
    previous: pd.DataFrame = _comparison_frame(comparison, "previous")
    current_total: float = _dataframe_total(current, "Value")
    previous_total: float = _dataframe_total(previous, "Value")

    new_positions: pd.DataFrame = _comparison_frame(comparison, "new")
    exited_positions: pd.DataFrame = _comparison_frame(comparison, "exited")
    increased: pd.DataFrame = _comparison_frame(comparison, "increased")
    decreased: pd.DataFrame = _comparison_frame(comparison, "decreased")
    unchanged: pd.DataFrame = _comparison_frame(comparison, "unchanged")
    if unchanged.empty:
        unchanged = _unchanged_from_comparison(comparison)

    manager_name: str = clean_text(comparison.get("manager_name") or comparison.get("fund_name") or "Unknown Manager")
    current_period: str = clean_text(comparison.get("current_period") or "Current")
    previous_period: str = clean_text(comparison.get("previous_period") or "Previous")

    lines: list[str] = [
        f"## 13F-HR QoQ Comparison: {manager_name}",
        f"Period: {current_period} vs {previous_period}",
        "",
        "### Summary",
        *_format_13f_summary(
            current=current,
            previous=previous,
            new_positions=new_positions,
            exited_positions=exited_positions,
            increased=increased,
            decreased=decreased,
            unchanged=unchanged,
            current_total=current_total,
            previous_total=previous_total,
        ),
        "",
        "### New Positions",
        _format_13f_section(new_positions, "new", current_total, previous_total),
        "",
        "### Exited Positions",
        _format_13f_section(exited_positions, "exited", current_total, previous_total),
        "",
        "### Increased",
        _format_13f_section(increased, "increased", current_total, previous_total),
        "",
        "### Decreased",
        _format_13f_section(decreased, "decreased", current_total, previous_total),
        "",
        "### Unchanged",
        _format_13f_section(unchanged, "unchanged", current_total, previous_total),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _comparison_frame(comparison: dict[str, Any], key: str) -> pd.DataFrame:
    value = comparison.get(key)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _format_13f_summary(
    *,
    current: pd.DataFrame,
    previous: pd.DataFrame,
    new_positions: pd.DataFrame,
    exited_positions: pd.DataFrame,
    increased: pd.DataFrame,
    decreased: pd.DataFrame,
    unchanged: pd.DataFrame,
    current_total: float,
    previous_total: float,
) -> list[str]:
    return [
        (
            f"- Positions: {len(current)} (prev: {len(previous)}) | New: {len(new_positions)} | "
            f"Exited: {len(exited_positions)} | Increased: {len(increased)} | "
            f"Decreased: {len(decreased)} | Unchanged: {len(unchanged)}"
        ),
        (
            f"- Portfolio value: {format_millions(current_total)} "
            f"(prev: {format_millions(previous_total)}, "
            f"Δ {format_signed_percent(_pct_change(current_total, previous_total))})"
        ),
        f"- Net new capital deployed: {format_millions(_section_value_total(new_positions, 'current'))}",
        f"- Net capital exited: {format_millions(_section_value_total(exited_positions, 'previous'))}",
    ]


def _format_13f_section(df: pd.DataFrame, kind: str, current_total: float, previous_total: float) -> str:
    if df.empty:
        return "(no rows)"

    row_payloads: list[tuple[float, list[str], str]] = []
    put_calls: list[str] = []
    for _, row in df.iterrows():
        put_call_side: str = "previous" if kind == "exited" else "current"
        put_call: str = clean_text(_row_value(row, "PutCall", put_call_side))
        if not put_call and kind in {"increased", "decreased", "unchanged"}:
            put_call = clean_text(_row_value(row, "PutCall", "previous"))
        if put_call:
            put_calls.append(put_call)

        if kind == "new":
            value = _row_number(row, "Value", "current")
            cells = [
                md_cell(_row_value(row, "Ticker", "current")),
                md_cell(_row_value(row, "Issuer", "current")),
                md_cell(_row_value(row, "Class", "current")),
                format_shares(_row_number(row, "SharesPrnAmount", "current")),
                format_millions(value),
                format_pct(_weight(value, current_total), na_value=""),
            ]
            sort_key = -(value or 0)
        elif kind == "exited":
            value = _row_number(row, "Value", "previous")
            cells = [
                md_cell(_row_value(row, "Ticker", "previous")),
                md_cell(_row_value(row, "Issuer", "previous")),
                md_cell(_row_value(row, "Class", "previous")),
                format_shares(_row_number(row, "SharesPrnAmount", "previous")),
                format_millions(value),
                format_pct(_weight(value, previous_total), na_value=""),
            ]
            sort_key = -(value or 0)
        elif kind in {"increased", "decreased"}:
            current_value = _row_number(row, "Value", "current")
            previous_value = _row_number(row, "Value", "previous")
            current_shares = _row_number(row, "SharesPrnAmount", "current")
            previous_shares = _row_number(row, "SharesPrnAmount", "previous")
            share_delta = _sub(current_shares, previous_shares)
            share_delta_pct = _pct_change(current_shares, previous_shares)
            current_weight = _weight(current_value, current_total)
            previous_weight = _weight(previous_value, previous_total)
            cells = [
                md_cell(_row_value(row, "Ticker", "current")),
                md_cell(_row_value(row, "Issuer", "current")),
                md_cell(_row_value(row, "Class", "current")),
                format_shares(current_shares),
                format_delta_shares(share_delta),
                format_signed_percent(share_delta_pct),
                format_millions(current_value),
                format_millions(_sub(current_value, previous_value), signed=True),
                format_pct(current_weight, na_value=""),
                format_pp(_sub(current_weight, previous_weight)),
            ]
            sort_key = -(share_delta_pct or 0) if kind == "increased" else (share_delta_pct or 0)
        else:
            current_value = _row_number(row, "Value", "current")
            previous_value = _row_number(row, "Value", "previous")
            current_weight = _weight(current_value, current_total)
            previous_weight = _weight(previous_value, previous_total)
            cells = [
                md_cell(_row_value(row, "Ticker", "current")),
                md_cell(_row_value(row, "Issuer", "current")),
                md_cell(_row_value(row, "Class", "current")),
                format_shares(_row_number(row, "SharesPrnAmount", "current")),
                format_millions(current_value),
                format_pct(current_weight, na_value=""),
                format_pp(_sub(current_weight, previous_weight)),
            ]
            sort_key = -(current_value or 0)

        row_payloads.append((sort_key, cells, md_cell(put_call)))

    include_put_call: bool = bool(put_calls)
    row_payloads.sort(key=lambda item: item[0])
    rows: list[list[str]] = []
    for _, cells, put_call in row_payloads:
        rows.append(cells + ([put_call] if include_put_call else []))

    headers_by_kind: dict[str, list[str]] = {
        "new": ["Ticker", "Issuer", "Class", "Shares", "Value ($M)", "Weight"],
        "exited": ["Ticker", "Issuer", "Class", "Shares (prev)", "Value ($M prev)", "Weight (prev)"],
        "increased": [
            "Ticker",
            "Issuer",
            "Class",
            "Shares",
            "Δ Shares",
            "Δ%",
            "Value ($M)",
            "Δ Value ($M)",
            "Weight",
            "Δ Weight",
        ],
        "decreased": [
            "Ticker",
            "Issuer",
            "Class",
            "Shares",
            "Δ Shares",
            "Δ%",
            "Value ($M)",
            "Δ Value ($M)",
            "Weight",
            "Δ Weight",
        ],
        "unchanged": ["Ticker", "Issuer", "Class", "Shares", "Value ($M)", "Weight", "Δ Weight"],
    }
    headers = headers_by_kind[kind] + (["Put/Call"] if include_put_call else [])
    alignment = ["l", "l", "l"] + ["r"] * (len(headers) - 3)
    return build_markdown_table(headers, rows, alignment=alignment)


def _unchanged_from_comparison(comparison: dict[str, Any]) -> pd.DataFrame:
    merged: pd.DataFrame | None = comparison.get("comparison")
    if merged is None or merged.empty or "_merge" not in merged.columns:
        return pd.DataFrame()
    both = merged[merged["_merge"] == "both"].copy()
    current_col = _find_column(both.columns, ["SharesPrnAmount_current", "sharesPrnAmount_current", "shares_current"])
    previous_col = _find_column(both.columns, ["SharesPrnAmount_previous", "sharesPrnAmount_previous", "shares_previous"])
    if not current_col or not previous_col:
        return pd.DataFrame()
    return both[both[current_col] == both[previous_col]].copy()


def _dataframe_total(df: pd.DataFrame, base_column: str) -> float:
    column = _find_column(df.columns, [base_column, base_column.lower()])
    if not column:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _section_value_total(df: pd.DataFrame, side: str) -> float:
    total = 0.0
    for _, row in df.iterrows():
        total += _row_number(row, "Value", side) or 0.0
    return total


def _row_value(row: pd.Series, base: str, side: str | None = None) -> Any:
    column = _row_column(row, base, side)
    if not column:
        return ""
    return row.get(column, "")


def _row_number(row: pd.Series, base: str, side: str | None = None) -> float | None:
    value = _row_value(row, base, side)
    if is_empty(value):
        return None
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def _row_column(row: pd.Series, base: str, side: str | None = None) -> str | None:
    candidates: list[str] = []
    variants: list[str] = [base, base.lower()]
    if base == "SharesPrnAmount":
        variants.extend(["sharesPrnAmount", "shares_prn_amount", "sharesprnamount", "shares"])
    if side:
        candidates.extend(f"{variant}_{side}" for variant in variants)
    candidates.extend(variants)
    return _find_column(row.index, candidates)


def _find_column(columns: Any, candidates: list[str]) -> str | None:
    column_map = {str(column).lower(): str(column) for column in columns}
    for candidate in candidates:
        found = column_map.get(candidate.lower())
        if found:
            return found
    return None


def _weight(value: float | None, total: float) -> float | None:
    if value is None or total == 0:
        return None
    return (value / total) * 100


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100


def _sub(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _safe_attr_text(obj: Any, names: list[str]) -> str:
    for name in names:
        value = getattr(obj, name, None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
        text = clean_text(value)
        if text:
            return text
    return ""


def _filing_period_label(filing_obj: Any, filing_wrapper: Any | None = None) -> str:
    raw = _safe_attr_text(
        filing_obj,
        ["report_period", "period_of_report", "period_end", "report_date", "filing_date", "date"],
    ) or _safe_attr_text(
        filing_wrapper,
        ["report_period", "period_of_report", "period_end", "report_date", "filing_date", "date"],
    )
    parsed = _safe_coerce_date(raw)
    if parsed:
        quarter = (parsed.month - 1) // 3 + 1
        return f"Q{quarter} {parsed.year} ({parsed.isoformat()})"
    return raw or "Unknown period"


def _safe_coerce_date(value: Any) -> date | None:
    try:
        return _coerce_date(value)
    except (TypeError, ValueError):
        return None


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
