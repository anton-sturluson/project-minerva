from datetime import date, timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from helpers import trade

from investor_platform.domain import Currency
from investor_platform.market_data import types as market_types
from investor_platform.market_data import yahoo as market_yahoo
from investor_platform.market_data.types import History
from investor_platform.performance import valuation as valuation


@pytest.mark.parametrize("failure", [None, "identity", "split"])
def test_fallback_keeps_as_traded_prices_and_identity_split_guards(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    """A provider outage can recover without bypassing listing or share-unit checks."""
    from investor_platform.market_data import tiingo as tiingo

    aid: str = portfolio[0]
    end: date = date(2026, 1, 30)
    monkeypatch.setattr(valuation, "completed_market_date", lambda: end)
    monkeypatch.setenv("TIINGO_API_KEY", "synthetic-test-key")

    def unavailable(*args: str, **kwargs: str) -> History:
        """Represent an unavailable primary quote provider."""
        raise OSError("offline")

    def provider(path: str, key: str) -> dict[str, str] | list[dict[str, str]]:
        """Return realistic fallback data with distinct adjusted and actual closes."""
        if "/prices?" not in path:
            return {"ticker": "AAA", "exchangeCode": "NASDAQ" if failure == "identity" else "NYSE"}
        return [
            {
                "date": end.isoformat(),
                "close": "50",
                "adjClose": "25",
                "divCash": "0",
                "splitFactor": "2" if failure == "split" else "1",
            }
        ]

    monkeypatch.setattr(market_yahoo, "history", unavailable)
    monkeypatch.setattr(tiingo, "get", provider)
    result: dict = db_client.get(f"/api/accounts/{aid}/valuation").json()
    if failure:
        assert not result["complete"]
        assert result["holdings"][0]["value"] is None
        assert result["holdings"][0]["price_error"]
        assert result["holdings"][0]["annualized_unrealized_return"] is None
        assert (
            result["holdings"][0]["annualized_unrealized_return_reason"]
            == "Market value unavailable"
        )
    else:
        assert result["complete"]
        assert D(result["holdings"][0]["close"]) == 50
        assert D(result["holdings"][0]["value"]) == 500


def test_old_held_split_withholds_values_liquidation_and_collection(
    db_client, database, portfolio, monkeypatch
):
    from helpers import ledger

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

    monkeypatch.setattr(market_yahoo, "history", quote)
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

    from investor_platform.market_data.price_refresh import collect_account
    from investor_platform.models import Account

    with Session(database) as session:
        collection = collect_account(
            session, session.get(Account, UUID(aid)), end, datetime.now(UTC)
        )
    assert {
        "symbol": "AAA",
        "scope": "current",
        "reason": "price_unavailable",
    } in collection.failures


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
        assert start <= date(2026, 1, 20)
        return History({end: D(50)}, {}, splits={split}, exchange="NYQ")

    monkeypatch.setattr(market_yahoo, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert result["complete"]
    assert D(result["holdings"][0]["value"]) == 500
    assert D(result["holdings"][0]["unrealized_pnl"]) == 0


def test_pre_split_previous_close_cannot_value_a_post_split_purchase(db_client, monkeypatch):
    from helpers import cash

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
        market_yahoo,
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
    for index in range(market_types.MAX_SECURITIES):
        symbol = f"OLD{index}"
        assert trade(db_client, aid, "opening_position", "1", ticker=symbol).status_code == 201
        assert trade(db_client, aid, "sell", "1", "1", ticker=symbol).status_code == 201
    calls = []

    def quote(symbol, start, end):
        calls.append(symbol)
        return History({end: D(120)}, {end: D(120)}, exchange="NYQ")

    monkeypatch.setattr(market_yahoo, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert calls == ["AAA"]  # Closed/delisted holdings need no quotes for today's valuation.
    assert result["complete"] and D(result["value"]) == D(1200 + market_types.MAX_SECURITIES)
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

    monkeypatch.setattr(market_yahoo, "history", quote)
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
    db_client, portfolio, monkeypatch, exchange, suffix, currency, provider, reset_market_cache
):
    from helpers import ledger

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

    monkeypatch.setattr(market_yahoo, "history", quote)
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert D(result["value"]) == 1214
    assert D(result["holdings"][1]["close"]) == 7
    assert D(result["holdings"][1]["unrealized_pnl"]) == 4
    assert ledger(db_client, aid) == before
    reset_market_cache()
    gap = True
    result = db_client.get(f"/api/accounts/{aid}/valuation").json()
    assert result["value"] is None and result["holdings"][1]["price_error"]


def test_hypothetical_closes_finish_whole_episodes_and_leave_records_unchanged(
    db_client, portfolio, monkeypatch, reset_market_cache
):
    from helpers import ledger

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

    monkeypatch.setattr(market_yahoo, "history", quote)
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

    reset_market_cache()
    monkeypatch.setattr(market_yahoo, "history", unavailable)
    response = db_client.get(url)
    assert response.status_code == 503 and "Latest prices unavailable" in response.json()["detail"]
    assert ledger(db_client, aid) == before


@pytest.mark.parametrize("position", ["single", "staggered", "partial_sale"])
@pytest.mark.parametrize("growth", ["1.1", "0.8"])
def test_annualized_unrealized_return_prices_only_remaining_purchase_costs(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch, position: str, growth: str
) -> None:
    from helpers import cash, ledger

    account = db_client.post(
        "/api/accounts", json={"name": "Synthetic annualized holding", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, account, "opening_cash", "10000", day="2019-01-02").status_code == 201
    assert (
        trade(
            db_client,
            account,
            ticker="AAA",
            exchange="NYSE",
            quantity="2",
            price="100",
            fees="20",
            effective_date="2020-01-02",
        ).status_code
        == 201
    )
    costs = [(D(220), D(4))]
    quantity = D(2)
    if position != "single":
        assert (
            trade(
                db_client,
                account,
                ticker="AAA",
                exchange="NYSE",
                quantity="1",
                price="200",
                effective_date="2022-01-02",
            ).status_code
            == 201
        )
        costs.append((D(200), D(730) / D("365.25")))
        quantity += 1
    if position == "partial_sale":
        assert (
            trade(
                db_client,
                account,
                kind="sell",
                ticker="AAA",
                exchange="NYSE",
                quantity="1",
                price="900",
                effective_date="2023-01-02",
            ).status_code
            == 201
        )
        costs[0] = (D(110), D(4))
        quantity -= 1
    # Construct a terminal value from a known annual growth rate, independently
    # of the implementation's inverse solver. Sale proceeds are deliberately unrelated.
    value = sum((cost * D(growth) ** years for cost, years in costs), D(0))
    quote = date(2024, 1, 2)
    history = History({quote: value / quantity}, {quote: value / quantity})
    history.exchange = "NYQ"
    monkeypatch.setattr(market_yahoo, "history", lambda *args, **kwargs: history)
    monkeypatch.setattr(valuation, "completed_market_date", lambda: quote + timedelta(days=1))
    before = ledger(db_client, account)
    response = db_client.get(f"/api/accounts/{account}/valuation")
    assert response.status_code == 200
    row = response.json()["holdings"][0]
    assert abs(D(row["annualized_unrealized_return"]) - (D(growth) - 1)) < D("1e-12")
    assert row["annualized_unrealized_return_reason"] is None
    basis = sum((cost for cost, _ in costs), D(0))
    assert D(row["basis"]) == basis
    assert abs(D(row["unrealized_pnl"]) - (value - basis)) < D("1e-20")
    assert row["quote_date"] == quote.isoformat()
    assert ledger(db_client, account) == before
    assert "lots" not in before["holdings"][0]


@pytest.mark.parametrize(
    "case,expected,reason",
    [
        ("short", None, "Less than one year"),
        ("future", None, "Quote precedes"),
        ("opening", None, "Original purchase date"),
        ("unknown_basis", None, "Positive purchase cost"),
        ("zero_basis", None, "Positive purchase cost"),
        ("sold_old", None, "Less than one year"),
        ("sold_import", "0", None),
        ("same_day", "0", None),
        ("same_day_loss", "-1", None),
        ("impossible", None, "No finite"),
    ],
)
def test_annualization_availability_preserves_market_value_and_pnl(
    db_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected: str | None,
    reason: str | None,
) -> None:
    from helpers import cash, ledger

    account = db_client.post(
        "/api/accounts", json={"name": "Synthetic return boundaries", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, account, "opening_cash", "10000", day="2019-01-02").status_code == 201
    imported = case in {"opening", "unknown_basis", "sold_import", "zero_basis"}
    first_date = (
        "2023-02-01" if case == "short" else "2024-01-03" if case == "future" else "2020-01-02"
    )
    options = (
        {"cost_basis": None if case == "unknown_basis" else "0" if case == "zero_basis" else "100"}
        if imported
        else {}
    )
    assert (
        trade(
            db_client,
            account,
            kind="opening_position" if imported else "buy",
            ticker="AAA",
            exchange="NYSE",
            quantity="1",
            price="0" if case == "zero_basis" else "100",
            effective_date=first_date,
            **options,
        ).status_code
        == 201
    )
    if case in {"sold_old", "sold_import"}:
        assert (
            trade(
                db_client,
                account,
                kind="sell",
                ticker="AAA",
                exchange="NYSE",
                quantity="1",
                effective_date="2021-01-02",
            ).status_code
            == 201
        )
        assert (
            trade(
                db_client,
                account,
                ticker="AAA",
                exchange="NYSE",
                quantity="1",
                effective_date="2023-02-01" if case == "sold_old" else "2022-01-02",
            ).status_code
            == 201
        )
    price = D(100)
    if case in {"same_day", "same_day_loss", "impossible"}:
        assert (
            trade(
                db_client,
                account,
                ticker="AAA",
                exchange="NYSE",
                quantity="1",
                effective_date="2024-01-02",
            ).status_code
            == 201
        )
        price = D(100) if case == "same_day" else D(50) if case == "same_day_loss" else D(25)
    quote = date(2024, 1, 2)
    history = History({quote: price}, {quote: price})
    history.exchange = "NYQ"
    monkeypatch.setattr(market_yahoo, "history", lambda *args, **kwargs: history)
    monkeypatch.setattr(valuation, "completed_market_date", lambda: date(2024, 1, 3))
    before = ledger(db_client, account)
    response = db_client.get(f"/api/accounts/{account}/valuation")
    assert response.status_code == 200
    row = response.json()["holdings"][0]
    assert D(row["value"]) == D(row["quantity"]) * price
    assert row["price_error"] is None
    if expected is None:
        assert row["annualized_unrealized_return"] is None
        assert reason in row["annualized_unrealized_return_reason"]
    else:
        assert abs(D(row["annualized_unrealized_return"]) - D(expected)) < D("1e-12")
        assert row["annualized_unrealized_return_reason"] is None
    assert ledger(db_client, account) == before


@pytest.mark.parametrize(
    "free_date,paid_date,reason",
    [
        (date(2024, 1, 3), date(2020, 1, 2), "Quote precedes a remaining purchase"),
        (date(2020, 1, 2), date(2023, 2, 1), "Less than one year of holding history"),
    ],
)
def test_zero_cost_lots_keep_date_validity_without_extending_paid_holding_age(
    free_date: date, paid_date: date, reason: str
) -> None:
    from investor_platform.ledger.accounting import Lot
    from investor_platform.performance.unrealized_return import annualized_unrealized_return

    # FIFO allocations can leave a zero-cost remainder; it has no invested capital,
    # but a quote still cannot precede its known acquisition.
    lots = [Lot(D(1), D(0), free_date), Lot(D(1), D(100), paid_date)]
    assert annualized_unrealized_return(lots, D(200), date(2024, 1, 2)) == (None, reason)
