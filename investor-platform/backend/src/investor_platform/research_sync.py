"""Explicit SEC history import; API reads never initiate network requests."""

import argparse
import json
import os
import re
import time
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID
from xml.etree import ElementTree as ET

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from .db import LOCAL_WORKSPACE, make_engine
from .models import ResearchFiling, ResearchHolding, ResearchManager
from .research import HoldingKey, Position, quarter_end
from .research_eligibility import Eligibility, manager_eligibility

CATALOG: Path = Path(__file__).with_name("research_managers.json")


class FilingMetadata(TypedDict):
    """SEC submission index facts needed for one historical filing."""

    accession: str
    report_period: str
    filed_date: str
    form: str
    primary_document: str


def seed_catalog(session: Session, path: Path = CATALOG) -> int:
    """Idempotently load reviewed public registry metadata into the workspace."""
    profiles: list[dict] = json.loads(path.read_text())
    profile: dict
    for profile in profiles:
        manager: ResearchManager | None = session.scalar(
            select(ResearchManager).where(
                ResearchManager.workspace_id == LOCAL_WORKSPACE,
                ResearchManager.cik == str(int(profile["cik"])),
            )
        )
        if manager is None:
            manager = ResearchManager(
                workspace_id=LOCAL_WORKSPACE,
                slug=profile["slug"],
                cik=str(int(profile["cik"])),
                profile=profile,
            )
            session.add(manager)
        else:
            manager.slug = profile["slug"]
            manager.profile = profile
    session.flush()
    return len(profiles)


class SECClient:
    """Bounded standard-library SEC requests with contact identity and pacing."""

    def __init__(self, identity: str) -> None:
        """Require a descriptive contact identity before network requests."""
        if "@" not in identity or "\n" in identity or "\r" in identity:
            raise ValueError("Set EDGAR_IDENTITY to a name and contact email")
        self.identity: str = identity

    def read(self, url: str) -> bytes:
        """Read a public SEC URL with a strict size limit and request pacing."""
        if urlsplit(url).hostname not in {"www.sec.gov", "data.sec.gov"}:
            raise ValueError("SEC requests must use official SEC hosts")
        time.sleep(0.15)
        request: Request = Request(url, headers={"User-Agent": self.identity})
        with urlopen(request, timeout=30) as response:
            payload: bytes = response.read(20_000_001)
        if len(payload) > 20_000_000:
            raise ValueError("SEC document exceeds the import size limit")
        return payload

    def json(self, url: str) -> dict:
        """Read a SEC JSON document."""
        return json.loads(self.read(url))


def submission_rows(
    data: dict,
    start_year: int,
    *,
    start_period: date | None = None,
    end_period: date | None = None,
) -> list[FilingMetadata]:
    """Select original and amended holdings filings from an index page."""
    rows: list[FilingMetadata] = []
    forms: list[str] = data.get("form", [])
    index: int
    form: str
    for index, form in enumerate(forms):
        if form not in {"13F-HR", "13F-HR/A"}:
            continue
        period: str = data.get("reportDate", [""] * len(forms))[index]
        if not period or int(period[:4]) < start_year:
            continue
        report_period: date = date.fromisoformat(period)
        if (start_period is not None and report_period < start_period) or (
            end_period is not None and report_period > end_period
        ):
            continue
        rows.append(
            FilingMetadata(
                accession=data["accessionNumber"][index],
                report_period=period,
                filed_date=data["filingDate"][index],
                form=form,
                primary_document=data["primaryDocument"][index],
            )
        )
    return rows


