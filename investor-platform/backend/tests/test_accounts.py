from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.models import Account, Owner, Workspace

DATA = {"name": "Patient capital", "base_currency": "USD"}


def test_account_round_trip_and_retry(db_client, database):
    assert db_client.get("/api/accounts").json() == []
    first = db_client.post("/api/accounts", json=DATA)
    assert first.status_code == 201
    assert db_client.post("/api/accounts", json=DATA).json() == first.json()
    assert db_client.get("/api/accounts").json() == [first.json()]
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Account)) == 1
    assert db_client.post("/api/accounts", json={**DATA, "name": "Other"}).status_code == 201
    assert len(db_client.get("/api/accounts").json()) == 2
    assert db_client.post("/api/accounts", json={**DATA, "base_currency": "CAD"}).status_code == 409


@pytest.mark.parametrize(
    "data",
    [
        {**DATA, "name": " "},
        {**DATA, "base_currency": "XXX"},
        {**DATA, "workspace_id": str(uuid4())},
    ],
)
def test_invalid_account(db_client, data):
    assert db_client.post("/api/accounts", json=data).status_code == 422


def test_cross_workspace_reads_and_writes(db_client, database):
    db_client.post("/api/accounts", json=DATA)
    owner, workspace = uuid4(), uuid4()
    with Session(database) as session:
        session.add(Owner(id=owner))
        session.flush()
        session.add(Workspace(id=workspace, owner_id=owner))
        session.commit()
    app.dependency_overrides[get_actor] = lambda: Actor(owner, workspace)
    assert db_client.get("/api/accounts").json() == []
    foreign = db_client.post("/api/accounts", json={**DATA, "name": "Foreign"})
    assert foreign.status_code == 201
    app.dependency_overrides[get_actor] = lambda: Actor(owner, uuid4())
    assert db_client.post("/api/accounts", json=DATA).status_code == 403
    app.dependency_overrides.clear()
    assert db_client.get("/api/accounts").json()[0]["name"] == DATA["name"]


def test_portfolios_share_instruments_but_isolate_cash_trades_and_corrections(db_client):
    from decimal import Decimal

    from helpers import cash, ledger, trade

    first = db_client.post("/api/accounts", json=DATA).json()["id"]
    second = db_client.post("/api/accounts", json={**DATA, "name": "Index account"}).json()["id"]
    cash(db_client, first, "opening_cash", "1000")
    cash(db_client, second, "opening_cash", "100")
    trade(db_client, first, quantity="2", price="100", ticker="AAA")
    before = ledger(db_client, first)
    purchase = trade(db_client, second, quantity="1", price="50", ticker="AAA").json()
    other = ledger(db_client, second)
    assert before["holdings"][0]["security"]["id"] == other["holdings"][0]["security"]["id"]
    assert Decimal(before["balance"]) == 800
    assert Decimal(other["balance"]) == 50
    assert ledger(db_client, first) == before
    rejected = db_client.post(
        f"/api/accounts/{first}/entries/{purchase['id']}/correction?preview=true",
        json={"request_key": str(uuid4()), "reason": "Wrong portfolio", "replacement": None},
    )
    assert rejected.status_code == 409
    assert ledger(db_client, second) == other
