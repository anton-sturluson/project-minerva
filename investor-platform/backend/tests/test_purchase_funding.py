"""Verify dated funding conservation, auditable migration, and future ledger maintenance."""

from datetime import date
from decimal import Decimal as D
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from helpers import cash, ledger, trade
from httpx import Response
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from investor_platform.domain import EntryKind
from investor_platform.funding import CashMovement, PurchaseShortfall, infer_purchase_shortfalls
from investor_platform.import_transactions import apply_import, reconstruct
from investor_platform.ledger import CashInput, entries_for, funding_purchase_key
from investor_platform.models import Account, LedgerCorrection, LedgerEntry
from investor_platform.purchase_funding import (
    FundingMigration,
    FundingMigrationResult,
    migrate_purchase_funding,
)
from investor_platform.trades import TradeInput


def imported(database: Engine) -> str:
    """Import two dated purchases without any recorded or placeholder starting cash."""
    entries: list[TradeInput | CashInput]
    summary: dict
    entries, summary = reconstruct(
        b"Date,Type,Symbol,Shares,Price (USD),Total (USD)\n"
        b"2026-01-02,Buy,AAA,1,100,100\n2026-01-06,Buy,AAA,1,100,100\n",
        {"AAA": {"exchange": "NYSE", "currency": "USD"}},
    )
    return apply_import(database, "Synthetic inferred funding", entries, summary)[0]


def test_shortfalls_use_only_preceding_cash_and_preserve_exact_amounts() -> None:
    """Earlier sales and paid income fund buys; a later same-day sale cannot fund an earlier buy."""
    day: date = date(2026, 1, 2)
    movements: list[CashMovement] = [
        CashMovement(day, EntryKind.BUY, D("10.0000000000000001")),
        CashMovement(day, EntryKind.SELL, D("4")),
        CashMovement(day, EntryKind.INCOME, D("1")),
        CashMovement(day, EntryKind.BUY, D("7")),
        CashMovement(day, EntryKind.SELL, D("3")),
    ]
    shortfalls: list[PurchaseShortfall] = infer_purchase_shortfalls(movements)
    assert [(item.index, item.amount) for item in shortfalls] == [
        (0, D("10.0000000000000001")),
        (3, D("2")),
    ]
    assert (
        sum((item.amount for item in shortfalls), D(0)) + 4 + 1 + 3 - D("17.0000000000000001") == 3
    )
    assert (
        infer_purchase_shortfalls(
            [CashMovement(day, EntryKind.SELL, D(10)), CashMovement(day, EntryKind.BUY, D(10))]
        )
        == []
    )
    with pytest.raises(ValueError, match="cash outflows"):
        infer_purchase_shortfalls([CashMovement(day, EntryKind.WITHDRAWAL, D(1))])


def test_import_keeps_full_product_precision_and_has_no_opening_cash(database: Engine) -> None:
    """A fractional execution's complete sixteen-decimal cash cost is funded exactly."""
    entries: list[TradeInput | CashInput]
    summary: dict
    entries, summary = reconstruct(
        b"Date,Type,Symbol,Shares,Cost,Price\n2026-01-02,Buy,AAA,0.12345678,0.12345678,\n",
        {"AAA": {"exchange": "NYSE", "currency": "USD"}},
    )
    aid: str = apply_import(database, "Precise inferred funding", entries, summary)[0]
    session: Session
    with Session(database) as session:
        rows: list[LedgerEntry] = entries_for(session, UUID(aid))
        assert [row.kind for row in rows] == ["deposit", "buy"]
        assert rows[0].amount == rows[1].amount == D("0.0152415765279684")
        assert funding_purchase_key(rows[0]) == rows[1].request_key
        assert "opening_cash" not in session.get(Account, UUID(aid)).reconstruction


def test_future_buys_sales_and_cash_updates_recompute_only_inferred_funding(
    database: Engine, db_client: TestClient
) -> None:
    """Future real cash and proceeds replace assumptions without editing original trade rows."""
    aid: str = imported(database)
    before: dict = ledger(db_client, aid)
    original_buys: list[dict] = [entry for entry in before["entries"] if entry["kind"] == "buy"]
    assert cash(db_client, aid, amount="50", day="2026-01-05").status_code == 201
    current: dict = ledger(db_client, aid)
    assert [D(entry["amount"]) for entry in current["entries"] if entry["kind"] == "deposit"] == [
        100,
        50,
        50,
    ]
    assert [entry for entry in current["entries"] if entry["kind"] == "buy"] == original_buys
    assert len(current["corrections"]) == 1
    assert D(current["balance"]) == 0
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "1",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-07",
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            quantity="1",
            price="150",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-08",
        ).status_code
        == 201
    )
    current = ledger(db_client, aid)
    assert D(current["balance"]) == 0
    assert D(current["entries"][-2]["amount"]) == 30
    assert current["entries"][-2]["kind"] == "deposit"
    assert current["entries"][-1]["kind"] == "buy"
    assert cash(db_client, aid, "withdrawal", "1", day="2026-01-09").status_code == 409