def filings_for(
    client: SECClient,
    cik: str,
    start_year: int,
    *,
    start_period: date | None = None,
    end_period: date | None = None,
) -> list[FilingMetadata]:
    """Include historical SEC submission pages, not just the recent index."""
    data: dict = client.json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    rows: list[FilingMetadata] = submission_rows(
        data["filings"]["recent"], start_year, start_period=start_period, end_period=end_period
    )
    archive: dict
    for archive in data["filings"].get("files", []):
        if archive["filingTo"][:4] < str(start_year):
            continue
        historical: dict = client.json("https://data.sec.gov/submissions/" + archive["name"])
        rows.extend(
            submission_rows(
                historical, start_year, start_period=start_period, end_period=end_period
            )
        )
    return sorted(rows, key=lambda row: (row["report_period"], row["filed_date"], row["accession"]))


def element_text(element: ET.Element, name: str) -> str:
    """Find a tag without depending on a particular SEC namespace."""
    child: ET.Element
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1].lower() == name.lower():
            return (child.text or "").strip()
    return ""


def parse_holdings(payload: bytes, filed_date: date) -> list[Position]:
    """Normalize table rows and aggregate duplicate identities using exact arithmetic."""
    root: ET.Element = ET.fromstring(payload)
    positions: dict[HoldingKey, Position] = {}
    row: ET.Element
    for row in root.iter():
        if row.tag.rsplit("}", 1)[-1].lower() != "infotable":
            continue
        cusip: str = element_text(row, "cusip").upper()
        security_class: str = element_text(row, "titleOfClass").upper()
        put_call: str = element_text(row, "putCall").upper()
        share_type: str = element_text(row, "sshPrnamtType").upper()
        quantity: Decimal = Decimal(element_text(row, "sshPrnamt"))
        multiplier: Decimal = Decimal(1) if filed_date >= date(2023, 1, 3) else Decimal(1000)
        value: Decimal = Decimal(element_text(row, "value")) * multiplier
        if (
            len(cusip) != 9
            or not security_class
            or share_type not in {"SH", "PRN"}
            or put_call not in {"", "PUT", "CALL"}
            or not quantity.is_finite()
            or not value.is_finite()
            or quantity < 0
            or value < 0
        ):
            raise ValueError("Invalid SEC holding identity or quantity")
        key: HoldingKey = (cusip, put_call, share_type)
        if key in positions:
            positions[key]["quantity"] += quantity
            positions[key]["value_usd"] += value
        else:
            positions[key] = Position(
                cusip=cusip,
                issuer=element_text(row, "nameOfIssuer"),
                security_class=security_class,
                put_call=put_call,
                share_type=share_type,
                quantity=quantity,
                value_usd=value,
            )
    return list(positions.values())


def parse_report_period(value: str) -> date:
    """Accept SEC ISO dates and historical month-first date formats."""
    format_string: str
    for format_string in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, format_string).date()
        except ValueError:
            continue
    raise ValueError("Unrecognized SEC report period")


