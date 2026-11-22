"""Verify tracking and archival across research views and SEC imports."""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import ResearchFiling, ResearchHolding, ResearchManager
from investor_platform.research import sync


def manager(session: Session, slug: str, cik: str, profile: dict) -> ResearchManager:
    """Create a synthetic manager."""
    record: ResearchManager = ResearchManager(
        workspace_id=LOCAL_WORKSPACE, slug=slug, cik=cik, profile={"name": slug, **profile}
    )
    session.add(record)
    session.flush()
    return record


def quarter(
    session: Session, record: ResearchManager, period: str, quantity: str, cusip: str
) -> None:
    """Store one complete synthetic filing."""
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
            cusip=cusip,
            issuer="Example",
            security_class="COM",
            put_call="",
            share_type="SH",
            quantity=Decimal(quantity),
            value_usd=Decimal("1000"),
        )
    )
    session.flush()


def test_unknown_and_small_aum_managers_are_tracked(
    database: Engine, db_client: TestClient
) -> None:
    """AUM does not prevent directory or activity inclusion, including the newest quarter."""
    with Session(database) as session:
        unknown: ResearchManager = manager(session, "unknown", "1001", {})
        small: ResearchManager = manager(session, "small", "1002", {"aum_usd": "1"})
        for record in (unknown, small):
            quarter(session, record, "2026-03-31", "10", "123456789")
            quarter(session, record, "2026-06-30", "11", "123456789")
        quarter(session, unknown, "2026-09-30", "12", "123456789")
        session.commit()
    registry: list[dict] = db_client.get("/api/research/managers").json()["managers"]
    assert {row["slug"] for row in registry} == {"unknown", "small"}
    assert all("eligibility" not in row for row in registry)
    activity: dict = db_client.get("/api/research/activity").json()
    assert activity["quarter"] == "2026-09-30"
    assert activity["available_quarters"] == ["2026-09-30", "2026-06-30"]
    assert activity["increased"][0]["contributors"][0]["slug"] == "unknown"
    earlier: dict = db_client.get("/api/research/activity?quarter=2026-06-30").json()
    assert {row["slug"] for row in earlier["increased"][0]["contributors"]} == {"unknown", "small"}


def test_archived_history_survives_reseeding_but_is_not_tracked(
    database: Engine, db_client: TestClient, tmp_path: Path
) -> None:
    """Archived records remain directly readable but do not contribute to tracked views."""
    catalog: Path = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {"slug": "active", "cik": "1001", "name": "Active"},
                {"slug": "archived", "cik": "1002", "name": "Archived", "archived": True},
            ]
        )
    )
    with Session(database) as session:
        sync.seed_catalog(session, catalog)
        active: ResearchManager = session.scalar(
            select(ResearchManager).where(ResearchManager.slug == "active")
        )
        archived: ResearchManager = session.scalar(
            select(ResearchManager).where(ResearchManager.slug == "archived")
        )
        for period, quantity in (("2026-03-31", "10"), ("2026-06-30", "11")):
            quarter(session, active, period, quantity, "111111111")
            quarter(session, archived, period, quantity, "222222222")
        quarter(session, archived, "2026-09-30", "12", "222222222")
        sync.seed_catalog(session, catalog)
        sync.seed_catalog(session, catalog)
        session.commit()
    assert {row["slug"] for row in db_client.get("/api/research/managers").json()["managers"]} == {
        "active"
    }
    activity: dict = db_client.get("/api/research/activity").json()
    assert activity["quarter"] == "2026-06-30"
    assert activity["available_quarters"] == ["2026-06-30"]
    assert {row["slug"] for row in activity["increased"][0]["contributors"]} == {"active"}
    assert (
        db_client.get(
            "/api/research/activity/market-context?quarter=2026-06-30&cusips=222222222"
        ).status_code
        == 404
    )
    detail: dict = db_client.get("/api/research/managers/archived").json()
    assert len(detail["filings"]) == 3
    changes: dict = db_client.get(
        "/api/research/managers/archived/changes?quarter=2026-06-30"
    ).json()
    assert changes["status"] == "available"
    assert Decimal(changes["changes"][0]["quantity_change"]) == 1


