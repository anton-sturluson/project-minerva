"""Economics parser and real PostgreSQL admission checks with synthetic facts."""

import hashlib
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.economics.collection import Payload, admit, next_regular, refresh
from investor_platform.economics.parsers import Fact, parse_bls, parse_usda
from investor_platform.economics.registry import SERIES
from investor_platform.models import EconomicObservation, EconomicRefreshState


def bls_bytes(value: str = "2.125", period: str = "M01") -> bytes:
    """Build a synthetic successful payload for the three active macroeconomic IDs."""
    return json.dumps(
        {
            "status": "REQUEST_SUCCEEDED",
            "message": [],
            "Results": {
                "series": [
                    {
                        "seriesID": series.source_key,
                        "data": [
                            {
                                "year": "2026",
                                "period": period,
                                "value": value,
                                "footnotes": [{"code": "X", "text": "Synthetic missing"}]
                                if value == "-"
                                else [],
                            }
                        ],
                    }
                    for series in SERIES
                    if series.source_id == "bls-macro" and not series.transform
                ]
            },
        }
    ).encode()


def usda_bytes(*, duplicate: bool = False, missing: bool = False) -> bytes:
    """Build a synthetic workbook using the publisher column schema."""
    workbook: openpyxl.Workbook = openpyxl.Workbook()
    sheet: Worksheet = workbook.active
    sheet.title = "Moderate-Cost 07-Pres"
    sheet.append(
        [
            "geographic_area",
            "fam_indv",
            "group",
            "age",
            "year",
            "month",
            "food_plan",
            "frequency",
            "cost",
        ]
    )
    group: str
    age: str
    value: float
    for group, age, value in [
        ("Male", "19-50 years", 80.1),
        ("Female", "19-50 years", 70.2),
        ("Child", "6-8 years", 60.3),
        ("Child", "9-11 years", 50.4),
    ]:
        if missing and age == "9-11 years":
            continue
        row: list[str | int | float] = [
            "Mainland U.S.",
            "Individual",
            group,
            age,
            2026,
            "January",
            "Moderate Cost",
            "Weekly",
            value,
        ]
        sheet.append(row)
        if duplicate:
            sheet.append(row)
    stream: io.BytesIO = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_bls_exact_decimals_and_missing() -> None:
    """Preserve exact prices and explicitly marked missing observations."""
    facts: list[Fact] = parse_bls(bls_bytes())
    assert len(facts) == 3
    assert {fact.value for fact in facts} == {Decimal("2.125")}
    missing: list[Fact] = parse_bls(bls_bytes("-"))
    assert all(fact.value is None and fact.footnotes[0]["code"] == "X" for fact in missing)
    with pytest.raises(ValueError):
        parse_bls(bls_bytes(period="Q01"))
    with pytest.raises(ValueError):
        parse_bls(b'{"status":"REQUEST_NOT_PROCESSED"}')
    empty: dict = json.loads(bls_bytes())
    empty["Results"]["series"][0]["data"] = []
    with pytest.raises(ValueError):
        parse_bls(json.dumps(empty).encode())


def test_usda_four_components_and_duplicate_rejection() -> None:
    """Require each family component once and retain the calculation inputs."""
    facts: list[Fact] = parse_usda(usda_bytes())
    assert len(facts) == 1 and facts[0].value == Decimal("261.0")
    assert len(facts[0].derived_from) == 4
    assert {row["component"] for row in facts[0].derived_from} == {
        "Male:19-50 years",
        "Female:19-50 years",
        "Child:6-8 years",
        "Child:9-11 years",
    }
    with pytest.raises(ValueError):
        parse_usda(usda_bytes(duplicate=True))
    with pytest.raises(ValueError):
        parse_usda(usda_bytes(missing=True))