def store_filing(
    session: Session,
    manager: ResearchManager,
    metadata: FilingMetadata,
    primary: bytes,
    table: bytes,
    source_url: str,
    table_url: str,
    *,
    retry_blocked: bool = False,
) -> ResearchFiling:
    """Retain normalized evidence and record incomplete tables without false changes."""
    existing: ResearchFiling | None = session.scalar(
        select(ResearchFiling).where(
            ResearchFiling.manager_id == manager.id,
            ResearchFiling.accession == metadata["accession"],
        )
    )
    if existing is not None and (not retry_blocked or existing.status != "blocked"):
        return existing
    root: ET.Element = ET.fromstring(primary)
    amendment: str | None = element_text(root, "amendmentType").upper() or None
    period: date = date.fromisoformat(metadata["report_period"])
    filed: date = date.fromisoformat(metadata["filed_date"])
    positions: list[Position] = []
    error: str | None = None
    try:
        positions = parse_holdings(table, filed)
        declared: str = element_text(root, "tableEntryTotal")
        raw_root: ET.Element = ET.fromstring(table)
        row_count: int = sum(
            1 for node in raw_root.iter() if node.tag.rsplit("}", 1)[-1].lower() == "infotable"
        )
        if not declared or int(declared) != row_count:
            error = "Reported table count does not match imported rows"
        reported_period: str = element_text(root, "reportCalendarOrQuarter")
        if reported_period:
            parsed_period: date = parse_report_period(reported_period)
            if parsed_period != period:
                error = "Primary filing report period differs from the SEC index"
        declared_value: str = element_text(root, "tableValueTotal")
        if declared_value:
            multiplier: Decimal = Decimal(1) if filed >= date(2023, 1, 3) else Decimal(1000)
            actual_value: Decimal = sum(
                (position["value_usd"] for position in positions), Decimal(0)
            )
            if Decimal(declared_value) * multiplier != actual_value:
                error = "Reported table value does not match imported rows"
        if not quarter_end(period):
            error = "Report period is not a calendar quarter end"
        if element_text(root, "isConfidentialOmitted").lower() in {"true", "1"}:
            error = "Confidential holdings omitted; complete comparison unavailable"
    except (ValueError, InvalidOperation, ET.ParseError):
        error = "Could not validate the complete information table"
    evidence: dict = {
        "primary_url": source_url,
        "table_url": table_url,
        "table_entry_total": element_text(root, "tableEntryTotal"),
        "value_unit": "USD" if filed >= date(2023, 1, 3) else "USD thousands",
    }
    filing: ResearchFiling
    if existing is None:
        filing = ResearchFiling(
            manager_id=manager.id,
            accession=metadata["accession"],
            report_period=period,
            filed_date=filed,
            form=metadata["form"],
            source_url=source_url,
            amendment_type=amendment,
            status="blocked" if error else "complete",
            reason=error,
            evidence=evidence,
        )
        session.add(filing)
        session.flush()
    else:
        filing = existing
        previous_holdings: list[ResearchHolding] = list(
            session.scalars(select(ResearchHolding).where(ResearchHolding.filing_id == filing.id))
        )
        attempts: list[dict] = list(filing.evidence.get("previous_import_attempts", []))
        attempts.append(
            {
                "status": filing.status,
                "reason": filing.reason,
                "evidence": {
                    key: value
                    for key, value in filing.evidence.items()
                    if key != "previous_import_attempts"
                },
                "holdings": [
                    {
                        "cusip": holding.cusip,
                        "issuer": holding.issuer,
                        "security_class": holding.security_class,
                        "put_call": holding.put_call,
                        "share_type": holding.share_type,
                        "quantity": str(holding.quantity),
                        "value_usd": str(holding.value_usd),
                    }
                    for holding in previous_holdings
                ],
            }
        )
        evidence["previous_import_attempts"] = attempts
        filing.evidence = evidence
        filing.status = "blocked" if error else "complete"
        filing.reason = error
        filing.amendment_type = amendment
        session.execute(delete(ResearchHolding).where(ResearchHolding.filing_id == filing.id))
        session.flush()
    position: Position
    for position in positions:
        session.add(ResearchHolding(filing_id=filing.id, **position))
    session.flush()
    return filing


