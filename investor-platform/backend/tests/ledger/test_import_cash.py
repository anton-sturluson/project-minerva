"""Exercise additive cash imports against isolated synthetic PostgreSQL schemas."""

from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from helpers import DAYS, cash, ledger, stock_report
from httpx import Response
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform.db import Actor
from investor_platform.domain import Currency, IncomeKind
from investor_platform.ledger.import_cash import CashImport, import_cash
from investor_platform.ledger.import_transactions import apply_import, reconstruct
from investor_platform.ledger.schemas import CashInput, LedgerRecord, TradeInput
from investor_platform.market_data.types import History
from investor_platform.models import Account, Owner, Security, Workspace


def setup(database: Engine) -> UUID:
    """Create a small imported portfolio with two funded purchases."""
    payload: bytes = (
        b"Date,Type,Symbol,Shares,Price (USD),Total (USD)\n"
        b"2026-01-02,Buy,AAA,1,10,10\n2026-01-05,Buy,AAA,1,20,20\n"
    )
    entries: list[CashInput | TradeInput]
    summary: dict
    entries, summary = reconstruct(payload, {"AAA": {"exchange": "NYSE", "currency": "USD"}})
    return UUID(apply_import(database, "Synthetic cash import", entries, summary)[0])


def plan_for() -> CashImport:
    """Return recorded income before a purchase and positive source tax and fee costs."""
    return CashImport.model_validate(
        {
            "request_key": str(uuid4()),
            "source_reference": "Synthetic broker statement, January 2026",
            "entries": [
                {
                    "request_key": str(uuid4()),
                    "kind": kind,
                    "effective_date": day,
                    "amount": amount,
                    "currency": "USD",
                    "note": note,
                }
                for kind, day, amount, note in [
                    ("income", "2026-01-03", "5", "AAA dividend; ex-date unverified"),
                    ("expense", "2026-01-04", ".5", "Dividend withholding tax"),
                    ("expense", "2026-01-04", ".1", "ADR fee"),
                ]
            ],
        }
    )


def test_preview_apply_receipt_and_overlap(database: Engine, db_client: TestClient) -> None:
    """Preview rolls back; apply changes exact funding once and retries do not add duplicates."""
    aid: UUID = setup(database)
    plan: CashImport = plan_for()
    before: dict = ledger(db_client, aid)
    preview: LedgerRecord = import_cash(database, aid, plan)
    assert preview["applied"] is False
    assert Decimal(str(preview["previous_inferred_deposits_total"])) == 30
    assert Decimal(str(preview["inferred_deposits_total"])) == Decimal("25.6")
    assert Decimal(str(preview["cash"])) == 0
    assert preview["added_entries"] == 3
    assert preview["unresolved_income_count"] == 1
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert "cash_imports" not in session.get(Account, aid).reconstruction
    plan.expected_revision = str(preview["revision"])
    result: LedgerRecord = import_cash(database, aid, plan, apply=True)
    after: dict = ledger(db_client, aid)
    assert result["applied"] is True
    assert after["holdings"] == before["holdings"]
    assert [entry for entry in after["entries"] if entry["security"]] == [
        entry for entry in before["entries"] if entry["security"]
    ]
    assert import_cash(database, aid, plan, apply=True)["already_applied"] is True
    assert ledger(db_client, aid) == after
    with Session(database) as session:
        receipt: dict = session.get(Account, aid).reconstruction["cash_imports"][
            str(plan.request_key)
        ]
        assert receipt["plan"]["source_reference"] == plan.source_reference
        assert receipt["plan"]["entries"][0]["income_kind"] is None
        assert receipt["result"] == result
    overlap: CashImport = plan.model_copy(
        update={"request_key": uuid4(), "expected_revision": None}
    )
    overlap_preview: LedgerRecord = import_cash(database, aid, overlap)
    assert overlap_preview["added_entries"] == 0 and overlap_preview["skipped_entries"] == 3
    overlap.expected_revision = str(overlap_preview["revision"])
    import_cash(database, aid, overlap, apply=True)
    assert ledger(db_client, aid) == after
    changed: CashImport = plan.model_copy(update={"source_reference": "different"})
    with pytest.raises(ValueError, match="Batch key"):
        import_cash(database, aid, changed, apply=True)


@pytest.mark.parametrize("problem", ["stale", "missing_revision", "owner", "currency"])
def test_rejected_batch_rolls_back(database: Engine, db_client: TestClient, problem: str) -> None:
    """Failure after valid earlier events cannot partially insert a batch or receipt."""
    aid: UUID = setup(database)
    plan: CashImport = plan_for()
    plan.expected_revision = str(import_cash(database, aid, plan)["revision"])
    actor: Actor | None = None
    if problem == "stale":
        assert cash(db_client, aid, amount="1", day="2026-01-06").status_code == 201
    elif problem == "missing_revision":
        plan.expected_revision = None
    elif problem == "owner":
        actor = Actor(uuid4(), uuid4())
    else:
        plan.entries[-1] = plan.entries[-1].model_copy(update={"currency": Currency.EUR})
    before: dict = ledger(db_client, aid)
    with pytest.raises((ValueError, HTTPException)):
        import_cash(database, aid, plan, apply=True, actor=actor)
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert "cash_imports" not in session.get(Account, aid).reconstruction


