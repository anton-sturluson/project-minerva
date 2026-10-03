from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_ledger import cash, ledger

from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.models import Security


@pytest.fixture
def account_id(db_client):
    account = db_client.post(
        "/api/account", json={"name": "Trade fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, account, "opening_cash", "10000")
    return account


def trade(client, account, kind="buy", quantity="10", price="100", **extra):
    data = {
        "kind": kind,
        "quantity": quantity,
        "price": price,
        "fees": "0",
        "ticker": "DEMO",
        "exchange": "TEST",
        "currency": "USD",
        "effective_date": "2026-01-02",
        "request_key": str(uuid4()),
        **extra,
    }
    if kind == "opening_position":
        data["price"] = None
    return client.post(f"/api/accounts/{account}/trades", json=data)


def test_fifo_open_buy_partial_sell_full_close(db_client, account_id, database):
    assert (
        trade(db_client, account_id, "opening_position", "10", cost_basis="800").status_code == 201
    )
    assert Decimal(ledger(db_client, account_id)["balance"]) == 10000
    assert trade(db_client, account_id, quantity="5", fees="2").status_code == 201
    state = ledger(db_client, account_id)
    assert Decimal(state["balance"]) == 9498
    assert Decimal(state["holdings"][0]["cost_basis"]) == 1302
    first_sell = trade(db_client, account_id, "sell", "12", "120", fees="3")
    assert first_sell.status_code == 201
    state = ledger(db_client, account_id)
    assert Decimal(state["balance"]) == 10935
    assert Decimal(state["holdings"][0]["quantity"]) == 3
    assert Decimal(state["holdings"][0]["cost_basis"]) == Decimal("301.2")
    assert Decimal(state["entries"][-1]["realized_pnl"]) == Decimal("436.2")
    assert trade(db_client, account_id, "sell", "3", "110", fees="1").status_code == 201
    state = ledger(db_client, account_id)
    assert state["holdings"] == []
    assert Decimal(state["balance"]) == 11264
    assert Decimal(state["entries"][-1]["realized_pnl"]) == Decimal("27.8")


def test_unknown_basis_is_not_fabricated(db_client, account_id):
    trade(db_client, account_id, "opening_position", "3")
    assert ledger(db_client, account_id)["holdings"][0]["cost_basis"] is None
    trade(db_client, account_id, quantity="2", price="10")
    trade(db_client, account_id, "sell", "4", "20")
    state = ledger(db_client, account_id)
    assert state["entries"][-1]["realized_pnl"] is None
    assert Decimal(state["holdings"][0]["quantity"]) == 1
    assert Decimal(state["holdings"][0]["cost_basis"]) == 10
    trade(db_client, account_id, "sell", "1", "20")
    assert Decimal(ledger(db_client, account_id)["entries"][-1]["realized_pnl"]) == 10


def test_invalid_trades_do_not_create_security_or_cash(db_client, account_id, database):
    before = ledger(db_client, account_id)
    assert trade(db_client, account_id, "sell", "1").status_code == 409
    assert trade(db_client, account_id, quantity="101").status_code == 409
    assert ledger(db_client, account_id) == before
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Security)) == 0


def test_backdating_checks_later_shares_and_cash(db_client, account_id):
    trade(db_client, account_id, "buy", "10", effective_date="2026-01-10")
    trade(db_client, account_id, "sell", "8", effective_date="2026-01-20")
    before = ledger(db_client, account_id)
    # Today there are 2 shares; inserting this sale makes the later sale invalid.
    assert trade(db_client, account_id, "sell", "3", effective_date="2026-01-15").status_code == 409
    assert trade(db_client, account_id, "sell", "1", effective_date="2026-01-05").status_code == 409
    assert trade(db_client, account_id, "opening_position", "1").status_code == 409
    assert ledger(db_client, account_id) == before
    cash(db_client, account_id, "withdrawal", "9000", "2026-01-11")
    cash(db_client, account_id, "deposit", "10000", "2026-01-21")
    before = ledger(db_client, account_id)
    assert trade(db_client, account_id, "buy", "1", effective_date="2026-01-11").status_code == 409
    assert ledger(db_client, account_id) == before


