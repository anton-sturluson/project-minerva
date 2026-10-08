"""Verify common-quarter cohorts against persisted synthetic SEC holdings."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import (
    Owner,
    ResearchFiling,
    ResearchHolding,
    ResearchManager,
    Workspace,
)
from investor_platform.research import Position


def manager(
    session: Session, slug: str, cik: str, workspace: UUID = LOCAL_WORKSPACE
) -> ResearchManager:
    """Create a synthetic owned registry record."""
    result: ResearchManager = ResearchManager(
        workspace_id=workspace,
        slug=slug,
        cik=cik,
        profile={
            "name": f"Example {slug.title()}",
            "aum_usd": "100000000",
            "aum_as_of": "2026-01-01",
            "aum_source_url": "https://example.com/aum",
            "aum_measurement": "firm_aum",
        },
    )
    session.add(result)
    session.flush()
    return result


def position(
    cusip: str, quantity: str, value: str, *, option: str = "", share_type: str = "SH"
) -> Position:
    """Create exact disclosed values with independent option and principal identities."""
    return Position(
        cusip=cusip,
        issuer=f"Example {cusip}",
        security_class="COM",
        quantity=Decimal(quantity),
        value_usd=Decimal(value),
        put_call=option,
        share_type=share_type,
    )


def quarter(
    session: Session,
    owner: ResearchManager,
    period: str,
    positions: list[Position],
    *,
    blocked: bool = False,
) -> None:
    """Persist a complete or explicitly incomplete quarterly snapshot."""
    filing: ResearchFiling = ResearchFiling(
        manager_id=owner.id,
        accession=f"{owner.slug}-{period}",
        report_period=date.fromisoformat(period),
        filed_date=date.fromisoformat(period),
        form="13F-HR",
        source_url=f"https://www.sec.gov/example/{owner.slug}/{period}",
        amendment_type=None,
        status="blocked" if blocked else "complete",
        reason="Synthetic incomplete disclosure" if blocked else None,
        evidence={},
    )
    session.add(filing)
    session.flush()
    value: Position
    for value in positions:
        session.add(ResearchHolding(filing_id=filing.id, **value))
    session.flush()


def test_common_quarter_counts_signed_average_and_contributor_evidence(
    database: Engine,
    db_client: TestClient,
) -> None:
    """A security can appear in both cohorts while unchanged and non-share identities stay out."""
    with Session(database) as session:
        alpha: ResearchManager = manager(session, "alpha", "1001")
        beta: ResearchManager = manager(session, "beta", "1002")
        gamma: ResearchManager = manager(session, "gamma", "1003")
        quarter(
            session,
            alpha,
            "2026-03-31",
            [
                position("111111111", "10", "100"),
                position("999999999", "10", "700"),
                position("111111111", "10", "100", option="PUT"),
                position("111111111", "10", "100", share_type="PRN"),
            ],
        )
        quarter(
            session,
            alpha,
            "2026-06-30",
            [
                position("111111111", "20", "200"),
                position("222222222", "10", "200"),
                position("999999999", "10", "400"),
                position("111111111", "20", "100", option="PUT"),
                position("111111111", "20", "100", share_type="PRN"),
            ],
        )
        quarter(
            session,
            beta,
            "2026-03-31",
            [
                position("111111111", "10", "200"),
                position("999999999", "10", "800"),
            ],
        )
        quarter(
            session,
            beta,
            "2026-06-30",
            [
                position("111111111", "15", "300"),
                position("333333333", "10", "500"),
                position("999999999", "10", "200"),
            ],
        )
        quarter(
            session,
            gamma,
            "2026-03-31",
            [
                position("111111111", "10", "400"),
                position("999999999", "10", "600"),
            ],
        )
        quarter(
            session,
            gamma,
            "2026-06-30",
            [
                position("111111111", "5", "100"),
                position("999999999", "10", "900"),
            ],
        )
        session.commit()
    data: dict = db_client.get("/api/research/activity?quarter=2026-06-30").json()
    assert data["status"] == "available"
    assert data["included_managers"] == data["total_managers"] == 3
    assert data["excluded_managers"] == []
    assert data["previous_quarter"] == "2026-03-31"
    assert [item["cusip"] for item in data["increased"]] == ["111111111", "333333333", "222222222"]
    first: dict = data["increased"][0]
    assert first["manager_count"] == 2
    assert Decimal(first["average_weight_change_pp"]) == 10
    assert [item["slug"] for item in first["contributors"]] == ["alpha", "beta"]
    contributor: dict = first["contributors"][0]
    assert Decimal(contributor["previous_weight"]) == Decimal("0.1")
    assert Decimal(contributor["current_weight"]) == Decimal("0.2")
    assert len(contributor["source_urls"]) == 2
    assert all(
        url.startswith("https://www.sec.gov/example/alpha/") for url in contributor["source_urls"]
    )
    assert data["increased"][1]["contributors"][0]["kind"] == "new"
    assert len(data["decreased"]) == 1
    assert data["decreased"][0]["cusip"] == "111111111"
    assert Decimal(data["decreased"][0]["average_weight_change_pp"]) == -30
    assert data["decreased"][0]["contributors"][0]["slug"] == "gamma"


def test_direction_uses_quantities_and_keeps_counterdirection_weight_changes(
    database: Engine,
    db_client: TestClient,
) -> None:
    """Increases can lose portfolio weight and reductions can gain it due to reported prices."""
    with Session(database) as session:
        alpha: ResearchManager = manager(session, "alpha", "1001")
        quarter(
            session,
            alpha,
            "2026-03-31",
            [
                position("111111111", "10", "400"),
                position("222222222", "10", "100"),
                position("333333333", "10", "100"),
                position("444444444", "10", "100"),
                position("999999999", "10", "300"),
            ],
        )
        quarter(
            session,
            alpha,
            "2026-06-30",
            [
                position("111111111", "11", "100"),
                position("222222222", "9", "400"),
                position("333333333", "11", "150"),
                position("444444444", "9", "50"),
                position("999999999", "10", "300"),
            ],
        )
        session.commit()
    data: dict = db_client.get("/api/research/activity").json()
    assert [item["cusip"] for item in data["increased"]] == ["333333333", "111111111"]
    assert [Decimal(item["average_weight_change_pp"]) for item in data["increased"]] == [5, -30]
    assert [item["cusip"] for item in data["decreased"]] == ["444444444", "222222222"]
    assert [Decimal(item["average_weight_change_pp"]) for item in data["decreased"]] == [-5, 30]


def test_default_falls_back_to_newest_usable_pair_without_mixing_quarters(
    database: Engine,
    db_client: TestClient,
) -> None:
    """Stale, missing, blocked and zero-value managers cannot enter a newer common quarter."""
    with Session(database) as session:
        stale: ResearchManager = manager(session, "stale", "1001")
        blocked: ResearchManager = manager(session, "blocked", "1002")
        zero: ResearchManager = manager(session, "zero", "1003")
        missing: ResearchManager = manager(session, "missing", "1004")
        quarter(session, stale, "2025-12-31", [position("111111111", "10", "100")])
        quarter(session, stale, "2026-03-31", [position("111111111", "11", "100")])
        quarter(session, blocked, "2026-03-31", [position("111111111", "10", "100")])
        quarter(session, blocked, "2026-06-30", [position("111111111", "11", "100")], blocked=True)
        quarter(session, zero, "2026-03-31", [position("111111111", "10", "0")])
        quarter(session, zero, "2026-06-30", [position("111111111", "11", "100")])
        quarter(session, missing, "2026-06-30", [position("111111111", "11", "100")])
        session.commit()
    newest: dict = db_client.get("/api/research/activity?quarter=2026-06-30").json()
    assert newest["status"] == "unavailable"
    assert newest["included_managers"] == 0
    assert newest["increased"] == newest["decreased"] == []
    reasons: dict[str, str] = {item["slug"]: item["reason"] for item in newest["excluded_managers"]}
    assert "Missing" in reasons["stale"] and "Missing" in reasons["missing"]
    assert "incomplete" in reasons["blocked"]
    assert "zero" in reasons["zero"]
    default: dict = db_client.get("/api/research/activity").json()
    assert default["quarter"] == "2026-03-31"
    assert default["previous_quarter"] == "2025-12-31"
    assert default["available_quarters"] == ["2026-06-30", "2026-03-31"]
    assert default["included_managers"] == 1
    assert default["increased"][0]["contributors"][0]["slug"] == "stale"
    assert db_client.get("/api/research/activity?quarter=2026-06-01").status_code == 422


def test_workspace_isolation_and_untrusted_origin(
    database: Engine,
    db_client: TestClient,
) -> None:
    """Foreign manager names and quarter choices stay outside the current workspace."""
    with Session(database) as session:
        owner_id: UUID = uuid4()
        workspace_id: UUID = uuid4()
        session.add(Owner(id=owner_id))
        session.flush()
        session.add(Workspace(id=workspace_id, owner_id=owner_id))
        session.flush()
        own: ResearchManager = manager(session, "owned", "1001")
        foreign: ResearchManager = manager(session, "foreign", "1002", workspace_id)
        quarter(session, own, "2026-03-31", [position("111111111", "1", "10")])
        quarter(session, own, "2026-06-30", [position("111111111", "2", "10")])
        quarter(session, foreign, "2026-06-30", [position("111111111", "1", "10")])
        quarter(session, foreign, "2026-09-30", [position("111111111", "2", "10")])
        session.commit()
    data: dict = db_client.get("/api/research/activity").json()
    assert data["total_managers"] == 1
    assert data["available_quarters"] == ["2026-06-30"]
    assert "foreign" not in str(data)
    assert (
        db_client.get(
            "/api/research/activity", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        db_client.get("/api/research/activity", headers={"Host": "evil.example"}).status_code == 400
    )


def test_empty_registry_and_no_adjacent_pairs_are_explicit(
    database: Engine,
    db_client: TestClient,
) -> None:
    """Empty data returns a usable unavailable response without inventing a quarter."""
    empty: dict = db_client.get("/api/research/activity").json()
    assert empty["quarter"] is None and empty["previous_quarter"] is None
    assert empty["available_quarters"] == [] and empty["status"] == "unavailable"
    assert empty["total_managers"] == empty["included_managers"] == 0
    with Session(database) as session:
        missing: ResearchManager = manager(session, "missing", "1001")
        quarter(session, missing, "2026-06-30", [])
        session.commit()
    unavailable: dict = db_client.get("/api/research/activity").json()
    assert unavailable["quarter"] is None
    assert unavailable["excluded_managers"][0]["slug"] == "missing"


def test_ties_use_cusip_and_zero_quantity_presence_is_not_activity(
    database: Engine,
    db_client: TestClient,
) -> None:
    """Equal cohort ranks stay deterministic and zero-quantity arrivals or exits do not count."""
    with Session(database) as session:
        alpha: ResearchManager = manager(session, "alpha", "1001")
        quarter(
            session,
            alpha,
            "2026-03-31",
            [
                position("444444444", "10", "100"),
                position("333333333", "10", "100"),
                position("999999999", "10", "800"),
                position("555555555", "0", "0"),
            ],
        )
        quarter(
            session,
            alpha,
            "2026-06-30",
            [
                position("222222222", "10", "100"),
                position("111111111", "10", "100"),
                position("999999999", "10", "800"),
                position("666666666", "0", "0"),
            ],
        )
        session.commit()
    data: dict = db_client.get("/api/research/activity").json()
    assert [item["cusip"] for item in data["increased"]] == ["111111111", "222222222"]
    assert [item["cusip"] for item in data["decreased"]] == ["333333333", "444444444"]
    assert all(Decimal(item["average_weight_change_pp"]) == 10 for item in data["increased"])
    assert all(Decimal(item["average_weight_change_pp"]) == -10 for item in data["decreased"])
