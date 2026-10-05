from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from test_ledger import cash

from investor_platform import market, price_refresh
from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.domain import completed_market_date
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
    calls, failed = [], {ids[0]}
    now = datetime(2026, 1, 5, 22, tzinfo=UTC)

    def collect(session, account, day, refresh_after):
        calls.append(str(account.id))
        assert day == date(2026, 1, 5)
        assert refresh_after >= now
        if str(account.id) in failed:
            raise OSError("sensitive provider detail")
        return day

    monkeypatch.setattr(price_refresh, "collect_account", collect)
    report, retry = price_refresh.refresh_workspace(database, now=now)
    assert (report["collected"], report["failed"], report["attempts"]) == (1, 1, 1)
    assert retry == now + timedelta(minutes=30)
    assert "sensitive" not in str(report)
    price_refresh.refresh_workspace(database, now=now + timedelta(minutes=1))
    assert len(calls) == 2
    failed.clear()
    report, next_run = price_refresh.refresh_workspace(database, now=retry)
    assert report["status"] == "complete" and report["collected"] == 2
    assert next_run == now + timedelta(days=1)
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
        return now.date()

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
    monkeypatch.setattr(price_refresh, "collect_account", lambda *args: date(2026, 1, 2))
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
    from test_trades import trade

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
        return market.History({end: Decimal(10)}, {end: Decimal(10)}, exchange="NYQ")

    monkeypatch.setattr(market, "history", history)
    with Session(database) as session:
        day = completed_market_date()
        close = price_refresh.collect_account(
            session, session.get(Account, UUID(aid)), day, datetime.now(UTC)
        )
    assert close == day and set(calls) == {"DEMO", "SPY", "QQQ"}
    assert db_client.get(f"/api/accounts/{aid}/ledger").json() == before


def test_delayed_same_date_fx_triggers_retry_even_when_yahoo_holdings_can_price(
    db_client, database, monkeypatch
):
    from decimal import Decimal

    from test_trades import trade

    aid = db_client.post(
        "/api/accounts", json={"name": "Late FX fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    trade(db_client, aid, quantity="1", price="10", exchange="TSX")
    day = completed_market_date()
    history = market.History({day: Decimal(10)}, {}, exchange="PCX")
    local = market.History({day - timedelta(days=1): Decimal(10)}, {}, exchange="TOR")
    monkeypatch.setattr(
        market,
        "security_histories",
        lambda *args, **kwargs: {"SPY": history, "QQQ": history, "DEMO.TO": local},
    )
    with Session(database) as session:
        with pytest.raises(ValueError, match="same-date FX"):
            price_refresh.collect_account(
                session, session.get(Account, UUID(aid)), day, datetime.now(UTC)
            )
