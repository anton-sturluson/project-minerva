from datetime import date
from decimal import Decimal as D
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from test_ledger import cash, ledger
from test_performance import DAYS, dividend
from test_trades import trade

from investor_platform.models import Account

pytest_plugins = ["test_performance"]


def stock_report(client, aid, **extra):
    return client.post(
        f"/api/accounts/{aid}/performance",
        json={"start": "2026-01-02", "end": "2026-01-06", "scope": "stocks", **extra},
    )


def test_stock_return_ignores_cash_and_uses_ex_date_dividends_once(db_client, portfolio):
    aid, data = portfolio
    cash(db_client, aid, amount="9000", day="2026-01-05")
    cash(db_client, aid, "income", "500", day="2026-01-05")
    data["AAA"].dividends[DAYS[1]] = D("1")
    assert dividend(db_client, aid).status_code == 201
    before = ledger(db_client, aid)
    r = stock_report(db_client, aid)
    assert r.status_code == 200, r.text
    result = r.json()
    # $10 ex-date distribution leaves the stock sleeve; broker payment is not added twice.
    assert float(result["return"]) == pytest.approx(1.11 * 1.1 - 1)
    assert result["warnings"] == []
    assert result["scope"] == "stocks"
    assert D(result["cash"]) == 0
    assert D(result["value"]) == 1210
    assert D(result["SPY"]) == D(".02")
    assert ledger(db_client, aid) == before


def test_partial_sales_and_new_purchase_use_execution_amounts(db_client, portfolio):
    aid, _ = portfolio
    cash(db_client, aid, amount="1000", day="2026-01-05")
    assert (
        trade(
            db_client,
            aid,
            "buy",
            "2",
            "105",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
            fees="2",
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "4",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-06",
            fees="3",
        ).status_code
        == 201
    )
    result = stock_report(db_client, aid).json()
    assert float(result["return"]) == pytest.approx((1320 / 1212) * ((968 + 477) / 1320) - 1)
    assert D(result["value"]) == 968


def test_flat_interval_and_reentry_preserve_prior_returns(db_client, portfolio):
    aid, data = portfolio
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
        ).status_code
        == 201
    )
    flat = stock_report(db_client, aid).json()
    assert D(flat["return"]) == D(".1")
    assert D(flat["value"]) == 0
    day = date(2026, 1, 7)
    for history in data.values():
        history.close[day] = history.adjusted[day] = D("120")
    assert (
        trade(
            db_client,
            aid,
            "buy",
            "5",
            "100",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(day),
        ).status_code
        == 201
    )
    result = stock_report(db_client, aid, end=str(day)).json()
    assert D(result["return"]) == D(".32")


def test_exclusions_remove_stock_capital_and_income_without_writing(db_client, portfolio):
    aid, data = portfolio
    cash(db_client, aid, amount="1000", day="2026-01-05")
    assert (
        trade(
            db_client,
            aid,
            "buy",
            "5",
            "100",
            ticker="SPY",
            exchange="ARCA",
            effective_date="2026-01-05",
        ).status_code
        == 201
    )
    data["AAA"].dividends[DAYS[1]] = D("1")
    before = ledger(db_client, aid)
    sid = next(h["security"]["id"] for h in before["holdings"] if h["security"]["ticker"] == "AAA")
    result = stock_report(db_client, aid, exclude_security_ids=[sid]).json()
    assert result["scenario_error"] is None
    assert D(result["scenario"]["return"]) == D(".01")
    assert D(result["scenario"]["value"]) == 505
    assert ledger(db_client, aid) == before
    ids = [h["security"]["id"] for h in before["holdings"]]
    empty = stock_report(db_client, aid, exclude_security_ids=ids).json()
    assert "at least one stock" in empty["scenario_error"]


def test_cash_reconciliation_and_market_quality_stay_separate(db_client, portfolio, database):
    aid, data = portfolio
    with Session(database) as session:
        account = session.get(Account, UUID(aid))
        account.reconstruction = {"funding_status": "inferred"}
        session.commit()
    assert stock_report(db_client, aid).json()["return"] is not None
    account_report = stock_report(db_client, aid, scope="account").json()
    assert account_report["return"] is None
    del data["AAA"].close[DAYS[1]]
    assert stock_report(db_client, aid).status_code == 422