def test_opening_position_cannot_be_retroactively_preceded(db_client, account_id):
    trade(db_client, account_id, "opening_position", "2", effective_date="2026-01-10")
    assert trade(db_client, account_id, effective_date="2026-01-05").status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"quantity": "0"},
        {"quantity": "0.000000001"},
        {"price": "0"},
        {"price": None},
        {"price": "NaN"},
        {"fees": "-1"},
        {"currency": "EUR"},
        {"kind": "split"},
        {"ticker": "INVALID SYMBOL"},
        {"cost_basis": "10"},
        {"amount": "10"},
        {"effective_date": "2999-01-01"},
    ],
)
def test_invalid_trade_inputs(db_client, account_id, extra):
    assert trade(db_client, account_id, **extra).status_code == 422
    assert ledger(db_client, account_id)["holdings"] == []


def test_opening_fields_and_sale_fees(db_client, account_id):
    assert trade(db_client, account_id, "opening_position", fees="1").status_code == 422
    trade(db_client, account_id, "opening_position", "2")
    assert trade(db_client, account_id, "sell", "1", "1", fees="2").status_code == 422


def test_trade_retry_and_owner_isolation(db_client, account_id):
    key = str(uuid4())
    first = trade(
        db_client, account_id, quantity="1.00", request_key=key, ticker="demo", exchange="test"
    )
    assert first.status_code == 201
    assert trade(db_client, account_id, quantity="1", request_key=key).json() == first.json()
    assert trade(db_client, account_id, quantity="2", request_key=key).status_code == 409
    app.dependency_overrides[get_actor] = lambda: Actor(uuid4(), uuid4())
    assert trade(db_client, account_id).status_code == 404


def test_concurrent_oversells(db_client, account_id):
    trade(db_client, account_id, "opening_position", "10")
    barrier = Barrier(2)

    def sell(_):
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            barrier.wait()
            return trade(client, account_id, "sell", "8").status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(sell, range(2))) == [201, 409]
    assert Decimal(ledger(db_client, account_id)["holdings"][0]["quantity"]) == 2


def test_concurrent_buy_and_withdraw_share_one_cash_lock(db_client, account_id):
    barrier = Barrier(2)

    def spend(operation):
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            barrier.wait()
            return (
                trade(client, account_id, quantity="80")
                if operation == 0
                else cash(client, account_id, "withdrawal", "8000")
            ).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(spend, range(2))) == [201, 409]
    assert Decimal(ledger(db_client, account_id)["balance"]) == 2000


def test_fractional_fifo_residual_and_cash_precision(db_client, account_id):
    trade(db_client, account_id, quantity="3", price="0.33333333", fees="0.00000001")
    for _ in range(3):
        assert trade(db_client, account_id, "sell", "1", "1").status_code == 201
    state = ledger(db_client, account_id)
    assert state["holdings"] == []
    assert sum(
        Decimal(e["realized_pnl"]) for e in state["entries"] if e["kind"] == "sell"
    ) == Decimal("2.00000000")
    response = trade(db_client, account_id, quantity="0.00000001", price="0.00000001")
    assert response.status_code == 201
    assert Decimal(response.json()["amount"]) == Decimal("0.0000000000000001")
    assert Decimal(ledger(db_client, account_id)["balance"]) == Decimal("10001.9999999999999999")


def test_large_products_keep_more_than_28_digits(db_client, account_id):
    quantity = "999999999999.99999999"
    trade(db_client, account_id, "opening_position", quantity, cost_basis="0")
    response = trade(db_client, account_id, "sell", quantity, quantity)
    assert response.status_code == 201
    assert response.json()["amount"] == "999999999999999999980000.0000000000000001"
    assert ledger(db_client, account_id)["balance"] == "999999999999999999990000.0000000000000001"


def test_concurrent_trade_retries_do_not_duplicate_shares(db_client, account_id):
    barrier = Barrier(2)
    key = str(uuid4())

    def buy(_):
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            barrier.wait()
            return trade(client, account_id, request_key=key).json()["id"]

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(buy, range(2)))
    assert results[0] == results[1]
    state = ledger(db_client, account_id)
    assert Decimal(state["holdings"][0]["quantity"]) == 10
    assert Decimal(state["balance"]) == 9000
