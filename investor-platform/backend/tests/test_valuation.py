from datetime import date, timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from test_trades import trade

from investor_platform import market, valuation
from investor_platform.domain import Currency
from investor_platform.market import History

pytest_plugins = ["test_performance"]


def test_old_held_split_withholds_values_liquidation_and_collection(
    db_client, database, portfolio, monkeypatch
):
    from test_ledger import ledger

    aid, _ = portfolio
    trade(db_client, aid, "opening_position", "2", ticker="BBB", exchange="NYSE")
    end, split = date(2026, 1, 30), date(2026, 1, 5)
    monkeypatch.setattr(valuation, "completed_market_date", lambda: end)
    before = ledger(db_client, aid)

    def quote(symbol, start, through):
        if symbol == "AAA":
            assert start <= date(2026, 1, 2)  # Split is older than the ten-day quote window.
        return History(
            {end: D(50)}, {}, splits={split} if symbol == "AAA" else set(), exchange="NYQ"
        )

    monkeypatch.setattr(market, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    a, b = result["holdings"]
    assert result["value"] is None and not result["complete"]
    assert a["value"] is None and a["unrealized_pnl"] is None
    assert a["price_error"] == "Split adjustment required (2026-01-05)"
    assert D(b["value"]) == 100 and b["price_error"] is None
    assert a["weight"] is None and b["weight"] is None
    hypothetical = db_client.get(f"/api/accounts/{aid}/statistics/hypothetical")
    assert hypothetical.status_code == 503
    assert "AAA: Split adjustment required" in hypothetical.json()["detail"]
    assert ledger(db_client, aid) == before
    from datetime import UTC, datetime
    from uuid import UUID

    from sqlalchemy.orm import Session

    from investor_platform.models import Account
    from investor_platform.price_refresh import collect_account

    with Session(database) as session, pytest.raises(ValueError, match="holding prices"):
        collect_account(session, session.get(Account, UUID(aid)), end, datetime.now(UTC))


@pytest.mark.parametrize("split", [date(2026, 1, 5), date(2026, 1, 20)])
def test_split_before_or_on_reentry_does_not_invalidate_new_share_units(
    db_client, portfolio, monkeypatch, split
):
    aid, _ = portfolio
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "121",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-06",
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            "buy",
            "10",
            "50",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-20",
        ).status_code
        == 201
    )
    end = date(2026, 1, 30)
    monkeypatch.setattr(valuation, "completed_market_date", lambda: end)

    def quote(symbol, start, through):
        assert start == date(2026, 1, 20)
        return History({end: D(50)}, {}, splits={split}, exchange="NYQ")

    monkeypatch.setattr(market, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert result["complete"]
    assert D(result["holdings"][0]["value"]) == 500
    assert D(result["holdings"][0]["unrealized_pnl"]) == 0


def test_pre_split_previous_close_cannot_value_a_post_split_purchase(db_client, monkeypatch):
    from test_ledger import cash

    aid = db_client.post(
        "/api/accounts", json={"name": "Split-day fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000", day="2026-01-05")
    trade(
        db_client,
        aid,
        "buy",
        "20",
        "50",
        ticker="AAA",
        exchange="NYSE",
        effective_date="2026-01-05",
    )
    monkeypatch.setattr(valuation, "completed_market_date", lambda: date(2026, 1, 4))
    monkeypatch.setattr(
        market,
        "history",
        lambda *args: History(
            {date(2026, 1, 2): D(100)}, {}, splits={date(2026, 1, 5)}, exchange="NYQ"
        ),
    )
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert not result["complete"]
    assert "Split adjustment required" in result["holdings"][0]["price_error"]


def test_quotes_only_open_positions_even_with_large_closed_history(
    db_client, portfolio, monkeypatch
):
    aid, _ = portfolio
    for index in range(market.MAX_SECURITIES):
        symbol = f"OLD{index}"
        assert trade(db_client, aid, "opening_position", "1", ticker=symbol).status_code == 201
        assert trade(db_client, aid, "sell", "1", "1", ticker=symbol).status_code == 201
    calls = []

    def quote(symbol, start, end):
        calls.append(symbol)
        return History({end: D(120)}, {end: D(120)}, exchange="NYQ")

    monkeypatch.setattr(market, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert calls == ["AAA"]  # Closed/delisted holdings need no quotes for today's valuation.
    assert result["complete"] and D(result["value"]) == D(1200 + market.MAX_SECURITIES)
    assert D(result["holdings"][0]["unrealized_pnl"]) == 200
    assert db_client.get(f"/api/accounts/{uuid4()}/valuation").status_code == 404


@pytest.mark.parametrize("failure", ["outage", "stale", "identity"])
def test_partial_quote_failure_retains_other_values_without_partial_weights(
    db_client, portfolio, monkeypatch, failure
):
    aid, _ = portfolio
    trade(db_client, aid, "opening_position", "2", ticker="BBB", exchange="NASDAQ")

    def quote(symbol, start, end):
        if symbol == "BBB":
            if failure == "outage":
                raise OSError("offline")
            return History(
                {end - timedelta(days=5) if failure == "stale" else end: D(10)},
                {},
                exchange="NYQ" if failure == "identity" else "NMS",
            )
        return History({end: D(120)}, {}, exchange="NYQ")

    monkeypatch.setattr(market, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert not result["complete"] and result["value"] is None
    a, b = result["holdings"]
    assert D(a["value"]) == 1200 and a["price_error"] is None
    assert b["value"] is None and b["price_error"]
    assert a["weight"] is None and b["weight"] is None


@pytest.mark.parametrize(
    "exchange,suffix,currency,provider",
    [
        ("ASX", ".AX", Currency.AUD, "ASX"),
        ("TSXV", ".V", Currency.CAD, "VAN"),
        ("WSE", ".WA", "PLN", "WSE"),
    ],
)
def test_foreign_closes_use_matching_usd_fx_and_never_change_ledger(
    db_client, portfolio, monkeypatch, exchange, suffix, currency, provider, expire_prices
):
    from test_ledger import ledger

    aid, _ = portfolio
    trade(
        db_client,
        aid,
        "opening_position",
        "2",
        ticker="FOREIGN",
        exchange=exchange,
        cost_basis="10",
    )
    before = ledger(db_client, aid)
    gap = False

    def quote(symbol, start, end, **kwargs):
        if symbol == f"{currency}USD=X":
            assert kwargs == {"instruments": ("CURRENCY",)}
            return History({end - timedelta(days=1) if gap else end: D(".7")}, {}, exchange="CCY")
        if symbol == f"FOREIGN{suffix}":
            assert kwargs == {"currency": currency}
            return History({end: D(10)}, {}, exchange=provider)
        return History({end: D(120)}, {}, exchange="NYQ")

    monkeypatch.setattr(market, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert D(result["value"]) == 1214
    assert D(result["holdings"][1]["close"]) == 7
    assert D(result["holdings"][1]["unrealized_pnl"]) == 4
    assert ledger(db_client, aid) == before
    expire_prices()
    gap = True
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert result["value"] is None and result["holdings"][1]["price_error"]


def test_hypothetical_closes_finish_whole_episodes_and_leave_records_unchanged(
    db_client, portfolio, monkeypatch, expire_prices
):
    from test_ledger import ledger

    aid, _ = portfolio
    trade(db_client, aid, "sell", "5", "90", ticker="AAA", exchange="NYSE")
    trade(db_client, aid, quantity="1", price="200", fees="2", ticker="CCC", exchange="NYSE")
    trade(db_client, aid, quantity="1", price="100", ticker="DDD")
    trade(db_client, aid, "sell", "1", "90", ticker="DDD")
    trade(db_client, aid, "opening_position", "1", ticker="UNKNOWN", exchange="NYSE")
    before = ledger(db_client, aid)
    realized = db_client.get(f"/api/accounts/{aid}/statistics").json()
    calls = []

    def quote(symbol, start, end):
        calls.append(symbol)
        return History({end: D(120 if symbol == "AAA" else 150)}, {}, exchange="NYQ")

    monkeypatch.setattr(market, "history", quote)
    url = f"/api/accounts/{aid}/statistics/hypothetical"
    response = db_client.get(url)
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(calls) == {"AAA", "CCC", "UNKNOWN"}  # No closed/delisted history needed.
    assert (result["wins"], result["losses"], result["unknown"], result["open"]) == (1, 2, 1, 0)
    assert result["simulated_positions"] == 3
    assert float(result["win_rate"]) == pytest.approx(1 / 3)
    assert float(result["payoff_ratio"]) == pytest.approx(50 / 31)
    assert sum(e["hypothetical"] for e in result["episodes"]) == 3
    assert D(next(e for e in result["episodes"] if e["ticker"] == "AAA")["pnl"]) == 50
    assert ledger(db_client, aid) == before
    assert db_client.get(f"/api/accounts/{aid}/statistics").json() == realized
    assert db_client.get(f"/api/accounts/{uuid4()}/statistics/hypothetical").status_code == 404

    def unavailable(*args):
        raise OSError("offline")

    expire_prices()
    monkeypatch.setattr(market, "history", unavailable)
    response = db_client.get(url)
    assert response.status_code == 503 and "Latest prices unavailable" in response.json()["detail"]
    assert ledger(db_client, aid) == before
