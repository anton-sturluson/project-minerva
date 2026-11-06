from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from helpers import cash
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.domain import completed_market_date
from investor_platform.market_data import history as market
from investor_platform.market_data import price_refresh as price_refresh
from investor_platform.market_data import types as market_types
from investor_platform.market_data import yahoo as market_yahoo
from investor_platform.models import Account, PriceRefreshRun


@pytest.mark.parametrize(
    ("stamp", "day"),
    [
        ("2026-03-07T21:59:59+00:00", "2026-03-06"),
        ("2026-03-07T22:00:00+00:00", "2026-03-07"),
        ("2026-03-08T20:59:59+00:00", "2026-03-07"),
        ("2026-03-08T21:00:00+00:00", "2026-03-08"),
        ("2026-11-01T21:59:59+00:00", "2026-10-31"),
        ("2026-11-01T22:00:00+00:00", "2026-11-01"),
    ],
)
def test_five_pm_cutoff_follows_new_york_daylight_saving(stamp, day):
    assert str(completed_market_date(datetime.fromisoformat(stamp))) == day


def test_refresh_is_durable_deduplicated_and_keeps_accounts_separate(
    db_client, database, monkeypatch
):
    ids = [
        db_client.post(
            "/api/accounts", json={"name": f"Synthetic {i}", "base_currency": "USD"}
        ).json()["id"]
        for i in range(2)
    ]
    monkeypatch.setattr(db_client.app.state, "daily_prices", True)
    calls, failed = [], {ids[0]}
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)

    def collect(session, account, day, refresh_after):
        calls.append(str(account.id))
        assert day == date(2026, 1, 5)
        assert refresh_after >= now
        if str(account.id) in failed:
            raise OSError("sensitive provider detail")
        return price_refresh.AccountCollection(close=day)

    monkeypatch.setattr(price_refresh, "collect_account", collect)
    report, retry = price_refresh.refresh_workspace(database, now=now)
    assert (report["collected"], report["failed"], report["attempts"]) == (1, 1, 1)
    assert retry == now + timedelta(minutes=30)
    status = db_client.get("/api/market-data/status").json()
    assert datetime.fromisoformat(status["next_due_at"]) == retry
    assert "sensitive" not in str(report)
    price_refresh.refresh_workspace(database, now=now + timedelta(minutes=1))
    assert len(calls) == 2
    failed.clear()
    report, next_run = price_refresh.refresh_workspace(database, now=retry)
    assert report["status"] == "complete" and report["collected"] == 2
    assert next_run == now + timedelta(days=1)
    status = db_client.get("/api/market-data/status").json()
    assert datetime.fromisoformat(status["next_due_at"]) == next_run
    price_refresh.refresh_workspace(database, now=retry + timedelta(minutes=1))
    assert len(calls) == 4  # A restart cannot run the successful collection again.
    with Session(database) as session:
        saved = session.get(PriceRefreshRun, (LOCAL_WORKSPACE, now.date()))
        assert saved.attempts == 2 and saved.report == report


def test_concurrent_collectors_skip_busy_run(db_client, database, monkeypatch):
    db_client.post("/api/accounts", json={"name": "Concurrent fixture", "base_currency": "USD"})
    entered, release = Event(), Event()
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)

    def collect(*args):
        entered.set()
        assert release.wait(5)
        return price_refresh.AccountCollection(close=now.date())

    monkeypatch.setattr(price_refresh, "collect_account", collect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(price_refresh.refresh_workspace, database, now=now)
        try:
            assert entered.wait(5)
            other, _ = price_refresh.refresh_workspace(database, now=now)
            assert other["status"] == "running"
        finally:
            release.set()
        assert task.result()[0]["status"] == "complete"


def test_late_provider_or_holiday_is_retried_only_three_times(db_client, database, monkeypatch):
    db_client.post("/api/accounts", json={"name": "Late data fixture", "base_currency": "USD"})
    monkeypatch.setattr(
        price_refresh,
        "collect_account",
        lambda *args: price_refresh.AccountCollection(close=date(2026, 1, 2)),
    )
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)
    for attempt in range(1, 4):
        report, next_run = price_refresh.refresh_workspace(database, now=now)
        assert report["attempts"] == attempt and report["status"] == "awaiting_close"
        now += timedelta(minutes=30)
    assert next_run == datetime(2026, 1, 6, 22, tzinfo=UTC)
    assert price_refresh.refresh_workspace(database, now=now)[0]["attempts"] == 3