def test_event_collision_and_corrected_keys(database: Engine, db_client: TestClient) -> None:
    """New batch keys cannot bypass changed values or append-only event corrections."""
    aid: UUID = setup(database)
    plan: CashImport = plan_for()
    plan.expected_revision = str(import_cash(database, aid, plan)["revision"])
    import_cash(database, aid, plan, apply=True)
    plan.request_key = uuid4()
    plan.expected_revision = None
    original: CashInput = plan.entries[-1]
    plan.entries[-1] = original.model_copy(update={"amount": Decimal(".2")})
    with pytest.raises(ValueError, match="different values"):
        import_cash(database, aid, plan)
    plan.entries[-1] = original
    existing: dict = next(
        entry for entry in ledger(db_client, aid)["entries"] if entry["note"] == original.note
    )
    replacement: dict = original.model_dump(mode="json") | {"request_key": str(uuid4())}
    correction: dict = {
        "request_key": str(uuid4()),
        "reason": "Synthetic corrected note",
        "replacement": replacement,
    }
    url: str = f"/api/accounts/{aid}/entries/{existing['id']}/correction"
    preview_response: Response = db_client.post(url + "?preview=true", json=correction)
    assert preview_response.status_code == 200, preview_response.text
    correction["expected_revision"] = preview_response.json()["revision"]
    response: Response = db_client.post(url, json=correction)
    assert response.status_code == 200, response.text
    before: dict = ledger(db_client, aid)
    with pytest.raises(ValueError, match="corrected record"):
        import_cash(database, aid, plan)
    plan.entries[-1] = CashInput.model_validate(
        replacement | {"request_key": correction["request_key"]}
    )
    with pytest.raises(ValueError, match="corrected record"):
        import_cash(database, aid, plan)
    assert ledger(db_client, aid) == before


def test_preview_binds_exact_plan(database: Engine, db_client: TestClient) -> None:
    """Changing a reviewed amount requires a fresh preview before any cash can commit."""
    aid: UUID = setup(database)
    plan: CashImport = plan_for()
    preview: LedgerRecord = import_cash(database, aid, plan)
    plan.expected_revision = str(preview["revision"])
    plan.entries[0] = plan.entries[0].model_copy(update={"amount": Decimal("500")})
    before: dict = ledger(db_client, aid)
    metadata: dict
    with Session(database) as session:
        metadata = dict(session.get(Account, aid).reconstruction)
    with pytest.raises(ValueError, match="plan changed"):
        import_cash(database, aid, plan, apply=True)
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert session.get(Account, aid).reconstruction == metadata
    fresh: LedgerRecord = import_cash(database, aid, plan)
    assert fresh["revision"] != preview["revision"]
    assert ledger(db_client, aid) == before
    plan.expected_revision = str(fresh["revision"])
    result: LedgerRecord = import_cash(database, aid, plan, apply=True)
    assert result["applied"] is True
    assert Decimal(str(result["cash"])) == Decimal("479.4")


@pytest.mark.parametrize("kind,amount", [("deposit", "1"), ("expense", "-1"), ("income", "0")])
def test_invalid_cash_event(kind: str, amount: str) -> None:
    """Funding rows and signed or zero costs cannot enter the additive plan."""
    body: LedgerRecord = cast(LedgerRecord, plan_for().model_dump(mode="json"))
    body["entries"][0]["kind"] = kind
    body["entries"][0]["amount"] = amount
    with pytest.raises(ValueError):
        CashImport.model_validate(body)


@pytest.mark.parametrize("foreign", [False, True])
def test_mixed_verified_and_unverified_income(
    database: Engine, db_client: TestClient, foreign: bool
) -> None:
    """Accept verified attribution or roll back the full batch for another workspace's listing."""
    aid: UUID = setup(database)
    before: dict = ledger(db_client, aid)
    security_id: UUID = UUID(before["holdings"][0]["security"]["id"])
    if foreign:
        owner_id: UUID = uuid4()
        workspace_id: UUID = uuid4()
        security_id = uuid4()
        with Session(database) as session:
            session.add(Owner(id=owner_id))
            session.flush()
            session.add(Workspace(id=workspace_id, owner_id=owner_id))
            session.flush()
            session.add(
                Security(
                    id=security_id,
                    workspace_id=workspace_id,
                    ticker="AAA",
                    exchange="NYSE",
                    currency="USD",
                )
            )
            session.commit()
    plan: CashImport = plan_for()
    classified: CashInput = plan.entries[0].model_copy(
        update={
            "request_key": uuid4(),
            "income_kind": IncomeKind.DIVIDEND,
            "income_security_id": security_id,
            "accrual_date": date(2026, 1, 2),
        }
    )
    # Check ownership after an earlier valid cash event has already been staged.
    plan.entries.append(classified)
    if foreign:
        with pytest.raises(HTTPException, match="Income security not found"):
            import_cash(database, aid, plan)
        assert ledger(db_client, aid) == before
        with Session(database) as session:
            assert "cash_imports" not in session.get(Account, aid).reconstruction
        return
    preview: LedgerRecord = import_cash(database, aid, plan)
    assert preview["added_entries"] == 4
    assert preview["unresolved_income_count"] == 1
    plan.expected_revision = str(preview["revision"])
    import_cash(database, aid, plan, apply=True)
    after: dict = ledger(db_client, aid)
    income: list[dict] = [entry for entry in after["entries"] if entry["kind"] == "income"]
    assert len(income) == 2
    verified: dict = next(entry for entry in income if entry["income_kind"] == "dividend")
    assert verified["income_security"]["id"] == str(security_id)
    assert verified["accrual_date"] == "2026-01-02"
    assert after["holdings"] == before["holdings"]