def test_backdated_sale_funds_later_buys_and_removes_unneeded_deposits(
    database: Engine, db_client: TestClient
) -> None:
    """New earlier proceeds void later inferred cash rather than double-fund the account."""
    aid: str = imported(database)
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "1",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
        ).status_code
        == 201
    )
    result: dict = ledger(db_client, aid)
    assert [D(entry["amount"]) for entry in result["entries"] if entry["kind"] == "deposit"] == [
        100
    ]
    assert D(result["balance"]) == 20
    assert result["corrections"][0]["replacement"] is None


def test_purchase_correction_preview_and_apply_rederive_funding_atomically(
    database: Engine, db_client: TestClient
) -> None:
    """Correcting and voiding purchases preserves the old cash assumptions in audit history."""
    aid: str = imported(database)
    before: dict = ledger(db_client, aid)
    buy: dict = before["entries"][-1]
    body: dict = {
        "request_key": str(uuid4()),
        "reason": "Synthetic execution correction",
        "replacement": {
            "request_key": str(uuid4()),
            "kind": "buy",
            "effective_date": "2026-01-06",
            "currency": "USD",
            "ticker": "AAA",
            "exchange": "NYSE",
            "quantity": "1",
            "price": "150",
        },
    }
    url: str = f"/api/accounts/{aid}/entries/{buy['id']}/correction"
    preview: Response = db_client.post(url + "?preview=true", json=body)
    assert preview.status_code == 200, preview.text
    assert ledger(db_client, aid) == before
    body["expected_revision"] = preview.json()["revision"]
    applied: Response = db_client.post(url, json=body)
    assert applied.status_code == 200, applied.text
    after: dict = ledger(db_client, aid)
    assert [D(entry["amount"]) for entry in after["entries"] if entry["kind"] == "deposit"] == [
        100,
        150,
    ]
    assert D(after["balance"]) == 0
    assert len(after["corrections"]) == 2
    assert db_client.post(url, json=body).json() == applied.json()
    assert ledger(db_client, aid) == after
    body = {"request_key": str(uuid4()), "reason": "Synthetic purchase void", "replacement": None}
    url = f"/api/accounts/{aid}/entries/{after['entries'][-1]['id']}/correction"
    preview = db_client.post(url + "?preview=true", json=body)
    body["expected_revision"] = preview.json()["revision"]
    assert db_client.post(url, json=body).status_code == 200
    final: dict = ledger(db_client, aid)
    assert [D(entry["amount"]) for entry in final["entries"] if entry["kind"] == "deposit"] == [100]
    assert D(final["holdings"][0]["quantity"]) == 1


def legacy_account(database: Engine, db_client: TestClient) -> tuple[str, list[int]]:
    """Create a source-marked opening placeholder and an explicitly reviewed balancing deposit."""
    aid: str = db_client.post(
        "/api/accounts", json={"name": "Legacy inferred fixture", "base_currency": "USD"}
    ).json()["id"]
    opening: dict = cash(db_client, aid, "opening_cash", "1000", day="2026-01-02").json()
    assert (
        trade(db_client, aid, quantity="1", price="100", ticker="AAA", exchange="NYSE").status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "1",
            "120",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            quantity="1",
            price="150",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-06",
        ).status_code
        == 201
    )
    balancing: dict = cash(db_client, aid, amount="999", day="2026-01-06").json()
    session: Session
    with Session(database) as session:
        session.get(Account, UUID(aid)).reconstruction = {
            "opening_cash": "1000",
            "funding_status": "inferred",
        }
        session.commit()
    return aid, [opening["id"], balancing["id"]]