def test_collection_warms_history_and_holdings_without_changing_transactions(
    db_client, database, monkeypatch
):
    from helpers import trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Collector fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="1", price="10", exchange="NYSE")
    before = db_client.get(f"/api/accounts/{aid}/ledger").json()
    calls = []

    def history(symbol, start, end, **options):
        from decimal import Decimal

        calls.append(symbol)
        return market_types.History({end: Decimal(10)}, {end: Decimal(10)}, exchange="NYQ")

    monkeypatch.setattr(market_yahoo, "history", history)
    with Session(database) as session:
        day = completed_market_date()
        close = price_refresh.collect_account(
            session, session.get(Account, UUID(aid)), day, datetime.now(UTC)
        )
    assert close.close == day and not close.failures and set(calls) == {"DEMO", "SPY", "QQQ"}
    assert db_client.get(f"/api/accounts/{aid}/ledger").json() == before


def test_delayed_same_date_fx_triggers_retry_even_when_yahoo_holdings_can_price(
    db_client, database, monkeypatch
):
    from decimal import Decimal

    from helpers import trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Late FX fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="1", price="10", exchange="TSX")
    day = completed_market_date()
    history = market_types.History({day: Decimal(10)}, {}, exchange="PCX")
    local = market_types.History({day - timedelta(days=1): Decimal(10)}, {}, exchange="TOR")
    monkeypatch.setattr(market.market_yahoo, "cached_history", lambda *args, **kwargs: history)
    monkeypatch.setattr(market, "listing_history", lambda *args, **kwargs: local)
    monkeypatch.setattr(market, "fx_history", lambda *args, **kwargs: local)
    with Session(database) as session:
        result = price_refresh.collect_account(
            session, session.get(Account, UUID(aid)), day, datetime.now(UTC)
        )
    assert {
        "symbol": "DEMO.TO",
        "scope": "history",
        "reason": "history_unavailable",
    } in result.failures


def test_attempt_is_visible_during_io_and_interruption_consumes_retry(
    db_client, database, monkeypatch
):
    db_client.post("/api/accounts", json={"name": "Interrupted fixture", "base_currency": "USD"})
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)

    def interrupted(*args):
        response = db_client.get("/api/market-data/status")
        assert response.status_code == 200
        assert response.json()["report"]["status"] == "running"
        assert response.json()["report"]["attempts"] == 1
        raise RuntimeError("simulated worker termination")

    monkeypatch.setattr(price_refresh, "collect_account", interrupted)
    with pytest.raises(RuntimeError, match="termination"):
        price_refresh.refresh_workspace(database, now=now)
    report, retry = price_refresh.refresh_workspace(database, now=now + timedelta(minutes=1))
    assert report["attempts"] == 1 and retry == now + timedelta(minutes=30)
    monkeypatch.setattr(
        price_refresh,
        "collect_account",
        lambda *args: price_refresh.AccountCollection(close=now.date()),
    )
    report, _ = price_refresh.refresh_workspace(database, now=retry)
    assert report["status"] == "complete" and report["attempts"] == 2
    status = db_client.get("/api/market-data/status").json()
    assert datetime.fromisoformat(status["last_success_at"]) == retry
    assert status["enabled"] is False and status["worker_alive"] is False
    assert status["next_due_at"] is None


