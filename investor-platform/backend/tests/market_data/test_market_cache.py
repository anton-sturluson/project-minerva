from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.market_data import types as market_types
from investor_platform.market_data import yahoo as market_yahoo
from investor_platform.models import MarketCache, Owner, Workspace

START, END = date(2026, 1, 2), date(2026, 1, 5)


def test_cache_single_flight_precision_and_period_slicing(database, monkeypatch):
    calls = []
    price = Decimal("123.12345678901234567890123456789")

    def download(symbol, first, last):
        calls.append((symbol, first, last))
        return market_types.History(
            {START: price, END: price + 1},
            {START: price, END: price},
            {END: Decimal(".5")},
            {END + timedelta(days=1)},
            "NYQ",
        )

    monkeypatch.setattr(market_yahoo, "history", download)

    def read(end):
        return market_yahoo.cached_history(
            "AAA", START, end, engine=database, workspace_id=LOCAL_WORKSPACE
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, [END] * 4))
    assert len(calls) == 1
    assert all(r.close[START] == price for r in results)
    subset = read(START)
    assert subset.close == {START: price}
    assert subset.dividends == {}
    assert subset.splits == {END + timedelta(days=1)}  # Future splits still affect share units.
    assert len(calls) == 1
    subset.close.clear()
    assert read(START).close  # No caller can mutate another request's cached data.


def test_accepted_prices_survive_age_and_failed_refresh_without_inventing_coverage(
    database, monkeypatch
):
    calls = []
    fail = False

    def download(symbol, first, last):
        calls.append((first, last))
        if fail:
            raise ValueError("Invalid provider response")
        return market_types.History({START: Decimal(10), END: Decimal(11)}, {})

    monkeypatch.setattr(market_yahoo, "history", download)

    def read(start=START, end=END, refresh_after=None):
        return market_yahoo.cached_history(
            "AAA",
            start,
            end,
            engine=database,
            workspace_id=LOCAL_WORKSPACE,
            refresh_after=refresh_after,
        )

    read()
    read(START - timedelta(days=1))
    assert calls[-1] == (START - timedelta(days=1), END)
    previous_collection = datetime.now(UTC) - timedelta(days=2)
    with Session(database) as session, session.begin():
        session.execute(update(MarketCache).values(fetched_at=previous_collection))
    fail = True
    retained = read()
    assert retained.close == {START: Decimal(10), END: Decimal(11)}
    assert retained.fetched_at == previous_collection
    assert len(calls) == 2
    with pytest.raises(ValueError):
        read(refresh_after=datetime.now(UTC))
    with pytest.raises(ValueError):
        read(end=END + timedelta(days=1))
    with Session(database) as session:
        row = session.query(MarketCache).one()
        assert row.payload["close"][START.isoformat()] == "10"
        assert datetime.now(UTC) - row.fetched_at > timedelta(days=1)
    fail = False
    refreshed = read(refresh_after=datetime.now(UTC))
    assert refreshed.fetched_at > previous_collection
    assert len(calls) == 5


def test_cache_separates_workspace_and_validation_options(database, monkeypatch):
    owner, workspace = uuid4(), uuid4()
    with Session(database) as session, session.begin():
        session.add(Owner(id=owner))
        session.flush()
        session.add(Workspace(id=workspace, owner_id=owner))
    calls = []

    def download(symbol, first, last, **options):
        calls.append(options)
        if options.get("currency") == "CAD":
            raise ValueError("Market currency is not CAD")
        return market_types.History({START: Decimal(10)}, {})

    monkeypatch.setattr(market_yahoo, "history", download)
    for workspace_id in [LOCAL_WORKSPACE, workspace]:
        market_yahoo.cached_history("AAA", START, END, engine=database, workspace_id=workspace_id)
    with pytest.raises(ValueError, match="currency"):
        market_yahoo.cached_history(
            "AAA", START, END, engine=database, workspace_id=workspace, currency="CAD"
        )
    assert len(calls) == 3


def test_cached_prices_do_not_hide_ledger_edits(db_client, monkeypatch):
    from helpers import cash, trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Cache fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="2", price="100", exchange="NYSE")
    calls = []

    def download(symbol, first, last):
        calls.append(symbol)
        return market_types.History({last: Decimal(120)}, {}, exchange="NYQ")

    monkeypatch.setattr(market_yahoo, "history", download)
    url = f"/api/accounts/{aid}/valuation"
    assert Decimal(db_client.get(url).json()["value"]) == 1040
    cash(db_client, aid, "deposit", "500")
    assert Decimal(db_client.get(url).json()["value"]) == 1540
    assert len(calls) == 1


def test_retained_valuation_shows_actual_quote_and_collection_dates_until_refresh(
    database, db_client, monkeypatch
):
    from helpers import cash, trade

    from investor_platform.performance import valuation

    aid = db_client.post(
        "/api/accounts", json={"name": "Dated quote fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="2", price="100", exchange="NYSE")
    monkeypatch.setattr(valuation, "completed_market_date", lambda: END)
    closes = {START: Decimal(120)}
    offline = False

    def download(symbol, first, last):
        if offline:
            raise OSError("synthetic provider outage")
        return market_types.History(closes, {}, exchange="NYQ", source="Synthetic daily history")

    monkeypatch.setattr(market_yahoo, "history", download)
    url = f"/api/accounts/{aid}/valuation"
    first = db_client.get(url).json()
    assert first["end"] == END.isoformat()
    assert first["holdings"][0]["quote_date"] == START.isoformat()
    prior = datetime.now(UTC) - timedelta(days=2)
    with database.begin() as connection:
        connection.execute(update(MarketCache).values(fetched_at=prior))
    offline = True
    retained = db_client.get(url).json()
    assert retained["value"] == first["value"]
    assert retained["holdings"][0]["quote_date"] == START.isoformat()
    assert datetime.fromisoformat(retained["prices_fetched_at"]) == prior
    assert datetime.fromisoformat(retained["fetched_at"]) > prior
    assert retained["source"] == "Synthetic daily history"
    offline = False
    closes[END] = Decimal(130)
    market_yahoo.cached_history(
        "DEMO",
        START,
        END,
        engine=database,
        workspace_id=LOCAL_WORKSPACE,
        refresh_after=datetime.now(UTC),
    )
    refreshed = db_client.get(url).json()
    assert refreshed["holdings"][0]["quote_date"] == END.isoformat()
    assert Decimal(refreshed["value"]) == 1060
    assert datetime.fromisoformat(refreshed["prices_fetched_at"]) > prior


def test_scheduled_refresh_bypasses_ttl_and_reuses_its_results(database, monkeypatch):
    calls = []

    def download(symbol, first, last):
        calls.append(symbol)
        return market_types.History({START: Decimal(len(calls))}, {})

    monkeypatch.setattr(market_yahoo, "history", download)

    def read(**kwargs):
        return market_yahoo.cached_history(
            "AAA", START, END, engine=database, workspace_id=LOCAL_WORKSPACE, **kwargs
        )

    assert read().close[START] == 1
    cutoff = datetime.now(UTC)
    assert read(refresh_after=cutoff).close[START] == 2
    assert read(refresh_after=cutoff).close[START] == 2
    assert read().close[START] == 2
    assert len(calls) == 2
