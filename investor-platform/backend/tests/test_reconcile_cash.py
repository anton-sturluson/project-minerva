from datetime import date
from decimal import Decimal as D
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from helpers import DAYS, cash, dividend, ledger, stock_report, trade
from httpx import Response
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform.db import Actor
from investor_platform.import_transactions import apply_import, reconstruct
from investor_platform.ledger import CashInput, entries_for, funding_purchase_key
from investor_platform.market import History
from investor_platform.models import Account
from investor_platform.reconcile_cash import CashReconciliation, reconcile
from investor_platform.trades import TradeInput


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
    assert all(c["original"]["kind"] == "deposit" for c in after["corrections"])
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


@pytest.mark.parametrize("complete", [False, True])
def test_reconciliation_leaves_inference_and_preserves_recorded_cash_lifecycle(
    database: Engine,
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    complete: bool,
) -> None:
    """Recorded source cash stays recorded after previews, retries, and later ledger mutations."""
    aid: UUID = setup(database)
    session: Session
    with Session(database) as session:
        account: Account = session.get(Account, aid)
        account.reconstruction = account.reconstruction | {"dividend_policy": "unrecorded_zero"}
        original_metadata: dict = dict(account.reconstruction)
        session.commit()
    before: dict = ledger(db_client, aid)
    plan: CashReconciliation = plan_for(db_client, aid, confirm_complete_funding=complete)
    preview: dict = reconcile(database, aid, plan)
    assert preview["cash_method"] == "recorded"
    assert preview["funding_status"] == ("reconciled" if complete else "inferred")
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert session.get(Account, aid).reconstruction == original_metadata
    plan.expected_revision = preview["revision"]
    result: dict = reconcile(database, aid, plan, apply=True)
    after: dict = ledger(db_client, aid)
    assert result["cash_method"] == "recorded"
    assert after["holdings"] == before["holdings"]
    assert [entry for entry in after["entries"] if entry["security"]] == [
        entry for entry in before["entries"] if entry["security"]
    ]
    assert min(entry["id"] for entry in after["entries"] if entry["kind"] == "deposit") > max(
        entry["id"] for entry in after["entries"] if entry["security"]
    )
    assert reconcile(database, aid, plan, apply=True)["already_applied"] is True
    assert ledger(db_client, aid) == after
    with Session(database) as session:
        account = session.get(Account, aid)
        assert account.reconstruction["cash_method"] == "recorded"
        assert account.reconstruction["dividend_policy"] == "unrecorded_zero"
        assert "dated recorded events" in account.reconstruction["warning"]
    reports: list[dict] = []
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(db_client, aid, scope="account", benchmark_mode=mode)
        assert response.status_code == 200, response.text
        report: dict = response.json()
        assert report["cash_method"] == "recorded"
        assert report["dividend_policy"] == "unrecorded_zero"
        assert (report["return"] is not None) is complete
        assert not any(
            "Purchase-date deposits are inferred" in item for item in report["assumptions"]
        )
        reports.append(report)
    assert reports[0]["return"] == reports[1]["return"]
    assert reports[0]["cagr"]["portfolio"] == reports[1]["cagr"]["portfolio"]
    assert [point["portfolio"] for point in reports[0]["series"]] == [
        point["portfolio"] for point in reports[1]["series"]
    ]
    assert cash(db_client, aid, amount="1", day="2026-01-06").status_code == 201
    current: dict = ledger(db_client, aid)
    assert D(current["balance"]) == 1
    assert len(current["corrections"]) == len(after["corrections"])
    with Session(database) as session:
        assert not any(funding_purchase_key(entry) for entry in entries_for(session, aid))
    assert (
        trade(
            db_client,
            aid,
            quantity="1",
            price="100",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-07",
        ).status_code
        == 409
    )
    assert ledger(db_client, aid) == current
    buy: dict = next(entry for entry in current["entries"] if entry["kind"] == "buy")
    correction: dict = {
        "request_key": str(uuid4()),
        "reason": "Synthetic source price correction",
        "replacement": {
            "request_key": str(uuid4()),
            "kind": "buy",
            "currency": "USD",
            "effective_date": buy["effective_date"],
            "ticker": "AAA",
            "exchange": "NYSE",
            "quantity": "1",
            "price": "100",
        },
    }
    rejected: Response = db_client.post(
        f"/api/accounts/{aid}/entries/{buy['id']}/correction?preview=true", json=correction
    )
    assert rejected.status_code == 409
    assert ledger(db_client, aid) == current


