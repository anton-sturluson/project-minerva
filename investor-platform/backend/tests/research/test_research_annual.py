"""Verify annual net changes against complete stored calendar-quarter evidence."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from test_research import filing, registry, row


def test_annual_net_changes_use_endpoints_not_quarterly_activity(
    database: Engine, db_client: TestClient, tmp_path: Path
) -> None:
    """Annual additions, reductions, exits and round trips use December boundaries."""
    manager_id: UUID = registry(database, tmp_path)
    opening: str = "".join(row("10", "100", cusip=f"{index:09}") for index in range(1, 6))
    closing: str = (
        row("15", "120", cusip="000000001")
        + row("5", "80", cusip="000000002")
        + row("10", "150", cusip="000000004")
        + row("10", "100", cusip="000000005")
        + row("2", "50", cusip="000000006")
    )
    filing(database, manager_id, "2025-12-31", "opening", opening, count=5)
    middle: str = opening.replace("<sshPrnamt>10</sshPrnamt>", "<sshPrnamt>20</sshPrnamt>")
    middle += row("3", "30", cusip="000000007")
    period: str
    for period in ["2026-03-31", "2026-06-30", "2026-09-30"]:
        filing(database, manager_id, period, period, middle, count=6)
    filing(database, manager_id, "2026-12-31", "closing", closing, count=5)
    response: dict = db_client.get("/api/research/managers/example/annual-changes?year=2026").json()
    assert response["status"] == "available"
    assert response["quarter"] == "2026-12-31"
    assert response["previous_quarter"] == "2025-12-31"
    assert response["year"] == 2026 and response["year_to_date"] is False
    assert len(response["source_urls"]) == 5
    changes: dict[str, dict] = {item["cusip"]: item for item in response["changes"]}
    assert {cusip: item["kind"] for cusip, item in changes.items()} == {
        "000000001": "increased",
        "000000002": "decreased",
        "000000003": "exited",
        "000000004": "unchanged",
        "000000005": "unchanged",
        "000000006": "new",
    }
    assert Decimal(changes["000000001"]["quantity_change"]) == 5
    assert Decimal(changes["000000001"]["value_change_usd"]) == 20
    assert Decimal(changes["000000001"]["previous_weight"]) == Decimal("0.2")
    assert Decimal(changes["000000001"]["current_weight"]) == Decimal("0.24")
    assert Decimal(changes["000000001"]["weight_change"]) == Decimal("0.04")
    assert Decimal(changes["000000005"]["quantity_change"]) == 0
    assert Decimal(changes["000000003"]["current_weight"]) == 0
    quarterly: dict = db_client.get(
        "/api/research/managers/example/changes?quarter=2026-12-31"
    ).json()
    assert quarterly["previous_quarter"] == "2026-09-30"
    assert "year" not in quarterly and "year_to_date" not in quarterly
    quarterly_changes: dict[str, dict] = {item["cusip"]: item for item in quarterly["changes"]}
    assert Decimal(quarterly_changes["000000001"]["quantity_change"]) == -5


def test_latest_year_is_explicit_year_to_date_without_other_year_fallback(
    database: Engine, db_client: TestClient, tmp_path: Path
) -> None:
    """The latest available year ends at its latest loaded quarter; absent years stay absent."""
    manager_id: UUID = registry(database, tmp_path)
    period: str
    for period in ["2025-12-31", "2026-03-31", "2026-06-30"]:
        filing(database, manager_id, period, period, row("5", "50"))
    result: dict = db_client.get("/api/research/managers/example/annual-changes?year=2026").json()
    assert result["status"] == "available"
    assert result["quarter"] == "2026-06-30" and result["year_to_date"] is True
    missing: dict = db_client.get("/api/research/managers/example/annual-changes?year=2024").json()
    assert missing["status"] == "unavailable" and missing["changes"] == []
    assert missing["quarter"] == "2024-12-31"
    assert missing["previous_quarter"] == "2023-12-31"
    assert db_client.get("/api/research/managers/example/annual-changes?year=0").status_code == 422
    assert (
        db_client.get("/api/research/managers/unknown/annual-changes?year=2026").status_code == 404
    )


@pytest.mark.parametrize("missing", ["2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"])
def test_annual_missing_boundary_or_intervening_quarter_is_unavailable(
    database: Engine, db_client: TestClient, tmp_path: Path, missing: str
) -> None:
    """Annual net results never silently bridge absent history."""
    manager_id: UUID = registry(database, tmp_path)
    period: str
    for period in ["2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]:
        if period != missing:
            filing(database, manager_id, period, period, row("5", "50"))
    result: dict = db_client.get("/api/research/managers/example/annual-changes?year=2026").json()
    assert result["status"] == "unavailable" and result["changes"] == []
    assert missing in result["reason"]


def test_past_year_requires_december_and_amendment_recovery_is_shared(
    database: Engine, db_client: TestClient, tmp_path: Path
) -> None:
    """Past years cannot use a partial year; blocked amendments need a valid restatement."""
    manager_id: UUID = registry(database, tmp_path)
    period: str
    for period in ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2026-03-31"]:
        filing(database, manager_id, period, period, row("5", "50"))
    endpoint: str = "/api/research/managers/example/annual-changes?year=2025"
    result: dict = db_client.get(endpoint).json()
    assert result["status"] == "unavailable" and "2025-12-31" in result["reason"]
    assert result["quarter"] == "2025-12-31" and result["year_to_date"] is False
    filing(database, manager_id, "2025-12-31", "original", row("5", "50"))
    assert db_client.get(endpoint).json()["status"] == "available"
    filing(database, manager_id, "2025-06-30", "overlap", row("1", "10"), amendment="NEW HOLDINGS")
    result = db_client.get(endpoint).json()
    assert result["status"] == "unavailable" and "overlaps" in result["reason"]
    filing(
        database, manager_id, "2025-06-30", "restatement", row("5", "50"), amendment="RESTATEMENT"
    )
    assert db_client.get(endpoint).json()["status"] == "available"
    filing(database, manager_id, "2025-09-30", "invalid", row("5", "50"), count=2)
    result = db_client.get(endpoint).json()
    assert result["status"] == "unavailable" and "count" in result["reason"]
