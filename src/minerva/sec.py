"""SEC EDGAR helpers that aggregate multi-step edgartools workflows."""

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

    current_df: pd.DataFrame = current_filing.holdings.to_dataframe()
    previous_df: pd.DataFrame = previous_filing.holdings.to_dataframe()

    merged: pd.DataFrame = current_df.merge(
        previous_df,
        on=["cusip"],
        how="outer",
        suffixes=("_current", "_previous"),
        indicator=True,
    )

    new_positions: pd.DataFrame = merged[merged["_merge"] == "left_only"].copy()
    exited_positions: pd.DataFrame = merged[merged["_merge"] == "right_only"].copy()

    both: pd.DataFrame = merged[merged["_merge"] == "both"].copy()
    increased: pd.DataFrame = both[both["value_current"] > both["value_previous"]].copy()
    decreased: pd.DataFrame = both[both["value_current"] < both["value_previous"]].copy()

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