def test_admission_is_idempotent_and_retains_revisions(database: Engine, tmp_path: Path) -> None:
    """Retain corrections, including a later return to a previously reported value."""
    now: datetime = datetime(2026, 1, 15, tzinfo=UTC)
    original: Payload = Payload(
        "https://example.com/prices", b"synthetic original", parse_bls(bls_bytes())
    )
    corrected: Payload = Payload(
        "https://example.com/prices", b"synthetic revision", parse_bls(bls_bytes("3.250"))
    )
    with Session(database) as session, session.begin():
        assert admit(session, LOCAL_WORKSPACE, [original], now, tmp_path) == 3
    with Session(database) as session, session.begin():
        assert admit(session, LOCAL_WORKSPACE, [original], now, tmp_path) == 0
        changed_bytes: Payload = Payload(
            original.url, b"different bytes, same facts", original.facts
        )
        assert admit(session, LOCAL_WORKSPACE, [changed_bytes], now, tmp_path) == 0
        assert admit(session, LOCAL_WORKSPACE, [corrected], now, tmp_path) == 3
    with Session(database) as session, session.begin():
        # A correction back to a previously seen value must append a new version.
        assert admit(session, LOCAL_WORKSPACE, [original], now, tmp_path) == 3
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(EconomicObservation)) == 9
    digest: str = hashlib.sha256(original.body).hexdigest()
    assert (tmp_path / digest).read_bytes() == original.body


def test_admission_rollback_keeps_last_good(database: Engine, tmp_path: Path) -> None:
    """Roll back facts together if source admission fails."""
    payload: Payload = Payload("https://example.com/prices", b"synthetic", parse_bls(bls_bytes()))
    with pytest.raises(ValueError), Session(database) as session, session.begin():
        admit(session, LOCAL_WORKSPACE, [payload], datetime.now(UTC), tmp_path)
        raise ValueError("Reject entire source transaction")
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(EconomicObservation)) == 0


def test_failure_state_recovery_and_initial_only_import(database: Engine, tmp_path: Path) -> None:
    """Retain failure state, recover, and reject stale snapshot replacement."""
    (tmp_path / "bls-macro.json").write_bytes(b'{"status":"BAD"}')
    now: datetime = datetime(2026, 1, 15, 14, tzinfo=UTC)
    assert (
        refresh(database, "bls-macro", now=now, import_dir=tmp_path, raw_dir=tmp_path / "raw")
        == "failed"
    )
    with Session(database) as session:
        state: EconomicRefreshState | None = session.get(
            EconomicRefreshState, (LOCAL_WORKSPACE, "bls-macro")
        )
        assert state.failures == 1 and state.last_success is None
        assert state.next_due > now
        assert session.scalar(select(func.count()).select_from(EconomicObservation)) == 0
    (tmp_path / "bls-macro.json").write_bytes(bls_bytes("-"))
    assert (
        refresh(
            database,
            "bls-macro",
            now=now,
            force=True,
            import_dir=tmp_path,
            raw_dir=tmp_path / "raw",
        )
        == "imported"
    )
    with pytest.raises(ValueError):
        refresh(database, "bls-macro", now=now, force=True, import_dir=tmp_path)
    with Session(database) as session:
        state = session.get(EconomicRefreshState, (LOCAL_WORKSPACE, "bls-macro"))
        assert state.failures == 0 and state.last_success == now
        assert session.scalar(select(func.count()).select_from(EconomicObservation)) == 3


def test_other_worker_lock_prevents_collection(database: Engine, tmp_path: Path) -> None:
    """Keep a second process from starting collection for a locked source."""
    lock: int = int.from_bytes(
        hashlib.sha256(f"economics:{LOCAL_WORKSPACE}:bls-macro".encode()).digest()[:8], signed=True
    )
    with database.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock})
        connection.commit()
        try:
            assert refresh(database, "bls-macro", import_dir=tmp_path) == "running"
            with Session(database) as session:
                assert session.get(EconomicRefreshState, (LOCAL_WORKSPACE, "bls-macro")) is None
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock})
            connection.commit()


