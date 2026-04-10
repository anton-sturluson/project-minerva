"""SEC collection into the canonical evidence tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import harness.commands.sec as sec
from harness.config import HarnessSettings
from harness.workflows.evidence.inventory import run_inventory
from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.registry import ensure_company_tree, normalize_local_path, upsert_source, utc_now
from harness.workflows.evidence.render import refresh_indexes, write_json


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
    """Collect SEC materials into the evidence tree and refresh metadata."""
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
    for file_path in sorted(item for item in paths.sources_dir.rglob("*") if _is_registered_source_file(item)):
        registered.append(_register_downloaded_file(paths, ticker=ticker, file_path=file_path))

    inventory = run_inventory(paths)
    summary = {
        "ticker": ticker.upper(),
        "root": str(paths.root),
        "collected_count": len(registered),
        "annual_count": len([item for item in registered if item["source_kind"] == "sec-10k"]),
        "quarterly_count": len([item for item in registered if item["source_kind"] == "sec-10q"]),
        "earnings_count": len([item for item in registered if item["source_kind"] == "sec-8k-earnings"]),
        "financials_count": len([item for item in registered if item["source_kind"].startswith("sec-financials-")]),
        "inventory_path": str(paths.inventory_json),
        "registered_source_ids": [item["id"] for item in registered],
        "last_updated": utc_now(),
    }
    write_json(paths.sec_collection_summary_json, summary)
    paths.sec_collection_summary_md.write_text(_render_summary_markdown(summary, inventory) + "\n", encoding="utf-8")
    refresh_indexes(paths.root)
    return summary


def _register_downloaded_file(paths: CompanyPaths, *, ticker: str, file_path: Path) -> dict[str, Any]:
    folder = file_path.parent.name
    if folder == "10-K":
        bucket = "sec-filings-annual"
        if file_path.suffix == ".html":
            source_kind = "sec-10k-html"
            title = f"{ticker.upper()} 10-K {file_path.stem} (HTML)"
        else:
            source_kind = "sec-10k"
            title = f"{ticker.upper()} 10-K {file_path.stem}"
    elif folder == "10-Q":
        bucket = "sec-filings-quarterly"
        if file_path.suffix == ".html":
            source_kind = "sec-10q-html"
            title = f"{ticker.upper()} 10-Q {file_path.stem} (HTML)"
        else:
            source_kind = "sec-10q"
            title = f"{ticker.upper()} 10-Q {file_path.stem}"
    elif folder == "earnings":
        bucket = "sec-earnings"
        if file_path.suffix == ".html":
            source_kind = "sec-8k-earnings-html"
            title = f"{ticker.upper()} earnings release {file_path.stem} (HTML)"
        else:
            source_kind = "sec-8k-earnings"
            title = f"{ticker.upper()} earnings release {file_path.stem}"
    elif folder == "financials":
        bucket = "sec-financial-statements"
        if file_path.suffix == ".csv":
            source_kind = f"sec-financials-{file_path.stem}-csv"
            title = f"{ticker.upper()} {file_path.stem} financials (CSV)"
        else:
            source_kind = f"sec-financials-{file_path.stem}"
            title = f"{ticker.upper()} {file_path.stem} financials"
    else:
        bucket = "sec-other"
        source_kind = "sec-other"
        title = f"{ticker.upper()} SEC source {file_path.name}"
    return upsert_source(
        paths,
        ticker=ticker,
        bucket=bucket,
        source_kind=source_kind,
        status="downloaded",
        title=title,
        local_path=normalize_local_path(paths, file_path),
        notes="Collected via minerva evidence collect sec.",
    )


def _render_summary_markdown(summary: dict[str, Any], inventory: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# SEC Collection Summary",
            "",
            f"- ticker: {summary['ticker']}",
            f"- collected_count: {summary['collected_count']}",
            f"- annual_count: {summary['annual_count']}",
            f"- quarterly_count: {summary['quarterly_count']}",
            f"- earnings_count: {summary['earnings_count']}",
            f"- financials_count: {summary['financials_count']}",
            f"- inventory_downloaded: {inventory['counts']['downloaded']}",
            f"- last_updated: {summary['last_updated']}",
        ]
    )


def _is_registered_source_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(".") and path.name != "INDEX.md"
