from datetime import date
from decimal import Decimal as D
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import DAYS, cash, dividend, ledger, stock_report, trade
from httpx import Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from investor_platform.domain import EntryKind
from investor_platform.financial import Record
from investor_platform.market import History
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
    response = stock_report(
        client, aid, benchmark_mode="funded_hold", **{"scope": "account", **extra}
    )
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


@pytest.mark.parametrize("kind", ["withdrawal", "income", "expense"])
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
    r = stock_report(
        db_client, aid, scope="account", benchmark_mode="funded_hold", exclude_security_ids=[sid]
    )
    assert r.status_code == 422 and "exclusions" in r.json()["detail"]


@pytest.mark.parametrize("deposit", ["1000", "400"])
def test_recorded_deposit_covers_buys_before_inferred_shortages(
    db_client: TestClient, inferred: tuple[str, dict[str, History]], deposit: str
) -> None:
    """Known deposits count once; only the uncovered initial purchase needs inferred cash."""
    aid: str = inferred[0]
    assert cash(db_client, aid, amount=deposit, day=str(DAYS[0])).status_code == 201
    before: Record = ledger(db_client, aid)
    result: Record = estimated(db_client, aid)
    assert D(result["funding_estimate"]["fresh_cash"]) == 1000
    assert D(result["funding_estimate"]["recorded_deposits"]) == D(deposit)
    assert D(result["funding_estimate"]["inferred_cash"]) == 1000 - D(deposit)
    assert D(result["funding_estimate"]["capital"]) == 1000
    assert D(result["cash"]) == 0 and D(result["value"]) == 1210
    assert D(result["benchmark_values"]["SPY"]["value"]) == 1020
    assert ledger(db_client, aid) == before


def test_later_deposit_is_new_index_money_once_and_cannot_fund_earlier_buys(
    db_client: TestClient, inferred: tuple[str, dict[str, History]]
) -> None:
    """A later deposit adds cash and benchmark units without replacing earlier inferred capital."""
    aid: str = inferred[0]
    assert cash(db_client, aid, amount="200", day=str(DAYS[1])).status_code == 201
    result: Record = estimated(db_client, aid)
    assert D(result["funding_estimate"]["inferred_cash"]) == 1000
    assert D(result["funding_estimate"]["recorded_deposits"]) == 200
    assert D(result["funding_estimate"]["fresh_cash"]) == 1200
    assert D(result["cash"]) == 200 and D(result["value"]) == 1410
    assert float(result["benchmark_values"]["SPY"]["value"]) == pytest.approx(
        1020 + 200 * 102 / 101
    )


def test_deposit_before_first_trade_starts_benchmark_before_stock_purchase(
    db_client: TestClient, inferred: tuple[str, dict[str, History]], database: Engine
) -> None:
    """A known early deposit establishes the estimate before the first stock exposure."""
    aid: str
    data: dict[str, History]
    aid, data = inferred
    prior: date = date(2025, 12, 31)
    session: Session
    with Session(database) as session:
        opening: LedgerEntry = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.account_id == UUID(aid), LedgerEntry.kind == EntryKind.OPENING_CASH
            )
        )
        opening.effective_date = date(2025, 12, 30)
        session.commit()
    symbol: str
    for symbol in ("SPY", "QQQ"):
        data[symbol].close[prior] = D(90)
        data[symbol].adjusted[prior] = D(90)
    assert cash(db_client, aid, amount="1000", day=str(prior)).status_code == 201
    result: Record = estimated(db_client, aid, start=str(prior))
    assert result["start"] == str(prior)
    assert D(result["series"][0]["cash"]) == 1000
    assert D(result["series"][0]["value"]) == 1000
    assert D(result["funding_estimate"]["inferred_cash"]) == 0
    assert float(result["benchmark_values"]["SPY"]["value"]) == pytest.approx(1000 * 102 / 90)


