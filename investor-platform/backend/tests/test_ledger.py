from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.models import LedgerEntry


@pytest.fixture
def account_id(db_client):
    return db_client.post(
        "/api/accounts", json={"name": "Ledger fixture", "base_currency": "USD"}
    ).json()["id"]


def cash(client, account_id, kind="deposit", amount="100", day="2026-01-01", **extra):
    return client.post(
        f"/api/accounts/{account_id}/cash",
        json={
            "request_key": str(uuid4()),
            "kind": kind,
            "amount": amount,
            "effective_date": day,
            "currency": "USD",
            **extra,
        },
    )


def ledger(client, account_id):
    return client.get(f"/api/accounts/{account_id}/ledger").json()


def test_exact_cash_and_audit(db_client, account_id):
    assert cash(db_client, account_id, "opening_cash", "100.10").status_code == 201
    assert cash(db_client, account_id, amount="0.20").status_code == 201
    assert cash(db_client, account_id, "withdrawal", "25.05").status_code == 201
    state = ledger(db_client, account_id)
    assert Decimal(state["balance"]) == Decimal("75.25")
    assert len(state["entries"]) == 3
    assert all(e["created_at"] and e["created_by"] for e in state["entries"])
    assert [e["id"] for e in state["entries"]] == sorted(e["id"] for e in state["entries"])


def test_retry_identity_and_conflict(db_client, account_id):
    key = str(uuid4())
    first = cash(db_client, account_id, amount="1.00", request_key=key)
    assert cash(db_client, account_id, amount="1", request_key=key).json() == first.json()
    assert cash(db_client, account_id, amount="2", request_key=key).status_code == 409
    assert len(ledger(db_client, account_id)["entries"]) == 1


def test_full_history_is_validated_and_rejection_is_atomic(db_client, account_id):
    cash(db_client, account_id, "opening_cash", "100", "2026-01-01")
    cash(db_client, account_id, "withdrawal", "90", "2026-01-10")
    cash(db_client, account_id, "deposit", "100", "2026-01-20")
    # Final balance could afford 20, but the January 10 balance could not.
    assert cash(db_client, account_id, "withdrawal", "20", "2026-01-05").status_code == 409
    assert cash(db_client, account_id, "deposit", "5", "2025-12-31").status_code == 409
    assert cash(db_client, account_id, "opening_cash", "0").status_code == 409
    state = ledger(db_client, account_id)
    assert len(state["entries"]) == 3
    assert Decimal(state["balance"]) == 110


@pytest.mark.parametrize(
    "extra",
    [
        {"kind": "income", "amount": "0"},
        {"kind": "opening_cash", "amount": "-1"},
        {"amount": "0"},
        {"amount": "NaN"},
        {"amount": "Infinity"},
        {"amount": "0.000000001"},
        {"kind": "dividend"},
        {"currency": "EUR"},
        {"effective_date": (datetime.now(UTC).date() + timedelta(days=1)).isoformat()},
    ],
)
def test_invalid_entries(db_client, account_id, extra):
    assert cash(db_client, account_id, **extra).status_code == 422
    assert ledger(db_client, account_id)["entries"] == []


def test_cash_ownership(db_client, account_id):
    app.dependency_overrides[get_actor] = lambda: Actor(uuid4(), uuid4())
    assert cash(db_client, account_id).status_code == 404
    assert db_client.get(f"/api/accounts/{account_id}/ledger").status_code == 404


def test_concurrent_withdrawals_cannot_overdraw(db_client, account_id, database):
    cash(db_client, account_id, "opening_cash", "100")
    barrier = Barrier(2)

    def withdraw(_):
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            barrier.wait()
            return cash(client, account_id, "withdrawal", "80").status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(withdraw, range(2))) == [201, 409]
    assert Decimal(ledger(db_client, account_id)["balance"]) == 20
    with Session(database) as session:
        assert len(list(session.scalars(select(LedgerEntry)))) == 2


def test_concurrent_retries_only_write_once(db_client, account_id):
    barrier = Barrier(2)
    key = str(uuid4())

    def deposit(_):
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            barrier.wait()
            return cash(client, account_id, request_key=key).json()["id"]

    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(deposit, range(2)))
    assert ids[0] == ids[1]
    assert len(ledger(db_client, account_id)["entries"]) == 1
