from datetime import date
from decimal import Decimal as D
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from helpers import cash, ledger
from sqlalchemy.orm import Session

from investor_platform.db import Actor
from investor_platform.import_transactions import apply_import, reconstruct
from investor_platform.models import Account
from investor_platform.reconcile_cash import CashReconciliation, reconcile


def setup(database):
    payload = (
        b"Date,Type,Symbol,Shares,Price (USD),Total (USD)\n"
        b"2026-01-02,Buy,AAA,1,10,10\n2026-01-05,Buy,AAA,1,20,20\n"
    )
    entries, summary = reconstruct(payload, {"AAA": {"exchange": "NYSE", "currency": "USD"}})
    aid, _ = apply_import(database, "Cash reconstruction fixture", entries, summary)
    return UUID(aid)


def plan_for(client, aid, **changes):
    before = ledger(client, aid)
    return CashReconciliation.model_validate(
        {
            "request_key": str(uuid4()),
            "source_reference": "Synthetic broker cash statement",
            "as_of": "2026-01-06",
            "reported_cash": "0.00",
            "confirm_complete_funding": True,
            "remove_entry_ids": [e["id"] for e in before["entries"] if e["security"] is None],
            "entries": [
                {
                    "request_key": str(uuid4()),
                    "kind": "deposit",
                    "effective_date": day,
                    "amount": amount,
                    "currency": "USD",
                    "note": "Synthetic source cash event",
                }
                for day, amount in [("2026-01-02", "10"), ("2026-01-05", "20")]
            ],
            **changes,
        }
    )


def test_atomic_cash_reconstruction_preserves_trades_and_retries(database, db_client):
    aid = setup(database)
    before = ledger(db_client, aid)
    plan = plan_for(db_client, aid)
    preview = reconcile(database, aid, plan)
    assert preview["applied"] is False
    assert ledger(db_client, aid) == before
    plan.expected_revision = preview["revision"]
    result = reconcile(database, aid, plan, apply=True)
    assert result["applied"] is True and D(result["cash"]) == 0
    after = ledger(db_client, aid)
    assert after["holdings"] == before["holdings"]
    assert [e for e in after["entries"] if e["security"]] == [
        e for e in before["entries"] if e["security"]
    ]
    assert [e["effective_date"] for e in after["entries"] if e["kind"] == "deposit"] == [
        "2026-01-02",
        "2026-01-05",
    ]
    assert after["corrections"][0]["original"]["kind"] == "opening_cash"
    assert reconcile(database, aid, plan, apply=True)["already_applied"] is True
    assert ledger(db_client, aid) == after
    with Session(database) as session:
        account = session.get(Account, aid)
        assert account.reconstruction["funding_status"] == "reconciled"
        assert (
            account.reconstruction["cash_reconciliations"][str(plan.request_key)]["source"][
                "source_reference"
            ]
            == plan.source_reference
        )
    changed = plan.model_copy(update={"source_reference": "Different source"})
    with pytest.raises(ValueError, match="already used"):
        reconcile(database, aid, changed, apply=True)


@pytest.mark.parametrize(
    "problem",
    ["later_funding", "closing_balance", "trade_removal", "missing_cash", "ownership", "stale"],
)
def test_failed_cash_plan_is_atomic(database, db_client, problem):
    aid = setup(database)
    plan = plan_for(db_client, aid)
    preview = reconcile(database, aid, plan)
    plan.expected_revision = preview["revision"]
    actor = None
    if problem == "later_funding":
        plan.entries[1].effective_date = date(2026, 1, 6)
    elif problem == "closing_balance":
        plan.reported_cash = D(1)
    elif problem == "trade_removal":
        plan.remove_entry_ids.append(ledger(db_client, aid)["entries"][-1]["id"])
    elif problem == "missing_cash":
        plan.remove_entry_ids = []
    elif problem == "ownership":
        actor = Actor(uuid4(), uuid4())
    else:
        assert cash(db_client, aid, amount="1", day="2026-01-06").status_code == 201
    before = ledger(db_client, aid)
    with pytest.raises((ValueError, HTTPException)):
        reconcile(database, aid, plan, apply=True, actor=actor)
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert session.get(Account, aid).reconstruction.get("funding_status") != "reconciled"


def test_incomplete_review_does_not_unlock_returns(database, db_client):
    aid = setup(database)
    plan = plan_for(db_client, aid, confirm_complete_funding=False)
    plan.expected_revision = reconcile(database, aid, plan)["revision"]
    reconcile(database, aid, plan, apply=True)
    with Session(database) as session:
        assert session.get(Account, aid).reconstruction["funding_status"] == "inferred"