def test_unavailable_sold_listing_does_not_block_current_prices(db_client, database, monkeypatch):
    from decimal import Decimal

    from helpers import trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Independent prices", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, ticker="OLD", quantity="1", price="10", exchange="NYSE")
    trade(db_client, aid, ticker="OLD", kind="sell", quantity="1", price="10", exchange="NYSE")
    trade(db_client, aid, ticker="NEW", quantity="1", price="10", exchange="NYSE")

    def history(symbol, start, end, **kwargs):
        if symbol == "OLD":
            raise OSError("provider URL with private token")
        return market_types.History({end: Decimal(10)}, {end: Decimal(10)}, exchange="NYQ")

    monkeypatch.setattr(market_yahoo, "history", history)
    report, _ = price_refresh.refresh_workspace(database)
    assert report["status"] == "partial"
    assert report["failures"] == [
        {"symbol": "OLD", "scope": "history", "reason": "history_unavailable"}
    ]
    assert "private token" not in str(report)
    with Session(database) as session:
        from sqlalchemy import select

        from investor_platform.models import MarketCache

        saved = session.scalar(select(MarketCache).where(MarketCache.symbol.like("NEW:%")))
        assert saved is not None and saved.payload["close"]

    def unexpected(*args, **kwargs):
        pytest.fail("Current prices should already be collected despite historical failure")

    monkeypatch.setattr(market_yahoo, "history", unexpected)
    valuation = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert valuation["complete"] is True
    assert valuation["holdings"][0]["ticker"] == "NEW"
    assert valuation["holdings"][0]["close"] == "10"


def test_status_normalizes_legacy_reports_without_downloads(db_client, database, monkeypatch):
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)
    with Session(database) as session:
        session.add(
            PriceRefreshRun(
                workspace_id=LOCAL_WORKSPACE,
                scheduled_date=now.date(),
                attempted_at=now,
                attempts=1,
                report={"status": "complete", "collected": 1},
            )
        )
        session.commit()

    def unexpected(*args, **kwargs):
        pytest.fail("Status must not request prices")

    monkeypatch.setattr(market_yahoo, "history", unexpected)
    response = db_client.get("/api/market-data/status")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["report"]["failures"] == []
    assert datetime.fromisoformat(response.json()["last_success_at"]) == now
    denied = db_client.get("/api/market-data/status", headers={"Origin": "https://example.com"})
    assert denied.status_code == 403


def test_interrupted_final_attempt_is_not_reported_as_running(db_client, database, monkeypatch):
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)
    with Session(database) as session:
        session.add(
            PriceRefreshRun(
                workspace_id=LOCAL_WORKSPACE,
                scheduled_date=now.date(),
                attempted_at=now,
                attempts=3,
                report={"status": "running", "attempts": 3},
            )
        )
        session.commit()
    report, due = price_refresh.refresh_workspace(database, now=now + timedelta(minutes=30))
    assert report["status"] == "interrupted" and report["attempts"] == 3
    assert due == now + timedelta(days=1)
    assert db_client.get("/api/market-data/status").json()["report"]["status"] == "interrupted"


def test_retry_collects_new_close_while_normal_reads_keep_accepted_prices(
    db_client, database, monkeypatch
):
    from decimal import Decimal

    from helpers import trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Late close", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="1", price="10", exchange="NYSE")
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)
    from investor_platform.market_data import cache

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(cache, "datetime", Clock)
    available = date(2026, 1, 2)

    def history(symbol, start, end, **kwargs):
        return market_types.History(
            {available: Decimal(10)}, {available: Decimal(10)}, exchange="NYQ"
        )

    monkeypatch.setattr(market_yahoo, "history", history)
    report, retry = price_refresh.refresh_workspace(database, now=now)
    assert report["status"] == "awaiting_close"
    available = now.date()
    stored = market_yahoo.cached_history(
        "SPY",
        date(2026, 1, 2),
        now.date(),
        engine=database,
        workspace_id=LOCAL_WORKSPACE,
    )
    assert max(stored.close) == date(2026, 1, 2)
    now = retry
    report, _ = price_refresh.refresh_workspace(database, now=now)
    assert report["status"] == "complete"
    stored = market_yahoo.cached_history(
        "SPY",
        date(2026, 1, 2),
        now.date(),
        engine=database,
        workspace_id=LOCAL_WORKSPACE,
    )
    assert max(stored.close) == now.date()


def test_empty_account_is_skipped_and_force_retries_completed_run(db_client, database):
    db_client.post("/api/accounts", json={"name": "Empty fixture", "base_currency": "USD"})
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)
    first, due = price_refresh.refresh_workspace(database, now=now)
    assert first["status"] == "complete"
    assert (first["skipped"], first["collected"], first["failed"]) == (1, 0, 0)
    forced, forced_due = price_refresh.refresh_workspace(
        database, now=now + timedelta(minutes=1), force=True
    )
    assert forced["attempts"] == 2 and forced["skipped"] == 1
    assert forced_due == due == now + timedelta(days=1)