def sync_manager(
    client: SECClient,
    session: Session,
    manager: ResearchManager,
    start_year: int,
    *,
    retry_blocked: bool = False,
    start_period: date | None = None,
    end_period: date | None = None,
) -> int:
    """Import independently reviewable filings, leaving previously imported records intact."""
    rows: list[FilingMetadata] = filings_for(
        client, manager.cik, start_year, start_period=start_period, end_period=end_period
    )
    imported: int = 0
    metadata: FilingMetadata
    for metadata in rows:
        existing: ResearchFiling | None = session.scalar(
            select(ResearchFiling).where(
                ResearchFiling.manager_id == manager.id,
                ResearchFiling.accession == metadata["accession"],
            )
        )
        if existing is not None and (not retry_blocked or existing.status != "blocked"):
            continue
        base: str = (
            f"https://www.sec.gov/Archives/edgar/data/{int(manager.cik)}/"
            f"{metadata['accession'].replace('-', '')}/"
        )
        source_url: str = base + metadata["primary_document"].rsplit("/", 1)[-1]
        primary: bytes = client.read(source_url)
        index: dict = client.json(base + "index.json")
        candidates: list[str] = [
            item["name"]
            for item in index["directory"]["item"]
            if item["name"].lower().endswith(".xml")
            and item["name"] != metadata["primary_document"].rsplit("/", 1)[-1]
        ]
        tables: list[tuple[str, bytes]] = []
        name: str
        for name in candidates:
            content: bytes = client.read(base + name)
            try:
                root: ET.Element = ET.fromstring(content)
                if root.tag.rsplit("}", 1)[-1].lower() == "informationtable" or any(
                    node.tag.rsplit("}", 1)[-1].lower() == "infotable" for node in root.iter()
                ):
                    tables.append((base + name, content))
            except ET.ParseError:
                continue
        table_url: str
        table: bytes
        if len(tables) == 1:
            table_url, table = tables[0]
        else:
            table_url, table = base + "index.json", b"<informationTable/>"
        stored: ResearchFiling = store_filing(
            session,
            manager,
            metadata,
            primary,
            table,
            source_url,
            table_url,
            retry_blocked=retry_blocked,
        )
        if len(tables) != 1:
            stored.status = "blocked"
            stored.reason = "Expected exactly one information table; review filing documents"
        session.commit()
        imported += 1
    return imported


def quarter_window(quarters: int, through_quarter: str, today: date) -> tuple[date, date]:
    """Return exactly N inclusive calendar quarter ends without guessing the latest filing."""
    if quarters <= 0:
        raise ValueError("--quarters must be positive")
    if not re.fullmatch(r"[0-9]{4}-Q[1-4]", through_quarter):
        raise ValueError("--through-quarter must use YYYY-QN, for example 2026-Q2")
    year: int = int(through_quarter[:4])
    quarter: int = int(through_quarter[-1])
    end_month: int = quarter * 3
    end: date = date(year, end_month, monthrange(year, end_month)[1])
    first_ordinal: int = year * 4 + quarter - quarters
    first_year: int = first_ordinal // 4
    first_month: int = (first_ordinal % 4 + 1) * 3
    if first_year < 1999:
        raise ValueError("The requested quarter window must start in 1999 or later")
    if end > today:
        raise ValueError("--through-quarter must not be in the future")
    start: date = date(first_year, first_month, monthrange(first_year, first_month)[1])
    return start, end


def filing_counts(
    session: Session,
    manager_id: UUID,
    start_year: int,
    *,
    start_period: date | None = None,
    end_period: date | None = None,
) -> dict[str, int]:
    """Count saved original and amended filings in the requested report-period scope."""
    query: Select[tuple[int, int]] = select(
        func.count().filter(ResearchFiling.status == "complete"),
        func.count().filter(ResearchFiling.status == "blocked"),
    ).where(
        ResearchFiling.manager_id == manager_id,
        ResearchFiling.report_period >= (start_period or date(start_year, 1, 1)),
        ResearchFiling.form.in_(["13F-HR", "13F-HR/A"]),
    )
    if end_period is not None:
        query = query.where(ResearchFiling.report_period <= end_period)
    complete: int
    blocked: int
    complete, blocked = session.execute(query).one()
    return {"complete_filings": complete, "blocked_filings": blocked}


