"""Extract a bounded SPGI issuance/revenue sample from original quarterly filings."""

import argparse
import hashlib
import json
import os
import re
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape
from pathlib import Path

type Json = str | int | float | bool | None | list[Json] | dict[str, Json]

FILINGS: tuple[tuple[str, str, str, int, int], ...] = (
    (
        "spgi-2026-q1",
        "https://www.sec.gov/Archives/edgar/data/64040/000006404026000024/spgi-20260331.htm",
        "2026-04-28",
        2026,
        1,
    ),
    (
        "spgi-2026-q2",
        "https://www.sec.gov/Archives/edgar/data/64040/000006404026000045/spgi-20260630.htm",
        "2026-07-28",
        2026,
        2,
    ),
)
BILLED: dict[str, str] = {
    "Investment-grade billed issuance": "billed_ig",
    "High-yield billed issuance": "billed_hy",
    "Other billed issuance": "billed_other",
    "Total billed issuance": "billed_total",
}
REVENUE: dict[str, str] = {
    "Transaction revenue": "ratings_transaction_revenue",
    "Non-transaction revenue": "ratings_non_transaction_revenue",
}


def plain(html: str) -> str:
    """Normalize visible SEC table-cell text without retaining markup."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def values(table: str, labels: dict[str, str], scale: Decimal) -> dict[str, list[str]]:
    """Read current/prior quarter values, excluding percent-change cells."""
    found: dict[str, list[str]] = {}
    row: str
    for row in re.findall(r"<tr\b.*?</tr>", table, re.IGNORECASE | re.DOTALL):
        cells: list[str] = [
            plain(cell)
            for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.IGNORECASE | re.DOTALL)
        ]
        label: str = re.sub(r"\s*\*+\s*", "", cells[0]).strip() if cells else ""
        if label not in labels:
            continue
        if "%" in cells:
            continue
        numbers: list[str] = [cell for cell in cells[1:] if re.fullmatch(r"[\d,]+(?:\.\d+)?", cell)]
        # The second occurrence in the revenue table is a percentage mix row.
        if len(numbers) < 2:
            continue
        key: str = labels[label]
        if key in found:
            raise ValueError(f"Duplicate amount row: {label}")
        found[key] = [str(Decimal(number.replace(",", "")) * scale) for number in numbers[:2]]
    if set(found) != set(labels.values()):
        raise ValueError("Expected issuance/revenue rows are incomplete; review the source table.")
    return found


def extract(body: str, source_id: str, year: int, quarter: int) -> list[dict[str, Json]]:
    """Extract two reported calendar quarters; never derive values from rounded totals."""
    tables: list[str] = re.findall(r"<table\b.*?</table>", body, re.IGNORECASE | re.DOTALL)
    billed: list[str] = [
        table for table in tables if "Investment-grade billed issuance" in plain(table)
    ]
    revenue: list[str] = [
        table
        for table in tables
        if "Transaction revenue" in plain(table) and "% of total revenue:" in plain(table)
    ]
    if len(billed) != 1 or len(revenue) != 1:
        raise ValueError("Expected one Ratings billed-issuance table and one revenue table.")
    if "(in billions)" not in plain(billed[0]) or "(in millions)" not in plain(revenue[0]):
        raise ValueError("Source units changed; review the table before extracting.")
    table: str
    for table in (billed[0], revenue[0]):
        header: str = plain(table).split("Investment-grade")[0].split("Revenue")[0]
        if re.findall(r"\b20\d{2}\b", header)[:2] != [str(year), str(year - 1)]:
            raise ValueError("Current/comparative year columns changed; review the table.")
        if quarter > 1 and not re.search(r"Three Months.*Six Months", header):
            raise ValueError("Quarter must precede year-to-date columns; review the table.")
    amounts: dict[str, list[str]] = values(billed[0], BILLED, Decimal(1_000_000_000))
    amounts.update(values(revenue[0], REVENUE, Decimal(1_000_000)))
    end_month: int = quarter * 3
    end_day: int = 31 if end_month in (3, 12) else 30
    result: list[dict[str, Json]] = []
    index: int
    for index in (0, 1):
        period_year: int = year - index
        record: dict[str, Json] = {
            "start": f"{period_year}-{end_month - 2:02d}-01",
            "end": f"{period_year}-{end_month:02d}-{end_day}",
            "fiscal_year": period_year,
            "fiscal_quarter": quarter,
            "currency": "USD",
            "source_refs": {key: [source_id] for key in amounts},
            "notes": [
                "Reported quarter; current and comparative columns, not six-month totals.",
                "Billed issuance was reported in USD billions; revenue in USD millions. "
                "Values normalized to USD.",
                "Reported components may differ from the total because of rounding.",
                "Billed issuance excludes frequent-issuer programs, unrated debt and most "
                "international public finance.",
            ],
        }
        record.update({key: pair[index] for key, pair in amounts.items()})
        result.append(record)
    return result


def build(research_dir: Path) -> dict[str, Json]:
    """Fetch or replay the two pinned filings, retaining original bytes and hashes."""
    research_dir.mkdir(parents=True, exist_ok=True)
    periods: list[Json] = []
    sources: list[Json] = []
    source_id: str
    url: str
    filed: str
    year: int
    quarter: int
    for source_id, url, filed, year, quarter in FILINGS:
        path: Path = research_dir / f"{year}-q{quarter}.html"
        if not path.exists():
            identity: str = os.environ.get("EDGAR_IDENTITY", "")
            if not identity:
                raise ValueError(
                    "Set EDGAR_IDENTITY to fetch SEC filings, or supply the cached original HTML."
                )
            request: urllib.request.Request = urllib.request.Request(
                url, headers={"User-Agent": identity}
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                payload: bytes = response.read(20_000_001)
            if len(payload) > 20_000_000:
                raise ValueError("SEC filing exceeds the 20 MB pilot limit.")
            path.write_bytes(payload)
        body: bytes = path.read_bytes()
        sources.append(
            {
                "id": source_id,
                "url": url,
                "accession": url.split("/")[-2],
                "filed_date": filed,
                "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        periods.extend(extract(body.decode(), source_id, year, quarter))
    return {"spgi_periods": periods, "sources": sources}


def main() -> None:
    """Write a replayable pilot supplement; input/output locations are explicit."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--research-dir",
        type=Path,
        required=True,
        help="Ignored directory for original SPGI HTML",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output supplement JSON; amounts are absolute USD",
    )
    args: argparse.Namespace = parser.parse_args()
    args.output.write_text(json.dumps(build(args.research_dir), indent=2) + "\n")


if __name__ == "__main__":
    main()