@pytest.mark.parametrize("gross", ["10", "9"])
def test_imported_dividend_and_costs_flow_into_account_returns(
    database: Engine,
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    gross: str,
) -> None:
    """A dividend accrues once and tax and ADR costs reduce whole-account wealth."""
    payload: bytes = (
        b"Date,Type,Symbol,Shares,Price (USD),Total (USD)\n2026-01-02,Buy,AAA,10,100,1000\n"
    )
    entries: list[CashInput | TradeInput]
    summary: dict
    entries, summary = reconstruct(payload, {"AAA": {"exchange": "NYSE", "currency": "USD"}})
    aid: UUID = UUID(apply_import(database, "Synthetic dividend performance", entries, summary)[0])
    with Session(database) as session:
        account: Account = session.get(Account, aid)
        account.reconstruction = account.reconstruction | {"dividend_policy": "unrecorded_zero"}
        session.commit()
    portfolio[1]["AAA"].close = dict.fromkeys(DAYS, Decimal("100"))
    portfolio[1]["AAA"].dividends = {DAYS[1]: Decimal("1")}
    before: dict = ledger(db_client, aid)
    baseline_response: Response = stock_report(db_client, aid, scope="account")
    assert baseline_response.status_code == 200, baseline_response.text
    baseline: dict = baseline_response.json()
    assert Decimal(baseline["return"]) == 0
    security_id: UUID = UUID(before["holdings"][0]["security"]["id"])
    plan: CashImport = CashImport.model_validate(
        {
            "request_key": str(uuid4()),
            "source_reference": "Synthetic verified dividend statement",
            "entries": [
                {
                    "request_key": str(uuid4()),
                    "kind": "income",
                    "effective_date": str(DAYS[2]),
                    "amount": gross,
                    "currency": "USD",
                    "income_kind": "dividend",
                    "income_security_id": str(security_id),
                    "accrual_date": str(DAYS[1]),
                },
                {
                    "request_key": str(uuid4()),
                    "kind": "expense",
                    "effective_date": str(DAYS[2]),
                    "amount": "1",
                    "currency": "USD",
                    "note": "Withholding tax",
                },
                {
                    "request_key": str(uuid4()),
                    "kind": "expense",
                    "effective_date": str(DAYS[2]),
                    "amount": ".25",
                    "currency": "USD",
                    "note": "ADR fee",
                },
            ],
        }
    )
    preview: LedgerRecord = import_cash(database, aid, plan)
    plan.expected_revision = str(preview["revision"])
    result: LedgerRecord = import_cash(database, aid, plan, apply=True)
    assert Decimal(str(result["previous_inferred_deposits_total"])) == 1000
    assert Decimal(str(result["inferred_deposits_total"])) == 1000
    after: dict = ledger(db_client, aid)
    assert after["holdings"] == before["holdings"]
    assert [entry for entry in after["entries"] if entry["security"]] == [
        entry for entry in before["entries"] if entry["security"]
    ]
    deposits: list[dict] = [entry for entry in after["entries"] if entry["kind"] == "deposit"]
    assert len(deposits) == 1 and Decimal(deposits[0]["amount"]) == 1000
    mode: str
    for mode in ("buy_hold", "funded_hold"):
        response: Response = stock_report(db_client, aid, scope="account", benchmark_mode=mode)
        assert response.status_code == 200, response.text
        report: dict = response.json()
        if gross != "10":
            assert report["return"] is None
            assert any("reconcile dividend" in warning for warning in report["warnings"])
            continue
        assert report["warnings"] == []
        assert Decimal(report["series"][1]["cash"]) == 0
        assert Decimal(report["series"][1]["receivables"]) == 10
        assert Decimal(report["series"][1]["portfolio"]) == Decimal(".01")
        assert Decimal(report["series"][2]["receivables"]) == 0
        assert Decimal(report["cash"]) == Decimal("8.75")
        assert Decimal(report["value"]) == Decimal("1008.75")
        assert Decimal(report["return"]) == Decimal(".00875")
        if mode == "funded_hold":
            assert Decimal(report["benchmark_values"]["SPY"]["value"]) == 1020
