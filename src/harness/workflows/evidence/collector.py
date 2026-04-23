"""SEC collection into the canonical evidence tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import harness.commands.sec as sec
from harness.config import HarnessSettings
from harness.workflows.evidence.ledger import upsert_evidence, utc_now
from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.registry import ensure_company_tree

_FORM_TO_CATEGORY: dict[str, str] = {
    "10-K": "sec-annual",
    "10-Q": "sec-quarterly",
}


def collect_sec_sources(
    paths: CompanyPaths,
    *,
    ticker: str,
    annual: int,
    quarters: int,
    earnings: int,
    include_financials: bool,
    include_html: bool,
    settings: HarnessSettings,
) -> dict[str, Any]:
    """Collect SEC materials into the evidence tree and register ledger entries."""
    ensure_company_tree(paths)
    identity_error = sec._configure_edgar(settings)
    if identity_error:
        raise ValueError(identity_error)

    sec._bulk_download_one(
        ticker=ticker,
        base_output=paths.sources_dir,
        annual=annual,
        quarters=quarters,
        earnings=earnings,
        include_financials=include_financials,
        include_html=include_html,
        nest_ticker=False,
    )

    registered: list[dict[str, Any]] = []

    # Register 10-K and 10-Q per-section directories.
    for form_folder in ["10-K", "10-Q"]:
        registered.extend(_register_filings(paths, ticker=ticker, form_folder=form_folder))

    # Register earnings releases (flat .md files).
    earnings_folder = paths.sources_dir / "earnings"
    if earnings_folder.exists():
        for entry in sorted(earnings_folder.iterdir()):
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue
            if entry.suffix == ".html":
                continue
            if entry.suffix == ".md":
                date_stem = entry.stem
                ledger_entry = upsert_evidence(
                    paths,
                    ticker=ticker,
                    category="sec-earnings",
                    status="downloaded",
                    title=f"{ticker.upper()} earnings {date_stem}",
                    local_path=str(entry.relative_to(paths.root)),
                    url=None,
                    date=date_stem,
                    notes="Earnings release (8-K EX-99.1)",
                    collector="sec",
                )
                registered.append(ledger_entry)

    # Register financial statement files.
    financials_folder = paths.sources_dir / "financials"
    if financials_folder.exists():
        for entry in sorted(financials_folder.iterdir()):
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue
            if entry.suffix not in {".md", ".csv"}:
                continue
            ledger_entry = upsert_evidence(
                paths,
                ticker=ticker,
                category="sec-financials",
                status="downloaded",
                title=f"{ticker.upper()} financials {entry.stem}",
                local_path=str(entry.relative_to(paths.root)),
                url=None,
                date=None,
                notes=f"{entry.stem} financial statement",
                collector="sec",
            )
            registered.append(ledger_entry)

    now = utc_now()
    summary = {
        "ticker": ticker.upper(),
        "root": str(paths.root),
        "collected_count": len(registered),
        "annual_count": len([item for item in registered if item["category"] == "sec-annual"]),
        "quarterly_count": len([item for item in registered if item["category"] == "sec-quarterly"]),
        "earnings_count": len([item for item in registered if item["category"] == "sec-earnings"]),
        "financials_count": len([item for item in registered if item["category"] == "sec-financials"]),
        "last_updated": now,
    }
    return summary


def _register_filings(paths: CompanyPaths, *, ticker: str, form_folder: str) -> list[dict[str, Any]]:
    """Register 10-K or 10-Q filings. Expects per-section directories."""
    out: list[dict[str, Any]] = []
    folder = paths.sources_dir / form_folder
    if not folder.exists():
        return out
    category = _FORM_TO_CATEGORY[form_folder]
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.is_dir():
            # Per-section directory
            date_stem = entry.name
            section_count = len([f for f in entry.glob("*.md") if f.name != "_sections.md"])
            notes = f"{section_count} sections" if section_count > 1 else "single-file filing"
            ledger_entry = upsert_evidence(
                paths,
                ticker=ticker,
                category=category,
                status="downloaded",
                title=f"{ticker.upper()} {form_folder} {date_stem}",
                local_path=str(entry.relative_to(paths.root)),
                url=None,
                date=date_stem,
                notes=notes,
                collector="sec",
            )
            out.append(ledger_entry)
        elif entry.suffix == ".md":
            # Legacy monolithic file — register as-is, pointing to the file
            date_stem = entry.stem
            ledger_entry = upsert_evidence(
                paths,
                ticker=ticker,
                category=category,
                status="downloaded",
                title=f"{ticker.upper()} {form_folder} {date_stem}",
                local_path=str(entry.relative_to(paths.root)),
                url=None,
                date=date_stem,
                notes="monolithic filing (legacy)",
                collector="sec",
            )
            out.append(ledger_entry)
    return out
