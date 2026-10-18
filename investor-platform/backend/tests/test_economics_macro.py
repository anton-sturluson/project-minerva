"""Native macro source schemas, calendar calculations and revision lineage."""

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.economics.collection import Payload, admit
from investor_platform.economics.macro import (
    parse_bea,
    parse_fed_equity,
    parse_fed_h15,
    parse_fed_targets,
    parse_shiller_rows,
    shiller_workbook_url,
)
from investor_platform.economics.parsers import Fact, number
from investor_platform.economics.registry import SERIES, Series
from investor_platform.economics.routes import current_rows
from investor_platform.economics.views import Point, points_for
from investor_platform.models import EconomicObservation


def definition(key: str) -> Series:
    """Find a production registry definition for a synthetic measurement."""
    return next(item for item in SERIES if item.key == key)


def accepted(key: str, day: str, value: str | None, identity: int) -> EconomicObservation:
    """Build an accepted numeric revision with sufficient source lineage."""
    return EconomicObservation(
        id=identity,
        workspace_id=LOCAL_WORKSPACE,
        series_key=key,
        observation_date=date.fromisoformat(day),
        value=Decimal(value) if value is not None else None,
        missing=value is None,
        collected_at=datetime(2026, 10, 18, tzinfo=UTC),
        provenance={
            "sha256": "a" * 64,
            "source_url": "https://example.com/source",
            "footnotes": [],
            "derived_from": [],
        },
    )


def test_signed_values_and_calendar_growth_do_not_bridge_missing_months() -> None:
    """Accept negative growth but require the actual prior-year calendar month."""
    assert number("-2.5", signed=True) == Decimal("-2.5")
    with pytest.raises(ValueError):
        number("-2.5")
    rows: list[EconomicObservation] = [
        accepted("cpi-index", "2025-01-01", "100", 1),
        accepted("cpi-index", "2025-03-01", "104", 2),
        accepted("cpi-index", "2026-01-01", "99", 3),
        accepted("cpi-index", "2026-02-01", "103", 4),
    ]
    points: list[Point] = points_for(definition("headline-inflation"), rows)
    assert points[-2].value == Decimal("-1.00")
    assert points[-1].value is None
    assert [ref["observation_id"] for ref in points[-2].derived_from] == [3, 1]
    rows[0].value = Decimal("0")
    assert points_for(definition("headline-inflation"), rows)[-2].value is None


def test_payroll_average_requires_contiguous_levels() -> None:
    """Compute the mean of three changes and reject a missing intermediate month."""
    rows: list[EconomicObservation] = [
        accepted("payrolls", "2026-01-01", "100", 1),
        accepted("payrolls", "2026-02-01", "103", 2),
        accepted("payrolls", "2026-03-01", "101", 3),
        accepted("payrolls", "2026-04-01", "106", 4),
    ]
    assert points_for(definition("payroll-growth"), rows)[-1].value == Decimal("5")
    assert points_for(definition("payroll-growth-3m"), rows)[-1].value == Decimal("2")
    assert points_for(definition("payroll-growth-3m"), rows[:1] + rows[2:])[-1].value is None


def test_equity_gdp_uses_same_quarter_and_explicit_million_billion_units() -> None:
    """Match quarter periods and retain both accepted inputs for the proxy."""
    rows: list[EconomicObservation] = [
        accepted("public-equity", "2026-06-30", "100000000", 1),
        accepted("nominal-gdp", "2026-04-01", "25000", 2),
    ]
    point: Point = points_for(definition("equity-gdp"), rows)[0]
    assert point.value == Decimal("400") and len(point.derived_from) == 2
    rows[1].observation_date = date(2026, 1, 1)
    assert points_for(definition("equity-gdp"), rows)[0].value is None


def test_shiller_standard_cape_dates_precision_and_provisional_months() -> None:
    """Distinguish CAPE from TR CAPE and mark both estimated-CPI months."""
    rows: list[list[str | float | int]] = [
        ["Date", "TR CAPE", "CAPE"],
        [1871.01, "NA", "NA"],
        [2026.08, 43.1, 40.123456789],
        [2026.09, 43.2, 40.223456789],
        [2026.1, 43.3, 40.323456789],
        ["", "Oct price is Oct 2nd close", "Sept/Oct CPI estimated"],
    ]
    facts: list[Fact] = parse_shiller_rows(rows)
    assert len(facts) == 3 and facts[-1].date == date(2026, 10, 1)
    assert facts[-1].value == Decimal("40.323457")
    assert facts[-1].derived_from[0]["value"] == "40.323456789"
    assert not facts[0].footnotes and facts[1].footnotes[0]["code"] == "provisional"
    assert "Oct 2nd" in facts[-1].footnotes[0]["text"]
    assert facts[-1].locator == "Data:row5:CAPE"
    assert (
        shiller_workbook_url(b'<a href="https://img1.wsimg.com/data/ie_data.xls?v=2">Download</a>')
        == "https://img1.wsimg.com/data/ie_data.xls?v=2"
    )
    with pytest.raises(ValueError):
        shiller_workbook_url(b'<a href="https://example.com/ie_data.xls">Download</a>')


