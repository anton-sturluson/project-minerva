"""Exercise read-only financial reports through the real application and synthetic schemas."""

import hashlib
import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from psycopg import Connection, connect, sql
from psycopg.rows import dict_row
from sqlalchemy import Connection as SQLConnection
from sqlalchemy import Engine, create_engine, text

from investor_platform.app import app
from investor_platform.financial import Record, Row, import_bundle, record, records
from investor_platform.financial_api import PILOT_HOLDINGS, read_profiles, router


@pytest.fixture
def financial_api(
    database: Engine, db_client: TestClient
) -> Iterator[tuple[TestClient, Engine, str]]:
    """Create an isolated financial namespace using the existing database/client fixtures."""
    schema: str = "investor_financial_test_" + uuid4().hex
    previous_schema: str | None = app.state.financial_schema
    app.state.financial_schema = schema
    conn: Connection[Row] = connect(
        database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg", "postgresql"
        ),
        row_factory=dict_row,
    )
    try:
        yield db_client, database, schema
    finally:
        app.state.financial_schema = previous_schema
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def seed_profiles(engine: Engine, schema: str, count: int = 3) -> None:
    """Import wholly synthetic reviewed statement values for the declared pilot identities."""
    bundle: Record = cast(
        Record,
        json.loads(Path("tests/fixtures/financial/synthetic-annual-bundle.json").read_text()),
    )
    conn: Connection[Row]
    with connect(
        engine.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg", "postgresql"
        ),
        row_factory=dict_row,
    ) as conn:
        issuer: str
        ticker: str
        weight: str
        for issuer, ticker, weight in PILOT_HOLDINGS[:count]:
            candidate: Record = deepcopy(bundle)
            candidate["bundle_id"] = str(uuid4())
            record(candidate["issuer"]).update(issuer_key=issuer, name="Synthetic " + ticker)
            records(candidate["sources"])[0]["content_sha256"] = hashlib.sha256(
                b"Synthetic annual statement source"
            ).hexdigest()
            if ticker == "OSCR":
                record(candidate["issuer"])["business_type"] = "insurer"
                metric: str
                for metric in ("gross_profit", "cost_of_revenue"):
                    fact: Record = record(record(candidate["facts"])[metric])
                    fact.pop("value")
                    fact.update(status="not_applicable", reason="Synthetic insurer example")
            import_bundle(conn, schema, candidate, True)


def test_complete_financial_report_is_source_backed_and_read_only(
    financial_api: tuple[TestClient, Engine, str],
) -> None:
    """Read all profiles, weighted coverage and evidence without changing persisted rows."""
    client: TestClient
    engine: Engine
    schema: str
    client, engine, schema = financial_api
    seed_profiles(engine, schema)
    connection: SQLConnection
    with engine.connect() as connection:
        before: int = connection.scalar(text(f'SELECT count(*) FROM "{schema}".observations'))
    response: Response = client.get("/api/financials?year=2025")
    assert response.status_code == 200
    report: Record = response.json()
    assert report["api_status"] == "available" and report["synthetic"] is True
    assert report["holdings_date"] == "2025-12-31"
    assert response.headers["cache-control"] == "no-store"
    gross: Record = record(record(report["weighted_ratios"])["gross_margin"])
    assert gross["coverage"] == "0.75" and gross["value"] == "0.4"
    company: Record = records(report["companies"])[0]
    profile: Record = record(company["profile"])
    assert record(record(profile["facts"])["basic_eps"])["value"] == "0.80"
    assert records(profile["sources"])[0]["url"] == "https://example.org/annual-report/2025"
    assert record(record(profile["calculations"])["net_margin"])["inputs"]
    with engine.connect() as connection:
        after: int = connection.scalar(text(f'SELECT count(*) FROM "{schema}".observations'))
        assert connection.scalar(text("SHOW transaction_read_only")) == "off"
    assert before == after == 42
    assert len(read_profiles(engine, schema, 2025)) == 3


def test_partial_and_missing_year_profiles(financial_api: tuple[TestClient, Engine, str]) -> None:
    """Partial financial coverage cannot appear as a complete cohort or a zero margin."""
    client: TestClient
    engine: Engine
    schema: str
    client, engine, schema = financial_api
    seed_profiles(engine, schema, count=1)
    report: Record = client.get("/api/financials?year=2025").json()
    assert report["api_status"] == "partial"
    metric: Record = record(record(report["weighted_ratios"])["net_margin"])
    assert metric["coverage"] == "0.6" and metric["value"] == "0.09"
    absent: Record = client.get("/api/financials?year=2023").json()
    assert absent["api_status"] == "unavailable"
    assert record(record(absent["weighted_ratios"])["net_margin"])["value"] is None
    assert all(company["profile"] is None for company in records(absent["companies"]))


def test_missing_or_unsupported_namespace_never_creates_data(
    financial_api: tuple[TestClient, Engine, str],
) -> None:
    """Do not initialize a schema, fall back to legacy data or hide unconfigured state."""
    client: TestClient
    engine: Engine
    schema: str
    client, engine, schema = financial_api
    missing: Record = client.get("/api/financials").json()
    assert missing["api_status"] == "unavailable" and missing["availability_reason"]
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}
            )
            == 0
        )
    app.state.financial_schema = "investor_data"
    unsupported: Record = client.get("/api/financials").json()
    assert unsupported["api_status"] == "unavailable"
    app.state.financial_schema = None
    unconfigured: Record = client.get("/api/financials").json()
    assert "not configured" in str(unconfigured["availability_reason"])


def test_financial_access_and_year_boundaries(
    financial_api: tuple[TestClient, Engine, str],
) -> None:
    """Keep authentication/origin checks and offer only supported read-only requests."""
    client: TestClient = financial_api[0]
    assert client.get("/api/financials?year=2022").status_code == 422
    assert client.get("/api/financials?year=2026").status_code == 422
    assert (
        client.get("/api/financials", headers={"Origin": "https://example.org"}).status_code == 403
    )
    assert client.post("/api/financials").status_code == 405
    isolated: FastAPI = FastAPI()
    isolated.include_router(router)
    unauthenticated: TestClient
    with TestClient(isolated) as unauthenticated:
        assert unauthenticated.get("/api/financials").status_code == 403


def test_transport_failure_is_actionable_without_connection_details(
    financial_api: tuple[TestClient, Engine, str],
) -> None:
    """A real unreachable local database returns a recoverable response without its URL."""
    client: TestClient
    engine: Engine
    schema: str
    client, engine, schema = financial_api
    unavailable: Engine = create_engine(
        "postgresql+psycopg://example@127.0.0.1:1/example", connect_args={"connect_timeout": 1}
    )
    app.state.engine = unavailable
    try:
        response: Response = client.get("/api/financials")
        assert response.status_code == 503
        assert "Check the database connection" in response.json()["detail"]
        assert "127.0.0.1" not in response.text and "example@" not in response.text
    finally:
        app.state.engine = engine
        unavailable.dispose()