def test_migration_preview_apply_retry_preserve_trades_and_original_records(
    database: Engine, db_client: TestClient
) -> None:
    """Replace reviewed placeholders with sufficient dated cash and retain the source history."""
    aid: str
    removed: list[int]
    aid, removed = legacy_account(database, db_client)
    before: dict = ledger(db_client, aid)
    plan: FundingMigration = FundingMigration(
        request_key=uuid4(),
        source_reference="Reviewed synthetic placeholders",
        remove_entry_ids=removed,
    )
    preview: FundingMigrationResult = migrate_purchase_funding(database, UUID(aid), plan)
    assert [D(row["amount"]) for row in preview["deposits"]] == [100, 30]
    assert D(preview["cash"]) == 0
    assert ledger(db_client, aid) == before
    plan.expected_revision = preview["revision"]
    result: FundingMigrationResult = migrate_purchase_funding(database, UUID(aid), plan, apply=True)
    after: dict = ledger(db_client, aid)
    assert not any(entry["kind"] == "opening_cash" for entry in after["entries"])
    assert [entry for entry in before["entries"] if entry["security"]] == [
        entry for entry in after["entries"] if entry["security"]
    ]
    assert after["holdings"] == before["holdings"]
    assert [D(entry["amount"]) for entry in after["entries"] if entry["kind"] == "deposit"] == [
        100,
        30,
    ]
    assert migrate_purchase_funding(database, UUID(aid), plan, apply=True)["already_applied"]
    assert ledger(db_client, aid) == after
    session: Session
    with Session(database) as session:
        assert all(session.get(LedgerEntry, entry_id) is not None for entry_id in removed)
        assert session.scalar(select(func.count()).select_from(LedgerCorrection)) == 2
        assert session.get(Account, UUID(aid)).reconstruction["funding_status"] == "inferred"
    assert result["holdings_unchanged"]
    with pytest.raises(ValueError, match="already used"):
        migrate_purchase_funding(
            database,
            UUID(aid),
            plan.model_copy(update={"source_reference": "Changed plan"}),
            apply=True,
        )


@pytest.mark.parametrize(
    "problem", ["stale", "trade", "missing_opening", "verified", "unknown_opening"]
)
def test_migration_rejects_unreviewed_or_stale_changes_atomically(
    database: Engine, db_client: TestClient, problem: str
) -> None:
    """A stale preview or unsupported removal cannot edit cash or holdings."""
    aid: str
    removed: list[int]
    aid, removed = legacy_account(database, db_client)
    plan: FundingMigration = FundingMigration(
        request_key=uuid4(),
        source_reference="Reviewed synthetic placeholders",
        remove_entry_ids=removed,
    )
    plan.expected_revision = migrate_purchase_funding(database, UUID(aid), plan)["revision"]
    if problem == "stale":
        assert cash(db_client, aid, amount="1", day="2026-01-06").status_code == 201
    elif problem == "trade":
        plan.remove_entry_ids.append(
            next(entry["id"] for entry in ledger(db_client, aid)["entries"] if entry["security"])
        )
    elif problem == "missing_opening":
        plan.remove_entry_ids = removed[1:]
    else:
        with Session(database) as session:
            account: Account = session.get(Account, UUID(aid))
            account.reconstruction = account.reconstruction | (
                {"funding_status": "reconciled"}
                if problem == "verified"
                else {"opening_cash": "900"}
            )
            session.commit()
        if problem != "verified":
            with pytest.raises(ValueError, match="not an explicitly inferred"):
                migrate_purchase_funding(database, UUID(aid), plan)
            return
    before: dict = ledger(db_client, aid)
    with pytest.raises(ValueError):
        migrate_purchase_funding(database, UUID(aid), plan, apply=True)
    assert ledger(db_client, aid) == before


def test_recorded_paid_income_reduces_later_funding_without_churning_earlier_rows(
    database: Engine, db_client: TestClient
) -> None:
    """Only the actual payment date supplies cash; unrelated earlier assumptions keep their IDs."""
    aid: str = imported(database)
    before: dict = ledger(db_client, aid)
    first_deposit_id: int = before["entries"][0]["id"]
    assert (
        cash(db_client, aid, "income", "40", day="2026-01-05", income_kind="interest").status_code
        == 201
    )
    current: dict = ledger(db_client, aid)
    assert current["entries"][0]["id"] == first_deposit_id
    assert [D(entry["amount"]) for entry in current["entries"] if entry["kind"] == "deposit"] == [
        100,
        60,
    ]
    assert len(current["corrections"]) == 1
    generated_ids: list[int] = [
        entry["id"] for entry in current["entries"] if entry["kind"] == "deposit"
    ]
    assert (
        cash(db_client, aid, "income", "5", day="2026-01-07", income_kind="interest").status_code
        == 201
    )
    current = ledger(db_client, aid)
    assert [
        entry["id"] for entry in current["entries"] if entry["kind"] == "deposit"
    ] == generated_ids
    assert len(current["corrections"]) == 1
    assert D(current["balance"]) == 5


def test_later_same_day_sale_never_retroactively_funds_an_earlier_purchase(
    database: Engine, db_client: TestClient
) -> None:
    """Same-day source order remains meaningful when a later sale can fund the next date's buy."""
    aid: str = imported(database)
    assert (
        trade(
            db_client,
            aid,
            quantity="1",
            price="100",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
        ).status_code
        == 201
    )
    assert (
        trade(
            db_client,
            aid,
            "sell",
            "1",
            "100",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2026-01-05",
        ).status_code
        == 201
    )
    result: dict = ledger(db_client, aid)
    assert [
        (entry["effective_date"], D(entry["amount"]))
        for entry in result["entries"]
        if entry["kind"] == "deposit"
    ] == [("2026-01-02", D(100)), ("2026-01-05", D(100))]
    assert [
        entry["kind"] for entry in result["entries"] if entry["effective_date"] == "2026-01-05"
    ] == ["deposit", "buy", "sell"]
    assert D(result["balance"]) == 0


