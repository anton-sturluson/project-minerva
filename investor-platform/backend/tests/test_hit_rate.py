from datetime import date
from decimal import Decimal as D
from decimal import localcontext
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from test_ledger import cash
from test_trades import trade

from investor_platform import market
from investor_platform.hit_rate import calculate_hit_rate
from investor_platform.performance import position_episodes

TODAY = date(2026, 2, 1)
DAYS = [date(2026, 1, d) for d in (2, 5, 6, 7)]


def entry(kind, day, quantity, amount, **extra):
    return NS(
        kind=kind,
        effective_date=DAYS[day],
        quantity=D(quantity),
        amount=D(amount),
        security_id=1,
        security=NS(ticker="DEMO", exchange="NASDAQ", currency="USD"),
        **extra,
    )


def histories():
    return {
        "SPY": market.History(
            dict.fromkeys(DAYS, D(999)), dict(zip(DAYS, map(D, (100, 120, 90, 130))))
        ),
        "QQQ": market.History(
            dict.fromkeys(DAYS, D(999)), dict(zip(DAYS, map(D, (100, 105, 120, 130))))
        ),
        "DEMO": market.History(dict.fromkeys(DAYS, D(100)), {}, exchange="NMS"),
    }


def test_profit_can_miss_market_and_loss_can_be_a_hit_with_equal_decision_weights():
    episodes = [
        [entry("buy", 0, "10", "1000"), entry("sell", 1, "10", "1100")],
        [entry("buy", 1, "100", "10000"), entry("sell", 2, "100", "9000")],
        [entry("buy", 2, "1", "100"), entry("sell", 2, "1", "100")],
    ]
    r = calculate_hit_rate(episodes, 2, histories(), TODAY)
    assert r["open"] == 2 and r["excluded"] == 0
    for b in ("SPY", "QQQ"):
        assert r["benchmarks"][b]["hits"] == 1
        assert r["benchmarks"][b]["ties"] == 1
        assert r["benchmarks"][b]["evaluated"] == 3
        assert float(r["benchmarks"][b]["hit_rate"]) == pytest.approx(1 / 3)
    assert r["episodes"][0]["benchmarks"]["SPY"]["excess"] == -100
    assert r["episodes"][1]["benchmarks"]["SPY"]["excess"] == 1500
    assert r["episodes"][0]["benchmarks"]["QQQ"]["excess"] == 50
    assert r["episodes"][1]["benchmarks"]["QQQ"]["excess"] < 0


def test_multiple_buys_partial_exits_and_fees_match_fifo_capital():
    trades = [
        entry("buy", 0, "10", "1002"),
        entry("buy", 1, "10", "2000"),
        entry("sell", 2, "5", "1499"),
        entry("sell", 3, "15", "4499"),
    ]
    episodes, opened = position_episodes(trades)
    assert len(episodes) == 1 and opened == 0
    with localcontext() as ctx:
        ctx.prec = 64
        row = calculate_hit_rate(episodes, opened, histories(), TODAY)["episodes"][0]
        expected = D(501) * D("-0.1") + D(501) * D("0.3") + D(2000) * (D(130) / 120 - 1)
        assert row["pnl"] == 2996
        assert row["benchmarks"]["SPY"]["pnl"] == expected


@pytest.mark.parametrize(
    "case", ["opening", "dividend", "split", "missing", "listing", "today", "old", "unsupported"]
)
def test_unavailable_decisions_are_excluded_not_counted_as_misses(case):
    episode = [entry("buy", 0, "1", "100"), entry("sell", 2, "1", "110")]
    h = histories()
    if case == "opening":
        episode[0].kind = "opening_position"
    elif case == "dividend":
        h["DEMO"].dividends[DAYS[1]] = D(1)
    elif case == "split":
        h["DEMO"].splits.add(DAYS[1])
    elif case == "missing":
        del h["QQQ"].adjusted[DAYS[2]]
    elif case == "listing":
        h["DEMO"].exchange = "NYQ"
    elif case == "today":
        episode[-1].effective_date = TODAY
    elif case == "old":
        episode[0].effective_date = date(2000, 1, 1)
    else:
        episode[0].security.exchange = "TEST"
    r = calculate_hit_rate([episode], 0, h, TODAY)
    assert r["excluded"] == 1 and r["episodes"][0]["excluded"]
    assert r["benchmarks"]["SPY"]["hit_rate"] is None
    assert r["benchmarks"]["QQQ"]["evaluated"] == 0


