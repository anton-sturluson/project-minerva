from datetime import date
from decimal import Decimal as D

import pytest
from test_ledger import cash, ledger
from test_stock_performance import stock_report
from test_trades import trade

pytest_plugins = ["test_performance"]


def test_first_day_execution_gain_is_in_dollars_but_not_time_weighted_return(db_client, portfolio):
    aid, data = portfolio
    for day in data["AAA"].close:
        data["AAA"].close[day] = data["AAA"].adjusted[day] = D(110)
    before = ledger(db_client, aid)
    report = stock_report(db_client, aid).json()
    assert D(report["holdings"][0]["unrealized_pnl"]) == 100
    for period in report["attribution"]:
        assert D(period["gain"]) == 100
        assert D(period["stocks"][0]["gain"]) == 100
        assert D(period["return"]) == D(period["contribution_total"]) == 0
    assert D(report["return"]) == 0
    assert ledger(db_client, aid) == before


def test_first_day_round_trip_retains_net_gain_and_closed_stock(db_client, portfolio):
    aid, _ = portfolio
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-02",
            fees="2",
        ).status_code
        == 201
    )
    report = stock_report(db_client, aid).json()
    assert report["holdings"] == []
    assert D(report["return"]) == 0
    period = report["attribution"][0]
    assert D(period["gain"]) == 98
    assert period["stocks"][0]["ticker"] == "AAA"
    assert D(period["stocks"][0]["contribution"]) == 0


def test_first_day_receipt_is_capital_not_profit_and_later_period_does_not_recount(
    db_client, portfolio
):
    aid, data = portfolio
    for day in data["AAA"].close:
        data["AAA"].close[day] = data["AAA"].adjusted[day] = D(110)
    assert (
        trade(
            db_client,
            aid,
            "transfer_in",
            "5",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-02",
        ).status_code
        == 201
    )
    full = stock_report(db_client, aid).json()
    assert full["holdings"][0]["basis"] is None
    assert D(full["attribution"][0]["gain"]) == 100  # Received $550 is neutral capital.
    later = stock_report(db_client, aid, start="2026-01-05", baseline="recorded").json()
    assert D(later["attribution"][0]["gain"]) == 0
    assert D(later["return"]) == 0


def test_year_end_first_day_keeps_dollars_without_inventing_an_annual_return():
    from decimal import localcontext
    from uuid import uuid4

    from investor_platform.domain import ACCOUNTING_PRECISION
    from investor_platform.market import History
    from investor_platform.models import LedgerEntry, Security
    from investor_platform.performance import PerformanceScope, calculate

    first, last = date(2025, 12, 31), date(2026, 1, 2)
    security = Security(id=uuid4(), ticker="AAA", exchange="NYSE", currency="USD")
    entry = LedgerEntry(
        id=1,
        kind="buy",
        effective_date=first,
        security=security,
        security_id=security.id,
        quantity=D(10),
        amount=D(1000),
    )
    prices = {first: D(110), last: D(110)}
    histories = {
        "AAA": History(prices, prices, exchange="NYQ"),
        "SPY": History(prices, prices),
        "QQQ": History(prices, prices),
    }
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        result = calculate([entry], histories, first, last, scope=PerformanceScope.STOCKS)
    periods = {p["period"]: p for p in result["attribution"]}
    assert D(periods["all"]["gain"]) == 100
    assert periods["2025"]["return"] is None
    assert periods["2025"]["contribution_total"] is None
    assert D(periods["2025"]["gain"]) == 100
    assert D(periods["2026"]["gain"]) == D(periods["2026"]["return"]) == 0


def test_stock_contributions_include_both_winners_and_losers_and_reconcile(db_client, portfolio):
    aid, data = portfolio
    cash(db_client, aid, amount="500", day="2026-01-02")
    assert (
        trade(
            db_client,
            aid,
            "buy",
            "5",
            "100",
            ticker="SPY",
            exchange="ARCA",
            effective_date="2026-01-02",
        ).status_code
        == 201
    )
    data["SPY"].close[date(2026, 1, 5)] = D("90")
    data["SPY"].close[date(2026, 1, 6)] = D("80")
    before = ledger(db_client, aid)
    report = stock_report(db_client, aid).json()
    for period in report["attribution"]:
        by_ticker = {row["ticker"]: row for row in period["stocks"]}
        assert D(by_ticker["AAA"]["contribution"]) == D(".14")
        assert float(by_ticker["SPY"]["contribution"]) == pytest.approx(-100 / 1500)
        assert D(period["gain"]) == 110
        assert D(period["return"]) == D(report["return"])
        assert abs(D(period["contribution_total"]) - D(report["return"])) < D("1e-20")
    assert ledger(db_client, aid) == before


def test_dividends_trading_fees_and_closed_positions_remain_attributed(db_client, portfolio):
    aid, data = portfolio
    data["AAA"].dividends[date(2026, 1, 5)] = D(1)
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
            fees="2",
        ).status_code
        == 201
    )
    report = stock_report(db_client, aid).json()
    period = report["attribution"][0]
    assert len(period["stocks"]) == 1
    assert D(period["stocks"][0]["gain"]) == 108  # $100 price gain + $10 gross dividend - $2 fee.
    assert D(period["stocks"][0]["contribution"]) == D(".108")
    assert report["holdings"] == []


def test_yearly_linking_resets_at_prior_year_end_without_losing_cross_year_holdings(
    db_client, portfolio
):
    aid, data = portfolio
    for h in data.values():
        h.close[date(2026, 12, 31)] = D(150)
        h.adjusted[date(2026, 12, 31)] = D(150)
        h.close[date(2027, 1, 4)] = D(165)
        h.adjusted[date(2027, 1, 4)] = D(165)
    # Pure calculation avoids future-date API validation and future providers.
    from decimal import localcontext
    from uuid import UUID

    from sqlalchemy.orm import Session

    from investor_platform.ledger import entries_for
    from investor_platform.performance import PerformanceScope, calculate

    with Session(db_client.app.state.engine) as session, localcontext() as ctx:
        ctx.prec = 64
        result = calculate(
            entries_for(session, UUID(aid)),
            data,
            date(2026, 1, 2),
            date(2027, 1, 4),
            scope=PerformanceScope.STOCKS,
        )
    reports = {p["period"]: p for p in result["attribution"]}
    assert reports["2026"]["return"] == D(".5")
    assert reports["2027"]["return"] == D(".1")
    assert reports["2027"]["start"] == date(2026, 12, 31)
    assert reports["all"]["return"] == D(".65")
    assert reports["2027"]["stocks"][0]["contribution"] == D(".1")