def test_voiding_real_cash_recreates_only_the_required_generated_shortfall(
    database: Engine, db_client: TestClient
) -> None:
    """A real deposit correction updates derived funding and retains the real row's audit trail."""
    aid: str = imported(database)
    real: dict = cash(db_client, aid, amount="50", day="2026-01-05").json()
    before: dict = ledger(db_client, aid)
    body: dict = {
        "request_key": str(uuid4()),
        "reason": "Synthetic source deposit void",
        "replacement": None,
    }
    url: str = f"/api/accounts/{aid}/entries/{real['id']}/correction"
    preview: Response = db_client.post(url + "?preview=true", json=body)
    assert preview.status_code == 200, preview.text
    assert ledger(db_client, aid) == before
    body["expected_revision"] = preview.json()["revision"]
    applied: Response = db_client.post(url, json=body)
    assert applied.status_code == 200, applied.text
    result: dict = ledger(db_client, aid)
    assert [D(entry["amount"]) for entry in result["entries"] if entry["kind"] == "deposit"] == [
        100,
        100,
    ]
    assert D(result["balance"]) == 0
    assert result["entries"][0]["id"] == before["entries"][0]["id"]


def test_migration_preserves_unlisted_real_deposits_and_removes_active_opening_metadata(
    database: Engine, db_client: TestClient
) -> None:
    """Review targets exact placeholders; an unrelated real cash receipt remains intact."""
    aid: str
    removed: list[int]
    aid, removed = legacy_account(database, db_client)
    real: dict = cash(db_client, aid, amount="10", day="2026-01-05").json()
    before: dict = ledger(db_client, aid)
    plan: FundingMigration = FundingMigration(
        request_key=uuid4(),
        source_reference="Reviewed synthetic placeholders",
        remove_entry_ids=removed,
    )
    plan.expected_revision = migrate_purchase_funding(database, UUID(aid), plan)["revision"]
    result: FundingMigrationResult = migrate_purchase_funding(database, UUID(aid), plan, apply=True)
    current: dict = ledger(db_client, aid)
    assert next(entry for entry in current["entries"] if entry["id"] == real["id"]) == next(
        entry for entry in before["entries"] if entry["id"] == real["id"]
    )
    assert [D(entry["amount"]) for entry in current["entries"] if entry["kind"] == "deposit"] == [
        100,
        10,
        20,
    ]
    assert result["previous_opening_cash"] == "1000"
    session: Session
    with Session(database) as session:
        assert "opening_cash" not in session.get(Account, UUID(aid)).reconstruction


@pytest.mark.parametrize("edit", [False, True])
def test_direct_generated_funding_edits_cannot_become_genuine_deposits(
    database: Engine, db_client: TestClient, edit: bool
) -> None:
    """Derived rows cannot be voided or edited outside their source trade and cash inputs."""
    aid: str = imported(database)
    before: dict = ledger(db_client, aid)
    derived: dict = before["entries"][0]
    body: dict = {
        "request_key": str(uuid4()),
        "reason": "Synthetic direct derived-row change",
        "replacement": {
            "request_key": str(uuid4()),
            "kind": "deposit",
            "effective_date": derived["effective_date"],
            "amount": "200",
            "currency": "USD",
        }
        if edit
        else None,
    }
    response: Response = db_client.post(
        f"/api/accounts/{aid}/entries/{derived['id']}/correction?preview=true", json=body
    )
    assert response.status_code == 409
    assert "derived from purchases" in response.json()["detail"]
    assert ledger(db_client, aid) == before


def test_migration_receipt_retry_after_later_verified_reconciliation_is_read_only(
    database: Engine, db_client: TestClient
) -> None:
    """An already applied request stays idempotent after the account's funding status changes."""
    aid: str
    removed: list[int]
    aid, removed = legacy_account(database, db_client)
    plan: FundingMigration = FundingMigration(
        request_key=uuid4(),
        source_reference="Reviewed synthetic placeholders",
        remove_entry_ids=removed,
    )
    plan.expected_revision = migrate_purchase_funding(database, UUID(aid), plan)["revision"]
    migrate_purchase_funding(database, UUID(aid), plan, apply=True)
    session: Session
    with Session(database) as session:
        account: Account = session.get(Account, UUID(aid))
        account.reconstruction = account.reconstruction | {"funding_status": "reconciled"}
        session.commit()
    before: dict = ledger(db_client, aid)
    assert migrate_purchase_funding(database, UUID(aid), plan, apply=True)["already_applied"]
    assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert session.get(Account, UUID(aid)).reconstruction["funding_status"] == "reconciled"