def test_research_api_latest_missing_and_date_bounds(
    db_client: TestClient, database: Engine, tmp_path: Path
) -> None:
    """Expose missing data and date ranges without triggering collection."""
    payload: Payload = Payload(
        "https://example.com/prices",
        b"synthetic",
        [
            Fact("unemployment", date(2026, 1, 1), Decimal("2.50"), "synthetic"),
            Fact("unemployment", date(2026, 2, 1), None, "synthetic", [{"text": "Unavailable"}]),
        ],
    )
    with Session(database) as session, session.begin():
        admit(session, LOCAL_WORKSPACE, [payload], datetime.now(UTC), tmp_path)
    catalog: dict = db_client.get("/api/research/economics").json()
    unemployment: dict = next(
        series for series in catalog["series"] if series["key"] == "unemployment"
    )
    assert unemployment["latest"]["missing"] is True and unemployment["observation_count"] == 2
    data: dict = db_client.get(
        "/api/research/economics/series/unemployment?start=2026-02-01"
    ).json()
    assert len(data["observations"]) == 1 and data["observations"][0]["value"] is None
    assert data["observations"][0]["footnotes"] == [{"text": "Unavailable"}]
    assert db_client.get("/api/research/economics/series/unknown").status_code == 404
    assert (
        db_client.get(
            "/api/research/economics/series/unemployment?start=2026-03-01&end=2026-01-01"
        ).status_code
        == 422
    )
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(EconomicRefreshState)) == 0


def test_schedule_uses_new_york_dst_and_eia_release_buffer() -> None:
    """Keep polling clocks in New York through seasonal time changes."""
    assert next_regular("bls-macro", datetime(2026, 1, 12, 12, tzinfo=UTC)) == datetime(
        2026, 1, 12, 14, tzinfo=UTC
    )
    assert next_regular("bls-macro", datetime(2026, 7, 13, 12, tzinfo=UTC)) == datetime(
        2026, 7, 13, 13, tzinfo=UTC
    )
    assert next_regular("eia", datetime(2026, 1, 12, 12, tzinfo=UTC)) == datetime(
        2026, 1, 13, 15, 30, tzinfo=UTC
    )


def test_retired_food_metrics_are_unavailable_without_deleting_saved_history(
    db_client: TestClient, database: Engine, tmp_path: Path
) -> None:
    """Retire the food-price catalog and collector while preserving earlier source evidence."""
    now: datetime = datetime(2026, 10, 18, tzinfo=UTC)
    payload: Payload = Payload(
        "https://example.com/old-food-data",
        b"synthetic retired history",
        [Fact("eggs", date(2026, 1, 1), Decimal("2.50"), "retired food series")],
    )
    with Session(database) as session, session.begin():
        admit(session, LOCAL_WORKSPACE, [payload], now, tmp_path)
        session.add(
            EconomicRefreshState(
                workspace_id=LOCAL_WORKSPACE,
                provider="bls",
                last_attempt=now,
                last_success=now,
                next_due=now,
                status="complete",
                failures=0,
            )
        )
    catalog: dict = db_client.get("/api/research/economics").json()
    keys: set[str] = {series["key"] for series in catalog["series"]}
    retired: tuple[str, ...] = ("chicken-breast", "ground-beef", "eggs", "milk", "bread")
    assert not keys.intersection(retired)
    assert {"family-groceries", "gasoline", "diesel", "headline-inflation"} <= keys
    assert "bls" not in {source["id"] for source in catalog["sources"]}
    key: str
    for key in retired:
        assert db_client.get(f"/api/research/economics/series/{key}").status_code == 404
    with pytest.raises(ValueError, match="not enabled"):
        refresh(database, "bls", import_dir=tmp_path)
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(EconomicObservation)) == 1
        assert session.get(EconomicRefreshState, (LOCAL_WORKSPACE, "bls")) is not None