@pytest.mark.parametrize("scope", ["account", "stocks"])
@pytest.mark.parametrize("recent", [False, True])
def test_benchmark_choice_preserves_portfolio_and_ledger(
    db_client: TestClient,
    inferred: tuple[str, dict[str, History]],
    scope: str,
    recent: bool,
) -> None:
    """Index choices preserve portfolio wealth, returns, dates, scope and recorded data."""
    aid: str = inferred[0]
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
    assert cash(db_client, aid, amount="200", day=str(DAYS[1])).status_code == 201
    before: Record = ledger(db_client, aid)
    options: dict[str, str] = {
        "scope": scope,
        "start": str(DAYS[1] if recent else DAYS[0]),
        "baseline": "recorded" if recent else "history",
    }
    regular_response: Response = stock_report(db_client, aid, benchmark_mode="buy_hold", **options)
    matched_response: Response = stock_report(
        db_client, aid, benchmark_mode="funded_hold", **options
    )
    assert regular_response.status_code == matched_response.status_code == 200
    regular: Record = regular_response.json()
    matched: Record = matched_response.json()
    field: str
    for field in ("scope", "start", "end", "value", "cash", "return", "holdings", "attribution"):
        assert regular[field] == matched[field], field
    assert regular["cagr"]["portfolio"] == matched["cagr"]["portfolio"]
    assert [
        {field: point[field] for field in ("date", "portfolio", "value", "cash", "receivables")}
        for point in regular["series"]
    ] == [
        {field: point[field] for field in ("date", "portfolio", "value", "cash", "receivables")}
        for point in matched["series"]
    ]
    assert "benchmark_values" not in regular
    assert D(matched["benchmark_values"]["SPY"]["value"]) > 1200
    assert D(matched["funding_estimate"]["recorded_deposits"]) == 200
    if scope == "account":
        assert regular["funding_estimate"] == matched["funding_estimate"]
    assert ledger(db_client, aid) == before


def test_stock_benchmark_switch_keeps_days_before_first_trade(
    db_client: TestClient, inferred: tuple[str, dict[str, History]], database: Engine
) -> None:
    """An earlier placeholder must not shift or truncate the stock return series."""
    aid: str = inferred[0]
    data: dict[str, History] = inferred[1]
    prior: date = date(2025, 12, 31)
    session: Session
    with Session(database) as session:
        opening: LedgerEntry = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.account_id == UUID(aid), LedgerEntry.kind == EntryKind.OPENING_CASH
            )
        )
        opening.effective_date = prior
        session.commit()
    symbol: str
    for symbol in ("SPY", "QQQ"):
        data[symbol].close[prior] = D(90)
        data[symbol].adjusted[prior] = D(90)
    regular: Record = stock_report(db_client, aid, start=str(prior)).json()
    matched: Record = estimated(db_client, aid, scope="stocks", start=str(prior))
    assert [(point["date"], point["portfolio"]) for point in regular["series"]] == [
        (point["date"], point["portfolio"]) for point in matched["series"]
    ]
    assert matched["start"] == str(prior)
    assert D(matched["series"][0]["SPY"]) == 0


@pytest.mark.parametrize("mode", ["buy_hold", "funded_hold"])
def test_modeled_account_cash_guards_apply_to_both_index_choices(
    db_client: TestClient, inferred: tuple[str, dict[str, History]], database: Engine, mode: str
) -> None:
    """Unsupported cash history cannot silently select a different account return model."""
    aid: str = inferred[0]
    enlarge_placeholder(database, aid, 1001)
    assert cash(db_client, aid, "withdrawal", "1", day=str(DAYS[0])).status_code == 201
    response: Response = stock_report(db_client, aid, scope="account", benchmark_mode=mode)
    assert response.status_code == 422
    assert "recorded cash" in response.json()["detail"]


def test_stock_exclusions_keep_the_same_scenario_when_indexes_change(
    db_client: TestClient, inferred: tuple[str, dict[str, History]], database: Engine
) -> None:
    """Matched index funding follows original trades while stock exclusions retain their returns."""
    aid: str = inferred[0]
    data: dict[str, History] = inferred[1]
    data["BBB"] = data["AAA"]
    enlarge_placeholder(database, aid, 1200)
    assert trade(db_client, aid, quantity="2", ticker="BBB", exchange="NYSE").status_code == 201
    holdings: list[Record] = ledger(db_client, aid)["holdings"]
    excluded: list[str] = [
        holding["security"]["id"] for holding in holdings if holding["security"]["ticker"] == "BBB"
    ]
    regular: Record = stock_report(db_client, aid, exclude_security_ids=excluded).json()
    matched: Record = estimated(db_client, aid, scope="stocks", exclude_security_ids=excluded)
    assert matched["scenario_error"] is None
    assert regular["scenario"]["return"] == matched["scenario"]["return"]
    assert regular["scenario"]["value"] == matched["scenario"]["value"]
    assert matched["scenario"]["benchmark_values"] == matched["benchmark_values"]
