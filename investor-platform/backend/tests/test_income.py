from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_ledger import cash, ledger
from test_trades import trade

from investor_platform.models import LedgerEntry, Owner, Security, Workspace


def setup(client):
    aid = client.post(
        "/api/accounts", json={"name": "Income fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(client, aid, "opening_cash", "100", day="2026-01-02")
    buy = trade(client, aid, quantity="1", price="100", ticker="AAA", exchange="NYSE").json()
    return aid, buy["security"]["id"]


def dividend_body(sid, **changes):
    return {
        "request_key": str(uuid4()),
        "kind": "income",
        "amount": "10",
        "currency": "USD",
        "effective_date": "2026-01-08",
        "income_kind": "dividend",
        "income_security_id": sid,
        "accrual_date": "2026-01-05",
        **changes,
    }


def test_dividend_retry_and_audited_correction_preserve_attribution(db_client):
    aid, sid = setup(db_client)
    body = dividend_body(sid)
    url = f"/api/accounts/{aid}/cash"
    saved = db_client.post(url, json=body)
    assert saved.status_code == 201
    assert db_client.post(url, json=body).json()["id"] == saved.json()["id"]
    assert len(ledger(db_client, aid)["entries"]) == 3
    # A receivable cannot fund a purchase before the dividend's cash payment.
    assert (
        trade(
            db_client,
            aid,
            quantity="1",
            price="5",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-06",
        ).status_code
        == 409
    )
    correction = f"/api/accounts/{aid}/entries/{saved.json()['id']}/correction"
    request = {
        "request_key": str(uuid4()),
        "reason": "Correct broker gross dividend",
        "replacement": {**body, "amount": "12"},
    }
    preview = db_client.post(correction + "?preview=true", json=request)
    assert preview.status_code == 200
    assert preview.json()["replacement"]["income_security"]["id"] == sid
    assert ledger(db_client, aid)["balance"] == "10.0000000000000000"
    request["expected_revision"] = preview.json()["revision"]
    assert db_client.post(correction, json=request).status_code == 200
    state = ledger(db_client, aid)
    assert state["balance"] == "12.0000000000000000"
    assert state["entries"][-1]["accrual_date"] == "2026-01-05"
    assert state["corrections"][0]["original"]["amount"] == "10.0000000000000000"


@pytest.mark.parametrize(
    "changes",
    [
        {"accrual_date": "2026-01-09"},
        {"accrual_date": None},
        {"income_security_id": None},
        {"kind": "deposit"},
        {"income_kind": "interest"},
        {"income_kind": None},
    ],
)
def test_invalid_income_attribution_does_not_write(db_client, changes):
    aid, sid = setup(db_client)
    before = ledger(db_client, aid)
    assert (
        db_client.post(f"/api/accounts/{aid}/cash", json=dividend_body(sid, **changes)).status_code
        == 422
    )
    assert ledger(db_client, aid) == before


def test_dividend_security_is_workspace_scoped_and_database_shape_rejects_null_category(
    db_client, database
):
    aid, sid = setup(db_client)
    owner, workspace, foreign_sid = uuid4(), uuid4(), uuid4()
    with Session(database) as session, session.begin():
        session.add(Owner(id=owner))
        session.flush()
        session.add(Workspace(id=workspace, owner_id=owner))
        session.flush()
        session.add(
            Security(
                id=foreign_sid,
                workspace_id=workspace,
                ticker="PRIVATE",
                exchange="NYSE",
                currency="USD",
            )
        )
    before = ledger(db_client, aid)
    assert (
        db_client.post(
            f"/api/accounts/{aid}/cash", json=dividend_body(str(foreign_sid))
        ).status_code
        == 404
    )
    assert ledger(db_client, aid) == before
    income = cash(db_client, aid, "income", "2", day="2026-01-08")
    with pytest.raises(IntegrityError), Session(database) as session, session.begin():
        entry = session.scalar(select(LedgerEntry).where(LedgerEntry.id == income.json()["id"]))
        entry.income_security_id = sid
        entry.accrual_date = entry.effective_date
        session.flush()
