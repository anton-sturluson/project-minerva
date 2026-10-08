"""Verify public snapshot storage and conservative quarter comparisons."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from investor_platform.models import ResearchFiling, ResearchHolding, ResearchManager
from investor_platform.research import HoldingKey, Position, compare_positions, previous_quarter
from investor_platform.research_sync import (
    FilingMetadata,
    parse_holdings,
    seed_catalog,
    store_filing,
)


def registry(database: Engine, tmp_path: Path) -> UUID:
    """Load a synthetic catalog twice to verify idempotent persistence."""
    path: Path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [
                {
                    "slug": "example",
                    "name": "Example Capital",
                    "cik": "1234",
                    "investor_names": ["Example Investor"],
                    "website_url": "https://example.com",
                    "letters_url": None,
                    "focus": "Technology",
                    "source_urls": ["https://example.com"],
                    "aum_usd": "100000000",
                    "aum_as_of": "2026-01-01",
                    "aum_source_url": "https://example.com/aum",
                    "aum_measurement": "firm_aum",
                }
            ]
        )
    )
    with Session(database) as session:
        seed_catalog(session, path)
        seed_catalog(session, path)
        session.commit()
        manager_id: UUID = session.scalar(select(ResearchManager.id))
        return manager_id


def row(quantity: str, value: str, *, option: str = "", cusip: str = "123456789") -> str:
    """Create one synthetic SEC row with option identity."""
    return (
        f"<infoTable><nameOfIssuer>Example</nameOfIssuer><titleOfClass>COM</titleOfClass>"
        f"<cusip>{cusip}</cusip><value>{value}</value><putCall>{option}</putCall>"
        f"<shrsOrPrnAmt><sshPrnamt>{quantity}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
        "</shrsOrPrnAmt></infoTable>"
    )


def filing(
    database: Engine,
    manager_id: UUID,
    period: str,
    accession: str,
    rows: str,
    *,
    amendment: str | None = None,
    count: int = 1,
) -> None:
    """Parse XML and persist through the production importer in an isolated schema."""
    primary: bytes = (
        f"<edgarSubmission><tableEntryTotal>{count}</tableEntryTotal>"
        f"<amendmentType>{amendment or ''}</amendmentType></edgarSubmission>"
    ).encode()
    table: bytes = f"<informationTable>{rows}</informationTable>".encode()
    metadata: FilingMetadata = {
        "accession": accession,
        "report_period": period,
        "filed_date": "2026-08-01",
        "form": "13F-HR/A" if amendment else "13F-HR",
        "primary_document": "primary.xml",
    }
    with Session(database) as session:
        manager: ResearchManager = session.get(ResearchManager, manager_id)
        store_filing(
            session,
            manager,
            metadata,
            primary,
            table,
            "https://www.sec.gov/example/primary.xml",
            "https://www.sec.gov/example/table.xml",
        )
        session.commit()


def test_persistence_quantities_options_and_duplicates(
    database: Engine,
    db_client: TestClient,
    tmp_path: Path,
) -> None:
    """Price changes stay unchanged while options compare independently."""
    manager_id: UUID = registry(database, tmp_path)
    managers: list[dict] = db_client.get("/api/research/managers").json()["managers"]
    assert len(managers) == 1
    assert managers[0]["coverage"]["continuous_decade"] is False
    old: str = row("10", "100") + row("5", "50") + row("2", "20", option="PUT")
    new: str = (row("15", "900") + row("4", "40", option="PUT")).replace(
        "<titleOfClass>COM</titleOfClass>", "<titleOfClass>COMMON STOCK</titleOfClass>"
    )
    filing(database, manager_id, "2026-03-31", "old", old, count=3)
    filing(database, manager_id, "2026-06-30", "new", new, count=2)
    filing(database, manager_id, "2026-06-30", "new", new, count=2)
    response: dict = db_client.get(
        "/api/research/managers/example/changes?quarter=2026-06-30"
    ).json()
    assert response["status"] == "available"
    assert [(item["put_call"], item["kind"]) for item in response["changes"]] == [
        ("PUT", "increased"),
        ("", "unchanged"),
    ]
    assert Decimal(response["changes"][1]["current_quantity"]) == 15
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(ResearchFiling)) == 2
        assert session.scalar(select(func.count()).select_from(ResearchHolding)) == 4


def test_gaps_incomplete_and_restatement_recovery(
    database: Engine,
    db_client: TestClient,
    tmp_path: Path,
) -> None:
    """Missing and partial quarters block false exits; restatements recover them."""
    manager_id: UUID = registry(database, tmp_path)
    filing(database, manager_id, "2025-12-31", "older", row("5", "50"))
    filing(database, manager_id, "2026-06-30", "latest", row("6", "60"))
    endpoint: str = "/api/research/managers/example/changes?quarter=2026-06-30"
    assert db_client.get(endpoint).json()["status"] == "unavailable"
    filing(database, manager_id, "2026-03-31", "a", row("5", "50"), count=2)
    assert "count" in db_client.get(endpoint).json()["reason"]
    filing(database, manager_id, "2026-03-31", "b", row("5", "50"), amendment="RESTATEMENT")
    assert db_client.get(endpoint).json()["status"] == "available"
    filing(database, manager_id, "2026-06-30", "z", row("1", "10"), amendment="NEW HOLDINGS")
    assert db_client.get(endpoint).json()["status"] == "unavailable"
    assert "overlaps" in db_client.get(endpoint).json()["reason"]
    assert db_client.get(endpoint.replace("2026-06-30", "2026-06-01")).status_code == 422


def test_value_units_and_quarter_arithmetic() -> None:
    """Normalize historical thousands and contemporary dollars exactly."""
    table: bytes = f"<informationTable>{row('2', '100')}</informationTable>".encode()
    assert parse_holdings(table, date(2022, 11, 15))[0]["value_usd"] == 100000
    assert parse_holdings(table, date(2023, 2, 15))[0]["value_usd"] == 100
    assert previous_quarter(date(2026, 3, 31)) == date(2025, 12, 31)


def test_coverage_requires_complete_contiguous_latest_quarters(
    database: Engine,
    db_client: TestClient,
    tmp_path: Path,
) -> None:
    """Operating age cannot substitute for actual forty-quarter imported coverage."""
    manager_id: UUID = registry(database, tmp_path)
    quarter: date = date(2026, 6, 30)
    index: int
    with Session(database) as session:
        for index in range(40):
            session.add(
                ResearchFiling(
                    manager_id=manager_id,
                    accession=f"coverage-{index}",
                    report_period=quarter,
                    filed_date=date(2026, 8, 1),
                    form="13F-HR",
                    source_url="https://www.sec.gov/example",
                    amendment_type=None,
                    status="complete",
                    reason=None,
                    evidence={},
                )
            )
            quarter = previous_quarter(quarter)
        session.commit()
    endpoint: str = "/api/research/managers/example"
    assert db_client.get(endpoint).json()["coverage"]["continuous_decade"] is True
    with Session(database) as session:
        latest: ResearchFiling = session.scalar(
            select(ResearchFiling).where(ResearchFiling.accession == "coverage-0")
        )
        latest.status = "blocked"
        session.commit()
    assert db_client.get(endpoint).json()["coverage"]["continuous_decade"] is False
    with Session(database) as session:
        latest = session.scalar(
            select(ResearchFiling).where(ResearchFiling.accession == "coverage-0")
        )
        latest.status = "complete"
        middle: ResearchFiling = session.scalar(
            select(ResearchFiling).where(ResearchFiling.accession == "coverage-20")
        )
        session.delete(middle)
        session.commit()
    assert db_client.get(endpoint).json()["coverage"]["continuous_decade"] is False


def test_all_change_kinds_and_disjoint_additions(
    database: Engine,
    db_client: TestClient,
    tmp_path: Path,
) -> None:
    """New and exited positions, reductions and disjoint amendment additions stay exact."""
    manager_id: UUID = registry(database, tmp_path)
    filing(
        database,
        manager_id,
        "2026-03-31",
        "a",
        row("5", "50") + row("2", "20", cusip="987654321"),
        count=2,
    )
    filing(database, manager_id, "2026-06-30", "b", row("3", "30"))
    filing(
        database,
        manager_id,
        "2026-06-30",
        "c",
        row("1", "10", cusip="111111111"),
        amendment="NEW HOLDINGS",
    )
    result: dict = db_client.get("/api/research/managers/example/changes?quarter=2026-06-30").json()
    assert result["status"] == "available"
    assert {item["kind"] for item in result["changes"]} == {"new", "exited", "decreased"}


def test_confidential_and_value_mismatch_are_not_complete(
    database: Engine,
    tmp_path: Path,
) -> None:
    """Incomplete disclosures and inconsistent table totals cannot qualify coverage."""
    manager_id: UUID = registry(database, tmp_path)
    table: bytes = f"<informationTable>{row('2', '100')}</informationTable>".encode()
    metadata: FilingMetadata = {
        "accession": "confidential",
        "report_period": "2026-06-30",
        "filed_date": "2026-08-01",
        "form": "13F-HR",
        "primary_document": "primary.xml",
    }
    primary: bytes = (
        b"<edgarSubmission><tableEntryTotal>1</tableEntryTotal><tableValueTotal>100</tableValueTotal>"
        b"<isConfidentialOmitted>true</isConfidentialOmitted></edgarSubmission>"
    )
    with Session(database) as session:
        manager: ResearchManager = session.get(ResearchManager, manager_id)
        result: ResearchFiling = store_filing(
            session,
            manager,
            metadata,
            primary,
            table,
            "https://www.sec.gov/example/primary.xml",
            "https://www.sec.gov/example/table.xml",
        )
        assert result.status == "blocked"
        assert "Confidential" in result.reason
        metadata["accession"] = "incorrect-total"
        result = store_filing(
            session,
            manager,
            metadata,
            primary.replace(b"true", b"false").replace(b">100<", b">200<"),
            table,
            "https://www.sec.gov/example/primary.xml",
            "https://www.sec.gov/example/table.xml",
        )
        assert result.status == "blocked"
        assert "value" in result.reason
    principal: bytes = table.replace(b">SH<", b">PRN<")
    assert parse_holdings(principal, date(2026, 8, 1))[0]["share_type"] == "PRN"


def test_historical_sec_period_and_explicit_blocked_retry_preserve_evidence(
    database: Engine,
    tmp_path: Path,
) -> None:
    """Recover a failed historical import with real month-first SEC XML date syntax."""
    from investor_platform.research_sync import parse_report_period

    assert parse_report_period("03-31-2016") == date(2016, 3, 31)
    assert parse_report_period("03/31/2016") == date(2016, 3, 31)
    assert parse_report_period("2016-03-31") == date(2016, 3, 31)
    manager_id: UUID = registry(database, tmp_path)
    metadata: FilingMetadata = {
        "accession": "historical",
        "report_period": "2016-03-31",
        "filed_date": "2016-05-15",
        "form": "13F-HR",
        "primary_document": "primary.xml",
    }
    primary: bytes = (
        b"<edgarSubmission><reportCalendarOrQuarter>03-31-2016</reportCalendarOrQuarter>"
        b"<tableEntryTotal>2</tableEntryTotal><tableValueTotal>100</tableValueTotal></edgarSubmission>"
    )
    table: bytes = f"<informationTable>{row('2', '100')}</informationTable>".encode()
    url: str = "https://www.sec.gov/example/primary.xml"
    table_url: str = "https://www.sec.gov/example/table.xml"
    with Session(database) as session:
        manager: ResearchManager = session.get(ResearchManager, manager_id)
        initial: ResearchFiling = store_filing(
            session, manager, metadata, primary, table, url, table_url
        )
        filing_id: UUID = initial.id
        assert initial.status == "blocked"
        repaired_primary: bytes = primary.replace(b"<tableEntryTotal>2", b"<tableEntryTotal>1")
        unchanged: ResearchFiling = store_filing(
            session, manager, metadata, repaired_primary, table, url, table_url
        )
        assert unchanged.status == "blocked"
        repaired: ResearchFiling = store_filing(
            session, manager, metadata, repaired_primary, table, url, table_url, retry_blocked=True
        )
        session.commit()
        assert repaired.id == filing_id
        assert repaired.source_url == url
        assert repaired.accession == "historical"
        assert repaired.status == "complete"
        assert len(repaired.evidence["previous_import_attempts"]) == 1
        prior: dict = repaired.evidence["previous_import_attempts"][0]
        assert prior["status"] == "blocked"
        assert "count" in prior["reason"]
        assert len(prior["holdings"]) == 1
        assert session.scalar(select(func.count()).select_from(ResearchFiling)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchHolding)) == 1
        repaired_quantity: Decimal = session.scalar(select(ResearchHolding.quantity))
        assert repaired_quantity == 2
        store_filing(
            session, manager, metadata, repaired_primary, table, url, table_url, retry_blocked=True
        )
        assert len(repaired.evidence["previous_import_attempts"]) == 1


def test_changes_group_quantity_and_rank_signed_values_with_portfolio_weights(
    database: Engine,
    db_client: TestClient,
    tmp_path: Path,
) -> None:
    """A quantity increase can lose value or weight while price-only changes stay unchanged."""
    manager_id: UUID = registry(database, tmp_path)
    previous: str = (
        row("10", "100", cusip="111111111")
        + row("10", "500", cusip="222222222")
        + row("10", "100", cusip="333333333")
        + row("10", "100", cusip="444444444")
        + row("10", "100", cusip="555555555")
        + row("10", "100", option="PUT", cusip="111111111")
    )
    current: str = (
        row("12", "50", cusip="111111111")
        + row("12", "700", cusip="222222222")
        + row("10", "300", cusip="444444444")
        + row("8", "50", cusip="555555555")
        + row("2", "800", cusip="666666666")
        + row("10", "100", option="PUT", cusip="111111111")
    )
    filing(database, manager_id, "2026-03-31", "previous-values", previous, count=6)
    filing(database, manager_id, "2026-06-30", "current-values", current, count=6)
    response: dict = db_client.get(
        "/api/research/managers/example/changes?quarter=2026-06-30"
    ).json()
    changes: list[dict] = response["changes"]
    assert [(item["category"], item["cusip"], item["put_call"]) for item in changes] == [
        ("increased", "666666666", ""),
        ("increased", "222222222", ""),
        ("increased", "111111111", ""),
        ("decreased", "333333333", ""),
        ("decreased", "555555555", ""),
        ("unchanged", "444444444", ""),
        ("unchanged", "111111111", "PUT"),
    ]
    added: dict = changes[0]
    assert added["kind"] == "new"
    assert Decimal(added["current_weight"]) == Decimal("0.4")
    increased: dict = changes[2]
    assert increased["kind"] == "increased"
    assert Decimal(increased["value_change_usd"]) == -50
    assert Decimal(increased["previous_value_usd"]) == 100
    assert Decimal(increased["current_value_usd"]) == 50
    assert Decimal(increased["previous_weight"]) == Decimal("0.1")
    assert Decimal(increased["current_weight"]) == Decimal("0.025")
    assert Decimal(increased["weight_change"]) == Decimal("-0.075")
    exited: dict = changes[3]
    assert exited["kind"] == "exited"
    assert Decimal(exited["current_weight"]) == 0
    assert Decimal(exited["current_value_usd"]) == 0
    unchanged: dict = changes[5]
    assert unchanged["kind"] == "unchanged"
    assert Decimal(unchanged["value_change_usd"]) == 200
    assert Decimal(unchanged["quantity_change"]) == 0
    assert Decimal(unchanged["current_weight"]) == Decimal("0.15")
    assert sum(Decimal(item["current_weight"]) for item in changes) == 1


def position(
    cusip: str,
    quantity: str,
    value: str,
    *,
    option: str = "",
    share_type: str = "SH",
) -> Position:
    """Create exact synthetic snapshots for arithmetic and deterministic ranking checks."""
    return Position(
        cusip=cusip,
        issuer="Example",
        security_class="COM",
        put_call=option,
        share_type=share_type,
        quantity=Decimal(quantity),
        value_usd=Decimal(value),
    )


def test_comparison_zero_totals_return_unknown_weights_and_ties_are_stable() -> None:
    """Zero totals stay unknown and equal dollar changes sort by the full security identity."""
    current: dict[HoldingKey, Position] = {
        ("222222222", "", "SH"): position("222222222", "2", "50"),
        ("111111111", "PUT", "SH"): position("111111111", "2", "50", option="PUT"),
        ("111111111", "", "SH"): position("111111111", "2", "50"),
        ("111111111", "", "PRN"): position("111111111", "2", "50", share_type="PRN"),
    }
    changes: list[dict] = compare_positions(current, {})
    assert [(item["cusip"], item["put_call"], item["share_type"]) for item in changes] == [
        ("111111111", "", "PRN"),
        ("111111111", "", "SH"),
        ("111111111", "PUT", "SH"),
        ("222222222", "", "SH"),
    ]
    assert all(
        item["previous_weight"] is None and item["weight_change"] is None for item in changes
    )
    assert all(Decimal(item["current_weight"]) == Decimal("0.25") for item in changes)
    exited: list[dict] = compare_positions({}, current)
    assert all(item["current_weight"] is None and item["weight_change"] is None for item in exited)
    zero: dict[HoldingKey, Position] = {
        ("111111111", "", "SH"): position("111111111", "2", "0"),
    }
    empty_values: list[dict] = compare_positions(zero, zero)
    assert empty_values[0]["category"] == "unchanged"
    assert empty_values[0]["previous_weight"] is None
    assert empty_values[0]["current_weight"] is None
    assert empty_values[0]["weight_change"] is None
    assert compare_positions({}, {}) == []


def test_value_ranking_preserves_decimal_cents_beyond_default_precision() -> None:
    """Sorting must retain cents when reported values exceed Decimal's default context."""
    current: dict[HoldingKey, Position] = {
        ("111111111", "", "SH"): position("111111111", "2", "1234567890123456789012345678.01"),
        ("222222222", "", "SH"): position("222222222", "2", "1234567890123456789012345678.02"),
    }
    changes: list[dict] = compare_positions(current, {})
    assert [item["cusip"] for item in changes] == ["222222222", "111111111"]
    assert changes[0]["value_change_usd"] == "1234567890123456789012345678.02"