def test_distribution_on_purchase_date_is_not_earned_and_cent_ties_are_not_hits():
    h = histories()
    h["DEMO"].dividends[DAYS[0]] = D(1)
    episode = [entry("buy", 0, "1", "100"), entry("sell", 0, "1", "100.004")]
    r = calculate_hit_rate([episode], 0, h, TODAY)
    assert r["excluded"] == 0
    assert r["benchmarks"]["SPY"] == {"hit_rate": 0, "hits": 0, "evaluated": 1, "ties": 1}


def test_route_empty_closed_decisions_ownership_and_provider_failure(
    db_client, monkeypatch, expire_prices
):
    aid = db_client.post(
        "/api/accounts", json={"name": "Hit rate fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "10000")
    calls = []

    def fetch(symbol, start, end):
        calls.append(symbol)
        return histories()[symbol]

    monkeypatch.setattr(market, "history", fetch)
    assert (
        db_client.post(f"/api/accounts/{aid}/hit-rate").json()["benchmarks"]["SPY"]["hit_rate"]
        is None
    )
    assert calls == []
    trade(db_client, aid, exchange="NASDAQ")
    trade(db_client, aid, "sell", price="110", exchange="NASDAQ", effective_date="2026-01-05")
    r = db_client.post(f"/api/accounts/{aid}/hit-rate")
    assert r.status_code == 200 and r.json()["benchmarks"]["SPY"]["hit_rate"] == "0"
    assert sorted(calls) == ["DEMO", "QQQ", "SPY"]
    assert db_client.post(f"/api/accounts/{uuid4()}/hit-rate").status_code == 404

    def unavailable(*args):
        raise OSError("synthetic outage")

    expire_prices()
    monkeypatch.setattr(market, "history", unavailable)
    assert db_client.post(f"/api/accounts/{aid}/hit-rate").status_code == 503
    assert db_client.get(f"/api/accounts/{aid}/statistics").status_code == 200


def test_non_usd_account_does_not_fetch_a_usd_benchmark(db_client, monkeypatch):
    aid = db_client.post(
        "/api/accounts", json={"name": "EUR fixture", "base_currency": "EUR"}
    ).json()["id"]

    def unexpected_fetch(*args):
        pytest.fail("No market fetch for an unsupported account currency")

    monkeypatch.setattr(market, "history", unexpected_fetch)
    response = db_client.post(f"/api/accounts/{aid}/hit-rate")
    assert response.status_code == 422 and "USD" in response.json()["detail"]


def test_hit_rate_fetches_only_each_closed_security_window(db_client, monkeypatch):
    aid = db_client.post(
        "/api/accounts", json={"name": "Dated decisions", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "1000")
    for ticker, opened, closed in [
        ("DEMO", "2026-01-02", "2026-01-05"),
        ("OTHER", "2026-01-06", "2026-01-07"),
    ]:
        assert (
            trade(
                db_client,
                aid,
                "buy",
                "1",
                "100",
                ticker=ticker,
                exchange="NASDAQ",
                effective_date=opened,
            ).status_code
            == 201
        )
        assert (
            trade(
                db_client,
                aid,
                "sell",
                "1",
                "110",
                ticker=ticker,
                exchange="NASDAQ",
                effective_date=closed,
            ).status_code
            == 201
        )

    def fetch(securities, start, end, **kwargs):
        assert kwargs["windows"] == {"DEMO": (DAYS[0], DAYS[1]), "OTHER": (DAYS[2], DAYS[3])}
        data = histories()
        data["OTHER"] = data["DEMO"]
        return data

    monkeypatch.setattr(market, "security_histories", fetch)
    result = db_client.post(f"/api/accounts/{aid}/hit-rate")
    assert result.status_code == 200
    assert result.json()["benchmarks"]["SPY"]["evaluated"] == 2
