import os
from decimal import Decimal as D
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from helpers import DAYS, cash, trade
from sqlalchemy import create_engine, text

from investor_platform import market
from investor_platform.app import app
from investor_platform.db import DEFAULT_URL
from investor_platform.market import History


@pytest.fixture
def database():
    # Each test gets a fresh schema. Never truncate the user's portfolio.
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_URL)
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        config = Config("alembic.ini")
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def db_client(database):
    app.state.engine = database
    try:
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def expire_prices(database):
    """Advance cached inputs past expiry before simulating a changed provider response."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from investor_platform.models import MarketCache

    def expire():
        with database.begin() as connection:
            connection.execute(
                update(MarketCache).values(fetched_at=datetime.now(UTC) - timedelta(days=2))
            )

    return expire


@pytest.fixture
def portfolio(db_client, monkeypatch):
    aid = db_client.post(
        "/api/accounts", json={"name": "Performance fixture", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, aid, "opening_cash", "1000", day="2026-01-02").status_code == 201
    assert (
        trade(db_client, aid, quantity="10", price="100", ticker="AAA", exchange="NYSE").status_code
        == 201
    )
    data = {
        "AAA": History(
            dict(zip(DAYS, map(D, ["100", "110", "121"]))),
            dict(zip(DAYS, map(D, ["100", "110", "121"]))),
        ),
        "SPY": History(
            dict(zip(DAYS, map(D, ["100", "100", "101"]))),
            dict(zip(DAYS, map(D, ["100", "101", "102"]))),
        ),
        "QQQ": History(
            dict(zip(DAYS, map(D, ["100", "102", "104"]))),
            dict(zip(DAYS, map(D, ["100", "102", "104"]))),
        ),
    }
    data["AAA"].exchange = "NYQ"
    data["SPY"].exchange = "PCX"
    data["QQQ"].exchange = "NGM"
    monkeypatch.setattr(market, "history", lambda symbol, start, end: data[symbol])
    return aid, data