def test_bounded_cli_imports_unknown_aum_and_excludes_archived(
    database: Engine,
    db_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Real parsing and storage import unknown-AUM history but skip archived managers."""
    with Session(database) as session:
        manager(session, "unknown", "1001", {})
        manager(session, "archived", "1002", {"archived": True})
        session.commit()
    submissions: dict = {
        "filings": {
            "recent": {
                "form": ["13F-HR", "13F-HR", "13F-HR"],
                "reportDate": ["2026-03-31", "2026-06-30", "2026-09-30"],
                "filingDate": ["2026-05-01", "2026-08-01", "2026-11-01"],
                "accessionNumber": ["1001-26-000001", "1001-26-000002", "1001-26-000003"],
                "primaryDocument": ["primary.xml"] * 3,
            },
            "files": [],
        }
    }

    def read(_client: sync.SECClient, url: str) -> bytes:
        """Return synthetic SEC documents at the network boundary."""
        if "submissions/" in url:
            assert "0000001001" in url
            return json.dumps(submissions).encode()
        if url.endswith("index.json"):
            return b'{"directory":{"item":[{"name":"primary.xml"},{"name":"table.xml"}]}}'
        if url.endswith("primary.xml"):
            return b"<submission><tableEntryTotal>1</tableEntryTotal></submission>"
        assert url.endswith("table.xml")
        quantity: int = 10 if "100126000001" in url else 15
        return (
            f"<informationTable><infoTable><nameOfIssuer>Example</nameOfIssuer>"
            f"<titleOfClass>COM</titleOfClass><cusip>123456789</cusip><value>100</value>"
            f"<shrsOrPrnAmt><sshPrnamt>{quantity}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
            f"</shrsOrPrnAmt></infoTable></informationTable>"
        ).encode()

    monkeypatch.setattr(sync.SECClient, "read", read)
    monkeypatch.setattr(sync, "make_engine", lambda: database)
    monkeypatch.setenv("EDGAR_IDENTITY", "Example research research@example.com")
    monkeypatch.setattr(
        sys,
        "argv",
        ["sync", "--manager", "unknown", "--quarters", "2", "--through-quarter", "2026-Q2"],
    )
    sync.main()
    outcome: dict = json.loads(capsys.readouterr().out)
    assert outcome["imported_filings"] == 2 and outcome["complete_filings"] == 2
    detail: dict = db_client.get("/api/research/managers/unknown").json()
    assert detail.get("aum_usd") is None
    changes: dict = db_client.get(
        "/api/research/managers/unknown/changes?quarter=2026-06-30"
    ).json()
    assert changes["status"] == "available"
    assert Decimal(changes["changes"][0]["quantity_change"]) == 5
    monkeypatch.setattr(
        sys,
        "argv",
        ["sync", "--manager", "archived", "--quarters", "2", "--through-quarter", "2026-Q2"],
    )
    with pytest.raises(SystemExit) as error:
        sync.main()
    assert error.value.code == 2
    monkeypatch.setattr(
        sys, "argv", ["sync", "--all-investors", "--quarters", "2", "--through-quarter", "2026-Q2"]
    )
    sync.main()
    assert json.loads(capsys.readouterr().out)["manager"] == "unknown"
    with Session(database) as session:
        archived: ResearchManager = session.scalar(
            select(ResearchManager).where(ResearchManager.slug == "archived")
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResearchFiling)
                .where(ResearchFiling.manager_id == archived.id)
            )
            == 0
        )
        unknown: ResearchManager = session.scalar(
            select(ResearchManager).where(ResearchManager.slug == "unknown")
        )
        assert unknown.profile.get("aum_usd") is None