def main() -> None:
    """Seed reviewed metadata or explicitly collect official SEC history."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Fetch and parse SEC 13F filings, then persist holdings and source evidence."
    )
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Load reviewed manager metadata only; do not fetch SEC filings",
    )
    parser.add_argument(
        "--retry-blocked",
        action="store_true",
        help="Re-fetch blocked filings while preserving prior import evidence",
    )
    parser.add_argument("--manager", help="Registry slug; omitted means every manager in scope")
    parser.add_argument(
        "--quarters",
        type=int,
        help="Collect exactly this many report quarters; requires --through-quarter",
    )
    parser.add_argument("--through-quarter", help="Inclusive final report quarter, such as 2026-Q2")
    parser.add_argument(
        "--all-investors",
        action="store_true",
        help="Collect existing database investors regardless of AUM eligibility",
    )
    default_start_year: int = date.today().year - 10
    parser.add_argument(
        "--start-year",
        type=int,
        help=f"Include report quarters from January 1 of this year (default: {default_start_year})",
    )
    args: argparse.Namespace = parser.parse_args()
    if args.through_quarter and args.quarters is None:
        parser.error("--through-quarter requires --quarters")
    if args.quarters is not None and (not args.through_quarter or args.start_year is not None):
        parser.error(
            "--quarters requires --through-quarter and cannot be combined with --start-year"
        )
    if args.all_investors and args.manager:
        parser.error("--all-investors cannot be combined with --manager")
    if args.catalog_only and (args.quarters is not None or args.all_investors):
        parser.error("--catalog-only cannot be combined with bounded or all-investor ingestion")
    start_period: date | None = None
    end_period: date | None = None
    start_year: int = args.start_year if args.start_year is not None else default_start_year
    if args.quarters is not None:
        try:
            start_period, end_period = quarter_window(
                args.quarters, args.through_quarter, date.today()
            )
        except ValueError as error:
            parser.error(str(error))
        start_year = start_period.year
    if not 1999 <= start_year <= date.today().year:
        parser.error("--start-year must be between 1999 and the current year")
    client: SECClient | None = None
    with Session(make_engine(), expire_on_commit=False) as session:
        existing_only: bool = args.quarters is not None or args.all_investors
        if not existing_only:
            count: int = seed_catalog(session)
            session.commit()
            if args.catalog_only:
                print(json.dumps({"seeded_managers": count}))
                return
        query: Select[tuple[ResearchManager]] = (
            select(ResearchManager)
            .where(ResearchManager.workspace_id == LOCAL_WORKSPACE)
            .order_by(ResearchManager.slug)
        )
        if args.manager:
            query = query.where(ResearchManager.slug == args.manager)
        managers: list[ResearchManager] = list(session.scalars(query))
        if not managers:
            parser.error("No matching manager in the workspace database")
        manager: ResearchManager
        failed: bool = False
        for manager in managers:
            eligibility: Eligibility = manager_eligibility(manager.profile, date.today())
            if not args.all_investors and eligibility["status"] != "eligible":
                print(
                    json.dumps(
                        {
                            "manager": manager.slug,
                            "status": "skipped",
                            "reason": eligibility["reason"],
                            **filing_counts(
                                session,
                                manager.id,
                                start_year,
                                start_period=start_period,
                                end_period=end_period,
                            ),
                        }
                    ),
                    flush=True,
                )
                continue
            if client is None:
                try:
                    client = SECClient(os.environ.get("EDGAR_IDENTITY", ""))
                except ValueError as error:
                    parser.error(str(error))
            try:
                imported: int = sync_manager(
                    client,
                    session,
                    manager,
                    start_year,
                    retry_blocked=args.retry_blocked,
                    start_period=start_period,
                    end_period=end_period,
                )
                print(
                    json.dumps(
                        {
                            "manager": manager.slug,
                            "imported_filings": imported,
                            **filing_counts(
                                session,
                                manager.id,
                                start_year,
                                start_period=start_period,
                                end_period=end_period,
                            ),
                        }
                    ),
                    flush=True,
                )
            except (HTTPError, URLError, ValueError, ET.ParseError) as error:
                session.rollback()
                failed = True
                reason: str = (
                    f"SEC HTTP {error.code}; retry later"
                    if isinstance(error, HTTPError)
                    else "SEC history import failed; retry or review the source filing"
                )
                print(
                    json.dumps(
                        {
                            "manager": manager.slug,
                            "status": "failed",
                            "reason": reason,
                            **filing_counts(
                                session,
                                manager.id,
                                start_year,
                                start_period=start_period,
                                end_period=end_period,
                            ),
                        }
                    ),
                    flush=True,
                )
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
