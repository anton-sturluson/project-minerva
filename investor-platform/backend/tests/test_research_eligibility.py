"""Verify sourced AUM eligibility in the registry, activity and explicit SEC imports."""

import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import ResearchFiling, ResearchHolding, ResearchManager
from investor_platform.research_eligibility import manager_eligibility

AUM: dict[str, str] = {
    "aum_usd": "50000000",
    "aum_as_of": "2026-01-01",
    "aum_source_url": "https://example.com/official-aum",
    "aum_measurement": "firm_aum",
}
TODAY: date = date(2026, 10, 8)


@pytest.mark.parametrize("measurement", ["firm_aum", "regulatory_aum", "verified_lower_bound"])
def test_minimum_is_inclusive(measurement: str) -> None:
    """Supported official measurements share the same exact USD minimum."""
    profile: dict = {**AUM, "aum_measurement": measurement}
    assert manager_eligibility(profile, TODAY) == {
        "status": "eligible",
        "minimum_aum_usd": "50000000",
        "reason": None,
    }
    below: dict = manager_eligibility({**profile, "aum_usd": "49999999.99"}, TODAY)
    if measurement == "verified_lower_bound":
        assert below["status"] == "unverified" and "lower bound" in below["reason"]
    else:
        assert below["status"] == "below_minimum" and "below" in below["reason"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"aum_usd": None},
        {"aum_usd": "NaN"},
        {"aum_usd": "Infinity"},
        {"aum_usd": "-1"},
        {"aum_usd": 50000000},
        {"aum_as_of": None},
        {"aum_as_of": "2026-02-30"},
        {"aum_as_of": "2027-01-01"},
        {"aum_as_of": "20260101"},
        {"aum_source_url": None},
        {"aum_source_url": "http://example.com/aum"},
        {"aum_source_url": "https:///aum"},
        {"aum_source_url": "https://not a host/aum"},
        {"aum_source_url": "https://user:password@example.com/aum"},
        {"aum_source_url": "https://example.com:bad/aum"},
        {"aum_measurement": "13f_portfolio_value"},
        {"aum_measurement": ["firm_aum"]},
    ],
)
def test_missing_or_invalid_evidence_is_unverified(overrides: dict) -> None:
    """Malformed evidence and a 13F portfolio value cannot establish eligible AUM."""
    eligibility: dict = manager_eligibility({**AUM, **overrides}, TODAY)
    assert eligibility["status"] == "unverified" and eligibility["reason"]
    assert (
        manager_eligibility({"portfolio_value_usd": "1000000000"}, TODAY)["status"] == "unverified"
    )


def manager(session: Session, slug: str, cik: str, evidence: dict) -> ResearchManager:
    """Create a synthetic registry record with AUM evidence separate from holdings."""
    record: ResearchManager = ResearchManager(
        workspace_id=LOCAL_WORKSPACE,
        slug=slug,
        cik=cik,
        profile={"name": f"Example {slug.title()}", **evidence},
    )
    session.add(record)
    session.flush()
    return record


def quarter(session: Session, record: ResearchManager, period: str, quantity: str) -> None:
    """Persist a large public portfolio that must never substitute for AUM evidence."""
    filing: ResearchFiling = ResearchFiling(
        manager_id=record.id,
        accession=f"{record.slug}-{period}",
        report_period=date.fromisoformat(period),
        filed_date=date.fromisoformat(period),
        form="13F-HR",
        source_url="https://www.sec.gov/example/filing",
        amendment_type=None,
        status="complete",
        reason=None,
        evidence={},
    )
    session.add(filing)
    session.flush()
    session.add(
        ResearchHolding(
            filing_id=filing.id,
            cusip="123456789",
            issuer="Example",
            security_class="COM",
            put_call="",
            share_type="SH",
            quantity=Decimal(quantity),
            value_usd=Decimal("1000000000"),
        )
    )
    session.flush()


def test_candidates_are_visible_but_excluded_from_activity(
    database: Engine,
    db_client: TestClient,
) -> None:
    """Sourced AUM controls tracking while retained candidate history remains readable."""
    with Session(database) as session:
        eligible: ResearchManager = manager(session, "eligible", "1001", AUM)
        below: ResearchManager = manager(
            session, "below", "1002", {**AUM, "aum_usd": "49999999.99"}
        )
        unknown: ResearchManager = manager(session, "unknown", "1003", {})
        record: ResearchManager
        for record in (eligible, below, unknown):
            quarter(session, record, "2026-03-31", "10")
            quarter(session, record, "2026-06-30", "11")
        quarter(session, unknown, "2026-09-30", "12")
        session.commit()
    registry: list[dict] = db_client.get("/api/research/managers").json()["managers"]
    assert {row["slug"]: row["eligibility"]["status"] for row in registry} == {
        "below": "below_minimum",
        "eligible": "eligible",
        "unknown": "unverified",
    }
    assert all(row["eligibility"]["minimum_aum_usd"] == "50000000" for row in registry)
    candidate: dict = db_client.get("/api/research/managers/unknown").json()
    assert candidate["eligibility"]["status"] == "unverified" and len(candidate["filings"]) == 3
    assert (
        db_client.get("/api/research/managers/unknown/changes?quarter=2026-06-30").json()["status"]
        == "available"
    )
    activity: dict = db_client.get("/api/research/activity").json()
    assert activity["quarter"] == "2026-06-30" and activity["available_quarters"] == ["2026-06-30"]
    assert activity["included_managers"] == 1 and activity["total_managers"] == 3
    assert activity["increased"][0]["manager_count"] == 1
    assert activity["increased"][0]["contributors"][0]["slug"] == "eligible"
    reasons: dict[str, str] = {row["slug"]: row["reason"] for row in activity["excluded_managers"]}
    assert "below" in reasons["below"] and "verified" in reasons["unknown"]
    with Session(database) as session:
        unknown = session.scalar(select(ResearchManager).where(ResearchManager.slug == "unknown"))
        unknown.profile = {**unknown.profile, **AUM}
        session.commit()
    updated: dict = db_client.get("/api/research/activity").json()
    assert updated["quarter"] == "2026-09-30"
    assert updated["increased"][0]["contributors"][0]["slug"] == "unknown"


def test_real_cli_skips_explicit_unverified_manager(database: Engine) -> None:
    """Explicit import selection cannot bypass the minimum or overwrite old filings."""
    with Session(database) as session:
        unknown: ResearchManager = manager(session, "unverified", "1003", {})
        quarter(session, unknown, "2026-06-30", "10")
        session.commit()
    with database.connect() as connection:
        schema: str = connection.scalar(text("SELECT current_schema()"))
    environment: dict[str, str] = {
        **os.environ,
        "DATABASE_URL": database.url.render_as_string(hide_password=False),
        "PGOPTIONS": f"-csearch_path={schema}",
    }
    environment.pop("EDGAR_IDENTITY", None)
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            sys.executable,
            "-m",
            "investor_platform.research_sync",
            "--manager",
            "unverified",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    outcome: dict = json.loads(result.stdout)
    assert outcome["manager"] == "unverified" and outcome["status"] == "skipped"
    assert "verified" in outcome["reason"]
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(ResearchFiling)) == 1