def bea_workbook(
    *, wrong_units: bool = False, released: str = "Data published January 1, 2026"
) -> bytes:
    """Create the two synthetic quarterly BEA tables with named codes and units."""
    workbook: openpyxl.Workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    sheet_name: str
    code: str
    units: str
    values: tuple[int, int]
    for sheet_name, code, units, values in (
        ("T10101-Q", "A191RL", "[Percent] Seasonally adjusted at annual rates", (-2, 3)),
        (
            "T10105-Q",
            "A191RC",
            "[Millions of dollars] Seasonally adjusted at annual rates",
            (25000000, 26000000),
        ),
    ):
        sheet: Worksheet = workbook.create_sheet(sheet_name)
        sheet.append(["Synthetic BEA table"])
        sheet.append(["Wrong units" if wrong_units else units])
        sheet.append(["Quarterly"])
        sheet.append(["Bureau of Economic Analysis"])
        sheet.append([released])
        sheet.append(["File created"])
        sheet.append([None])
        sheet.append(["Line", None, None, "2026Q1", "2026Q2"])
        sheet.append(["1", "GDP", code, *values])
    stream: io.BytesIO = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_bea_units_signed_growth_and_release_metadata_do_not_duplicate_facts() -> None:
    """Convert native GDP millions once; publication date changes do not alter old facts."""
    facts: list[Fact] = parse_bea(bea_workbook(), 1)
    assert next(f.value for f in facts if f.series_key == "nominal-gdp") == Decimal("25000")
    assert next(f.value for f in facts if f.series_key == "real-gdp-growth") == Decimal("-2")
    assert facts == parse_bea(bea_workbook(released="Data published February 1, 2026"), 1)
    with pytest.raises(ValueError):
        parse_bea(bea_workbook(wrong_units=True), 1)


def test_fed_target_events_and_named_daily_yield_missing_values() -> None:
    """Retain effective policy events and preserve the publisher's missing-yield markers."""
    facts: list[Fact] = parse_fed_targets(b"2026-01-01T00:00:00Z,3/19/2026\n3.5,3.25\n3.75,3.5\n")
    assert len(facts) == 4 and facts[-1].date == date(2026, 3, 19)
    with pytest.raises(ValueError):
        parse_fed_targets(b"2026-01-01\n4\n3\n")
    body: bytes = (
        b"Series Description,10-year\nUnit:,Percent:_Per_Year\nMultiplier:,1\n"
        b"Currency:,NA\nUnique Identifier:,H15/H15/RIFLGFCY10_N.B\n"
        b"Time Period,RIFLGFCY10_N.B\n2026-01-01,ND\n2026-01-02,-0.01\n"
    )
    yields: list[Fact] = parse_fed_h15(body)
    assert yields[0].value is None and yields[1].value == Decimal("-0.01")
    with pytest.raises(ValueError):
        parse_fed_h15(body.replace(b"Percent:_Per_Year", b"Basis points"))


def test_fed_equity_selects_exact_memo_item_and_keeps_historical_quarter_gaps() -> None:
    """Read the validated named ZIP member without loading the full Financial Accounts archive."""
    stream: io.BytesIO = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("csv/F51_1_s.csv", "date,LM883164115.Q\n1945:Q4,1000\n2026:Q2,2000\n")
        archive.writestr(
            "data_dictionary/F51_1_s.txt",
            "LM883164115.Q\tPublic equity\tMillions of dollars; end of period",
        )
    facts: list[Fact] = parse_fed_equity(stream.getvalue())
    assert [fact.date for fact in facts] == [date(1945, 10, 1), date(2026, 4, 1)]
    assert facts[-1].value == Decimal("2000")


def test_macro_corrections_recompute_views_without_storing_derived_rows(
    database: Engine, tmp_path: Path
) -> None:
    """Recalculate growth from the accepted revised baseline while keeping source levels only."""
    now: datetime = datetime(2026, 10, 18, tzinfo=UTC)
    original: Payload = Payload(
        "https://example.com/data",
        b"synthetic",
        [
            Fact("cpi-index", date(2025, 1, 1), Decimal("100"), "index"),
            Fact("cpi-index", date(2026, 1, 1), Decimal("110"), "index"),
        ],
    )
    with Session(database) as session, session.begin():
        admit(session, LOCAL_WORKSPACE, [original], now, tmp_path)
    with Session(database) as session, session.begin():
        revised: Payload = Payload(
            original.url,
            b"synthetic correction",
            [Fact("cpi-index", date(2025, 1, 1), Decimal("105"), "index")],
        )
        admit(session, LOCAL_WORKSPACE, [revised], now, tmp_path)
    with Session(database) as session:
        rows: list[EconomicObservation] = current_rows(session, LOCAL_WORKSPACE)
        point: Point = points_for(definition("headline-inflation"), rows)[-1]
        assert point.value == (Decimal("110") / Decimal("105") - 1) * 100
        assert point.derived_from[1]["observation_id"] == max(row.id for row in rows)
        assert session.scalar(select(func.count()).select_from(EconomicObservation)) == 3


def test_shiller_provisional_months_match_names_not_substrings() -> None:
    """Do not read month names inside market text or the modal verb may."""
    facts: list[Fact] = parse_shiller_rows(
        [
            ["Date", "CAPE", "TR CAPE"],
            [2026.03, 30.0, 31.0],
            [2026.05, 31.0, 32.0],
            [2026.1, 32.0, 33.0],
            ["", "The market CPI may be estimated; Oct CPI estimated", ""],
        ]
    )
    assert not facts[0].footnotes and not facts[1].footnotes
    assert facts[2].footnotes[0]["code"] == "provisional"


def test_shiller_provisional_months_cross_the_year_boundary() -> None:
    """Mark the previous December when a January workbook estimates both CPI months."""
    facts: list[Fact] = parse_shiller_rows(
        [
            ["Date", "CAPE", "TR CAPE"],
            [2026.01, 29.0, 30.0],
            [2026.11, 30.0, 31.0],
            [2026.12, 31.0, 32.0],
            [2027.01, 32.0, 33.0],
            ["", "December and January CPI are estimated", ""],
        ]
    )
    assert not facts[0].footnotes and not facts[1].footnotes
    assert all(fact.footnotes[0]["code"] == "provisional" for fact in facts[-2:])