@pytest.mark.parametrize("complete", [False, True])
def test_recorded_cash_completeness_controls_annualized_returns(
    database: Engine,
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    complete: bool,
) -> None:
    """A recorded partial review withholds CAGR even when the reporting period exceeds a year."""
    first: date = date(2024, 1, 2)
    second: date = date(2025, 1, 2)
    payload: bytes = (
        b"Date,Type,Symbol,Shares,Price (USD),Total (USD)\n"
        b"2024-01-02,Buy,AAA,1,10,10\n2025-01-02,Buy,AAA,1,20,20\n"
    )
    entries: list[CashInput | TradeInput]
    summary: dict
    entries, summary = reconstruct(payload, {"AAA": {"exchange": "NYSE", "currency": "USD"}})
    aid: str = apply_import(database, "Long recorded funding fixture", entries, summary)[0]
    history: History
    for history in portfolio[1].values():
        history.close[first] = history.close[DAYS[0]]
        history.adjusted[first] = history.adjusted[DAYS[0]]
        history.close[second] = history.close[DAYS[1]]
        history.adjusted[second] = history.adjusted[DAYS[1]]
    plan: CashReconciliation = plan_for(db_client, aid, confirm_complete_funding=complete)
    plan.entries[0].effective_date = first
    plan.entries[1].effective_date = second
    plan.expected_revision = reconcile(database, UUID(aid), plan)["revision"]
    reconcile(database, UUID(aid), plan, apply=True)
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(
            db_client, aid, scope="account", benchmark_mode=mode, start=str(first)
        )
        assert response.status_code == 200, response.text
        assert (response.json()["return"] is not None) is complete
        assert (response.json()["cagr"]["portfolio"] is not None) is complete


@pytest.mark.parametrize("policy", [False, True])
def test_recorded_cash_keeps_explicit_zero_dividend_policy_without_hiding_mismatches(
    database: Engine,
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    policy: bool,
) -> None:
    """Source reconciliation preserves the zero assumption while actual income stays validated."""
    aid: UUID = setup(database)
    session: Session
    if policy:
        with Session(database) as session:
            account: Account = session.get(Account, aid)
            account.reconstruction = account.reconstruction | {"dividend_policy": "unrecorded_zero"}
            session.commit()
    plan: CashReconciliation = plan_for(db_client, aid)
    plan.expected_revision = reconcile(database, aid, plan)["revision"]
    reconcile(database, aid, plan, apply=True)
    portfolio[1]["AAA"].dividends[DAYS[1]] = D(1)
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(db_client, aid, scope="account", benchmark_mode=mode)
        assert response.status_code == 200, response.text
        assert (response.json()["return"] is not None) is policy
        assert (response.json().get("dividend_policy") == "unrecorded_zero") is policy
    assert dividend(db_client, aid, amount=".5").status_code == 201
    for mode in ("buy_hold", "funded_hold"):
        response = stock_report(db_client, aid, scope="account", benchmark_mode=mode)
        assert response.status_code == 200, response.text
        assert response.json()["return"] is None
        assert any("reconcile dividend" in warning for warning in response.json()["warnings"])


def test_recorded_opening_cash_is_valid_for_account_but_not_deposit_matched_indexes(
    database: Engine, db_client: TestClient, portfolio: tuple[str, dict[str, History]]
) -> None:
    """A genuine opening balance is never silently discarded by the deposit-only simulation."""
    aid: str = portfolio[0]
    session: Session
    with Session(database) as session:
        account: Account = session.get(Account, UUID(aid))
        account.reconstruction = {"cash_method": "recorded", "funding_status": "reconciled"}
        session.commit()
    ordinary: Response = stock_report(db_client, aid, scope="account", benchmark_mode="buy_hold")
    funded: Response = stock_report(db_client, aid, scope="account", benchmark_mode="funded_hold")
    assert ordinary.status_code == 200 and D(ordinary.json()["return"]) == D(".21")
    assert funded.status_code == 422
    assert "recorded opening cash" in funded.json()["detail"]
