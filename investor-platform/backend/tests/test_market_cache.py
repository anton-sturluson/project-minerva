from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from investor_platform import market
from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import MarketCache, Owner, Workspace

START, END = date(2026, 1, 2), date(2026, 1, 5)


def test_cache_single_flight_precision_and_period_slicing(database, monkeypatch):
    calls = []
    price = Decimal("123.12345678901234567890123456789")

    def download(symbol, first, last):
        calls.append((symbol, first, last))
        return market.History(
            {START: price, END: price + 1},
            {START: price, END: price},
            {END: Decimal(".5")},
            {END + timedelta(days=1)},
            "NYQ",
        )

    monkeypatch.setattr(market, "history", download)

    def read(end):
        return market.cached_history(
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


def test_cache_expiry_range_growth_and_failed_refresh_preserves_prices(database, monkeypatch):
    calls = []
    fail = False

    def download(symbol, first, last):
        calls.append((first, last))
        if fail:
            raise ValueError("Invalid provider response")
        return market.History({START: Decimal(10), END: Decimal(11)}, {})

    monkeypatch.setattr(market, "history", download)

    def read(start=START, end=END):
        return market.cached_history(
            "AAA", start, end, engine=database, workspace_id=LOCAL_WORKSPACE
        )

    read()
    read(START - timedelta(days=1))
    assert calls[-1] == (START - timedelta(days=1), END)
    with Session(database) as session, session.begin():
        session.execute(
            update(MarketCache).values(fetched_at=datetime.now(UTC) - timedelta(days=2))
        )
    fail = True
    with pytest.raises(ValueError):
        read()
    with Session(database) as session:
        row = session.query(MarketCache).one()
        assert row.payload["close"][START.isoformat()] == "10"
        assert datetime.now(UTC) - row.fetched_at > timedelta(days=1)
    fail = False
    read()
    assert len(calls) == 4


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
        return market.History({START: Decimal(10)}, {})

    monkeypatch.setattr(market, "history", download)
    for workspace_id in [LOCAL_WORKSPACE, workspace]:
        market.cached_history("AAA", START, END, engine=database, workspace_id=workspace_id)
    with pytest.raises(ValueError, match="currency"):
        market.cached_history(
            "AAA", START, END, engine=database, workspace_id=workspace, currency="CAD"
        )
    assert len(calls) == 3


def test_cached_prices_do_not_hide_ledger_edits(db_client, monkeypatch):
    from test_ledger import cash
    from test_trades import trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Cache fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="2", price="100", exchange="NYSE")
    calls = []

    def download(symbol, first, last):
        calls.append(symbol)
        return market.History({last: Decimal(120)}, {}, exchange="NYQ")

    monkeypatch.setattr(market, "history", download)
    url = f"/api/accounts/{aid}/valuation"
    assert Decimal(db_client.get(url).json()["value"]) == 1040
    cash(db_client, aid, "deposit", "500")
    assert Decimal(db_client.get(url).json()["value"]) == 1540
    assert len(calls) == 1


def test_scheduled_refresh_bypasses_ttl_and_reuses_its_results(database, monkeypatch):
    calls = []

    def download(symbol, first, last):
        calls.append(symbol)
        return market.History({START: Decimal(len(calls))}, {})

    monkeypatch.setattr(market, "history", download)

    def read(**kwargs):
        return market.cached_history(
            "AAA", START, END, engine=database, workspace_id=LOCAL_WORKSPACE, **kwargs
        )

    assert read().close[START] == 1
    cutoff = datetime.now(UTC)
    assert read(refresh_after=cutoff).close[START] == 2
    assert read(refresh_after=cutoff).close[START] == 2
    assert read().close[START] == 2
    assert len(calls) == 2
