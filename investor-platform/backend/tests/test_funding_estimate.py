from decimal import Decimal as D
from uuid import UUID

import pytest
from helpers import DAYS, cash, dividend, ledger, stock_report, trade
from sqlalchemy import select
from sqlalchemy.orm import Session

from investor_platform.domain import EntryKind
from investor_platform.models import Account, LedgerEntry


@pytest.fixture
def inferred(portfolio, database):
    aid, data = portfolio
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "funding_status": "inferred",
            "opening_cash": "1000",
        }
        session.commit()
    return aid, data


def estimated(client, aid, **extra):
    response = stock_report(client, aid, benchmark_mode="funded_hold", **extra)
    assert response.status_code == 200, response.text
    return response.json()


def test_recycled_proceeds_never_become_new_index_money(db_client, inferred):
    aid, _ = inferred
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            quantity="12",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[2]),
        ).status_code
        == 201
    )
    before = ledger(db_client, aid)
    result = estimated(db_client, aid)
    assert D(result["funding_estimate"]["capital"]) == 1000
    assert D(result["benchmark_values"]["SPY"]["value"]) == 1020
    assert D(result["benchmark_values"]["QQQ"]["value"]) == 1040
    assert D(result["value"]) == 1452
    assert D(result["return"]) == D(".452")
    assert result["scope"] == "account" and result["attribution"] is None
    assert ledger(db_client, aid) == before


def test_initial_net_profitable_roundtrip_cannot_imply_free_capital(db_client, inferred):
    aid, _ = inferred
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "10",
            "110",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[0]),
        ).status_code
        == 201
    )
    response = stock_report(db_client, aid, benchmark_mode="funded_hold")
    assert response.status_code == 422 and "intraday funding" in response.json()["detail"]


def test_partial_sales_retain_cash_and_reuse_it(db_client, inferred):
    aid, _ = inferred
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "4",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client, aid, quantity="4", ticker="AAA", exchange="NYSE", effective_date=str(DAYS[2])
        ).status_code
        == 201
    )
    result = estimated(db_client, aid)
    assert D(result["value"]) == 1290 and D(result["cash"]) == 80
    assert D(result["funding_estimate"]["capital"]) == 1000
    assert D(result["benchmark_values"]["SPY"]["value"]) == 1020
    assert sum(D(h["weight"]) for h in result["holdings"]) == D(1210) / D(1290)


def test_estimated_dividends_reduce_new_cash_and_are_not_contributions(db_client, inferred):
    aid, data = inferred
    data["AAA"].dividends[DAYS[1]] = D(5)  # $50 of gross dividend cash.
    # The recorded account's placeholder needs enough cash to accept this purchase.
    # Change only synthetic bookkeeping; the estimate must independently infer $50.
    result = estimated(db_client, aid)
    assert D(result["cash"]) == 50
    assert D(result["value"]) == 1260
    assert D(result["return"]) == D(".26")
    assert D(result["funding_estimate"]["estimated_dividends"]) == 50
    assert D(result["funding_estimate"]["capital"]) == 1000
    assert D(result["benchmark_values"]["SPY"]["value"]) == 1020


def enlarge_placeholder(database, aid, amount):
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "funding_status": "inferred",
            "opening_cash": str(amount),
        }
        row = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.account_id == UUID(aid),
                LedgerEntry.kind == EntryKind.OPENING_CASH,
            )
        )
        row.amount = D(amount)
        session.commit()


def test_dividend_cash_funds_a_later_purchase_before_new_cash(db_client, inferred, database):
    aid, data = inferred
    enlarge_placeholder(database, aid, 1100)
    data["AAA"].dividends[DAYS[1]] = D(5)
    assert (
        trade(
            db_client, aid, quantity="1", ticker="AAA", exchange="NYSE", effective_date=str(DAYS[2])
        ).status_code
        == 201
    )
    result = estimated(db_client, aid)
    assert D(result["funding_estimate"]["fresh_cash"]) == 1050
    assert D(result["value"]) == 1331
    assert D(result["cash"]) == 0
    assert D(result["benchmark_values"]["SPY"]["value"]) == 1070


def test_same_day_sale_can_fund_a_buy_without_new_capital(db_client, inferred):
    aid, _ = inferred
    # Buy is entered first. Intraday order is not reliable; net by effective date.
    assert (
        trade(
            db_client, aid, quantity="3", ticker="AAA", exchange="NYSE", effective_date=str(DAYS[1])
        ).status_code
        == 409
    )  # cash remains negative until sale
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "5",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client, aid, quantity="3", ticker="AAA", exchange="NYSE", effective_date=str(DAYS[1])
        ).status_code
        == 201
    )
    result = estimated(db_client, aid)
    assert D(result["funding_estimate"]["fresh_cash"]) == 1000
    assert D(result["cash"]) == 300
    assert D(result["value"]) == 1268


