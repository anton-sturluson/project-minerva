from datetime import date
from decimal import Decimal as D

import pytest
from test_ledger import cash, ledger
from test_stock_performance import stock_report
from test_trades import trade

pytest_plugins = ["test_performance"]


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
