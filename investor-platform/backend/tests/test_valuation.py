from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from test_trades import trade

from investor_platform import market
from investor_platform.domain import Currency
from investor_platform.market import History

pytest_plugins = ["test_performance"]


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
    [("ASX", ".AX", Currency.AUD, "ASX"), ("TSXV", ".V", Currency.CAD, "VAN")],
)
def test_foreign_closes_use_matching_usd_fx_and_never_change_ledger(
    db_client, portfolio, monkeypatch, exchange, suffix, currency, provider
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
    gap = True
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert result["value"] is None and result["holdings"][1]["price_error"]