def test_weekend_buy_cannot_borrow_from_a_later_monday_sale(db_client, inferred, database):
    aid, _ = inferred
    enlarge_placeholder(database, aid, 1500)
    assert (
        trade(
            db_client, aid, quantity="5", ticker="AAA", exchange="NYSE", effective_date="2026-01-03"
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "5",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
        ).status_code
        == 201
    )
    result = estimated(db_client, aid)
    assert D(result["funding_estimate"]["fresh_cash"]) == 1500
    assert D(result["cash"]) == 600
    assert float(result["benchmark_values"]["SPY"]["value"]) == pytest.approx(
        1020 + 500 * 102 / 101
    )


def test_receipts_are_once_only_external_capital_at_close(db_client, inferred):
    aid, _ = inferred
    assert (
        trade(
            db_client,
            aid,
            "transfer_in",
            "2",
            ticker="AAA",
            exchange="NYSE",
            effective_date=str(DAYS[1]),
            cost_basis=None,
        ).status_code
        == 201
    )
    result = estimated(db_client, aid)
    assert D(result["funding_estimate"]["received_assets"]) == 220
    assert D(result["funding_estimate"]["capital"]) == 1220
    assert float(result["return"]) == pytest.approx(0.21)
    assert float(result["SPY"]) == pytest.approx(0.02)
    assert float(result["benchmark_values"]["SPY"]["value"]) == pytest.approx(
        1020 + 220 * 102 / 101
    )
    assert D(result["cash"]) == 0


def test_recent_period_rebases_returns_without_resetting_wealth(db_client, inferred):
    aid, _ = inferred
    full = estimated(db_client, aid)
    recent = estimated(db_client, aid, start=str(DAYS[1]), baseline="recorded")
    assert recent["value"] == full["value"]
    assert recent["benchmark_values"] == full["benchmark_values"]
    assert recent["funding_estimate"] == full["funding_estimate"]
    assert D(recent["series"][0]["portfolio"]) == 0
    assert D(recent["series"][0]["SPY"]) == 0
    assert float(recent["SPY"]) == pytest.approx(102 / 101 - 1)
    assert recent["cagr"]["SPY"] is None


@pytest.mark.parametrize("kind", ["deposit", "withdrawal", "income", "expense"])
def test_unsupported_cash_records_are_checked_before_displayed_period(
    db_client,
    inferred,
    database,
    kind,
):
    aid, _ = inferred
    enlarge_placeholder(database, aid, 1001)
    assert cash(db_client, aid, kind, "1", day=str(DAYS[0])).status_code == 201
    r = stock_report(
        db_client, aid, benchmark_mode="funded_hold", start=str(DAYS[1]), baseline="recorded"
    )
    assert r.status_code == 422 and "recorded cash" in r.json()["detail"]


def test_known_dividend_with_future_payment_is_not_silently_ignored(db_client, inferred):
    aid, _ = inferred
    assert dividend(db_client, aid, pay="2026-01-07").status_code == 201
    r = stock_report(db_client, aid, benchmark_mode="funded_hold")
    assert r.status_code == 422 and "recorded cash" in r.json()["detail"]


def test_post_close_deposit_does_not_enter_the_estimate(db_client, inferred):
    aid, _ = inferred
    assert cash(db_client, aid, amount="200", day="2026-01-07").status_code == 201
    result = estimated(db_client, aid, end="2026-01-07")
    assert result["end"] == str(DAYS[-1])
    assert D(result["funding_estimate"]["fresh_cash"]) == 1000


def test_post_close_unpriced_security_is_not_fetched(db_client, inferred):
    aid, data = inferred
    assert cash(db_client, aid, amount="100", day="2026-01-07").status_code == 201
    assert (
        trade(
            db_client,
            aid,
            quantity="1",
            ticker="UNPRICED",
            exchange="NYSE",
            effective_date="2026-01-07",
        ).status_code
        == 201
    )
    # The provider fixture deliberately has no UNPRICED symbol or Jan-7 session.
    result = estimated(db_client, aid, end="2026-01-07")
    assert result["end"] == str(DAYS[-1])
    assert D(result["funding_estimate"]["fresh_cash"]) == 1000


def test_stale_quotes_cannot_truncate_the_funding_history(db_client, inferred):
    aid, _ = inferred
    response = stock_report(db_client, aid, benchmark_mode="funded_hold", end="2026-01-12")
    assert response.status_code == 422
    assert "stale" in response.json()["detail"]


def test_rejects_exclusions_real_opening_balances_and_changed_placeholders(
    db_client,
    portfolio,
    database,
):
    aid, _ = portfolio
    assert stock_report(db_client, aid, benchmark_mode="funded_hold").status_code == 422
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "funding_status": "inferred",
            "opening_cash": "999",
        }
        session.commit()
    assert stock_report(db_client, aid, benchmark_mode="funded_hold").status_code == 422
    sid = ledger(db_client, aid)["holdings"][0]["security"]["id"]
    r = stock_report(db_client, aid, benchmark_mode="funded_hold", exclude_security_ids=[sid])
    assert r.status_code == 422 and "exclusions" in r.json()["detail"]
