from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.models import Account, Owner, Workspace

DATA = {"name": "Patient capital", "base_currency": "USD"}


def test_account_round_trip_and_retry(db_client, database):
    assert db_client.get("/api/account").json() is None
    first = db_client.post("/api/account", json=DATA)
    assert first.status_code == 201
    assert db_client.post("/api/account", json=DATA).json() == first.json()
    assert db_client.get("/api/account").json() == first.json()
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Account)) == 1
        assert session.scalar(select(func.count()).select_from(Owner)) == 1
    database.dispose()  # Reconnect without an in-memory account cache.
    assert db_client.get("/api/account").json()["name"] == DATA["name"]
    assert db_client.post("/api/account", json={**DATA, "name": "Other"}).status_code == 409


@pytest.mark.parametrize(
    "data",
    [
        {**DATA, "name": " "},
        {**DATA, "base_currency": "XXX"},
        {**DATA, "workspace_id": str(uuid4())},
    ],
)
def test_invalid_account(db_client, data):
    assert db_client.post("/api/account", json=data).status_code == 422


def test_cross_workspace_reads_and_writes(db_client, database):
    db_client.post("/api/account", json=DATA)
    owner, workspace = uuid4(), uuid4()
    with Session(database) as session:
        session.add(Owner(id=owner))
        session.flush()
        session.add(Workspace(id=workspace, owner_id=owner))
        session.commit()
    app.dependency_overrides[get_actor] = lambda: Actor(owner, workspace)
    assert db_client.get("/api/account").json() is None
    foreign = db_client.post("/api/account", json={**DATA, "name": "Foreign"})
    assert foreign.status_code == 201
    app.dependency_overrides[get_actor] = lambda: Actor(owner, uuid4())
    assert db_client.post("/api/account", json=DATA).status_code == 403
    app.dependency_overrides.clear()
    assert db_client.get("/api/account").json()["name"] == DATA["name"]
