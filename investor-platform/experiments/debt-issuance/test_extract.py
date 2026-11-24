"""Check accounting periods, revisions and missing values using synthetic SEC contexts."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from collect import (
    CFO,
    COHORT,
    Fact,
    extract_entity,
    fiscal_window,
    latest,
    quarter_field,
    read_facts,
    validate_snapshot,
)

ENTITY: dict = COHORT[1]


def fact(start: str, end: str, value: str, accession: str = "a") -> Fact:
    """Create one explicitly scoped cash-flow input."""
    return Fact(
        date.fromisoformat(start),
        date.fromisoformat(end),
        Decimal(value),
        accession,
        date(2025, 2, 1),
        "10-K",
        "us-gaap:" + CFO.concept,
        CFO.label,
        CFO.scope,
        "synthetic-facts",
        "https://example.com/filing",
    )


def payload(rows: list[dict], rub: list[dict] | None = None) -> dict:
    """Create companyfacts with a separate, incompatible currency context."""
    return {
        "facts": {
            "us-gaap": {
                CFO.concept: {
                    "label": "Net cash from operations",
                    "units": {"USD": rows, "RUB": rub or []},
                }
            }
        }
    }


def record(start: str, end: str, value: int, *, filed: str = "2025-02-01") -> dict:
    """Use SEC-style exact duration contexts and filing metadata."""
    return {
        "start": start,
        "end": end,
        "val": value,
        "form": "10-K",
        "filed": filed,
        "accn": "0000000000-25-000001",
    }


def test_same_filing_ytd_subtraction_retains_both_inputs() -> None:
    """Subtract cumulative periods only when the filing and measurement scope match."""
    values: list[Fact] = [
        fact("2024-01-01", "2024-06-30", "250"),
        fact("2024-01-01", "2024-03-31", "100"),
    ]
    value: str | None
    detail: dict
    value, detail = quarter_field(
        values, CFO, date(2024, 4, 1), date(2024, 6, 30), date(2024, 1, 1)
    )
    assert value == "150"
    assert detail["status"] == "derived"
    assert [row["value"] for row in detail["derivation_inputs"]] == ["250", "100"]


def test_cross_filing_ytd_is_not_a_quarter() -> None:
    """A prior filing can contain a different scope or a restated amount."""
    values: list[Fact] = [
        fact("2024-01-01", "2024-06-30", "250", "new"),
        fact("2024-01-01", "2024-03-31", "100", "old"),
    ]
    value: str | None
    detail: dict
    value, detail = quarter_field(
        values, CFO, date(2024, 4, 1), date(2024, 6, 30), date(2024, 1, 1)
    )
    assert value is None
    assert detail["status"] == "missing"
    assert "same filing" in detail["reason"]


def test_latest_conflicting_context_requires_review() -> None:
    """Conflicting latest values must not fall back to an older presentation."""
    selected: Fact | None
    reason: str | None
    selected, reason = latest(
        [
            fact("2024-01-01", "2024-03-31", "100"),
            fact("2024-01-01", "2024-03-31", "110"),
        ]
    )
    assert selected is None
    assert reason and "Conflicting" in reason


def test_cutoff_revision_and_currency_selection() -> None:
    """Only the latest allowed USD presentation enters the measurement."""
    raw: dict = payload(
        [
            record("2024-01-01", "2024-03-31", 100),
            record("2024-01-01", "2024-03-31", 110, filed="2025-03-01"),
        ],
        [record("2024-01-01", "2024-03-31", 99999)],
    )
    facts: list[Fact] = read_facts(raw, CFO, ENTITY, {}, date(2025, 2, 15), "facts")
    assert len(facts) == 1
    assert facts[0].value == Decimal(100)
    facts = read_facts(raw, CFO, ENTITY, {}, date(2025, 4, 1), "facts")
    selected: Fact | None = latest(facts)[0]
    assert selected is not None and selected.value == Decimal(110)


def test_reported_ytd_annual_retained_without_invented_quarters() -> None:
    """Annual-only disclosures remain useful while their discrete quarters stay missing."""
    raw: dict = payload(
        [
            record("2024-01-01", "2024-06-30", 250),
            record("2024-01-01", "2024-12-31", 700),
        ]
    )
    rows: list[dict]
    coverage: dict
    rows, coverage = extract_entity(ENTITY, raw, {}, date(2025, 3, 1), "facts")
    reported: dict[int, dict] = {
        row["duration_months"]: row for row in rows if row["duration_months"] != 3
    }
    assert reported[6]["cfo"] == "250"
    assert reported[12]["cfo"] == "700"
    assert reported[12]["presentation"] == "reported_annual"
    assert all(row["cfo"] is None for row in rows if row["duration_months"] == 3)
    assert all(row["cash_capex"] is None for row in rows)
    assert coverage["status"] == "partial"


def test_zero_and_signed_operating_cash_flow_are_reported() -> None:
    """Zero is a source observation; operating cash outflow can be negative."""
    amount: str
    for amount in ("0", "-25"):
        value: str | None
        detail: dict
        value, detail = quarter_field(
            [fact("2024-01-01", "2024-03-31", amount)],
            CFO,
            date(2024, 1, 1),
            date(2024, 3, 31),
            date(2024, 1, 1),
        )
        assert value == amount
        assert detail["status"] == "reported"


def test_fiscal_year_is_not_calendar_or_comparative_frame() -> None:
    """Microsoft and Oracle fiscal quarters use their actual year boundaries."""
    assert fiscal_window(date(2024, 9, 30), "0630") == (
        date(2024, 7, 1),
        date(2024, 7, 1),
        2025,
        1,
    )
    assert fiscal_window(date(2024, 8, 31), "0531") == (
        date(2024, 6, 1),
        date(2024, 6, 1),
        2025,
        1,
    )
    assert fiscal_window(date(2024, 8, 30), "0531") is None


@pytest.mark.parametrize("fault", ["duplicate", "cross_group_duplicate", "principal", "tranches"])
def test_bond_sample_rejects_double_counting_and_inconsistent_amounts(fault: str) -> None:
    """The verified registry cannot render duplicated deals or inconsistent principal."""
    registry: dict = json.loads(Path(__file__).with_name("events.json").read_text())
    bond: dict = registry["bond_events"][0]
    sample: dict = {
        "schema_version": 1,
        "cutoff_date": "2026-10-20",
        "entities": COHORT.copy(),
        "fiscal_periods": [],
        "bond_events": [bond],
        "other_financings": [],
        "spgi_periods": [],
        "coverage": [],
        "sources": registry["sources"],
    }
    validate_snapshot(sample)
    if fault == "duplicate":
        sample["bond_events"].append(bond.copy())
    elif fault == "cross_group_duplicate":
        other: dict = registry["other_financings"][0].copy()
        other["id"] = bond["id"]
        other["entity_id"] = bond["entity_id"]
        sample["other_financings"].append(other)
    elif fault == "principal":
        bond["face_amount"] = None
    else:
        bond["maturities"][0]["face_amount"] = "1"
    with pytest.raises(ValueError):
        validate_snapshot(sample)
