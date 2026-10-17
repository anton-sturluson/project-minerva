"""Preview and apply reviewed purchase funding with an append-only correction history."""

import hashlib
import json
from decimal import Decimal, localcontext
from typing import TypedDict
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform.accounts import owned_account
from investor_platform.db import LOCAL_OWNER, LOCAL_WORKSPACE, Actor
from investor_platform.domain import ACCOUNTING_PRECISION, Currency, EntryKind, FundingStatus
from investor_platform.ledger.purchase_shortfalls import (
    FUNDING_WARNING,
    CashMovement,
    InferredDepositInput,
    PurchaseShortfall,
    infer_purchase_shortfalls,
    inferred_deposit,
)
from investor_platform.ledger.schemas import LedgerView
from investor_platform.ledger.state import (
    entries_for,
    fingerprint,
    funding_purchase_key,
    ledger_view,
)
from investor_platform.models import Account, LedgerCorrection, LedgerEntry


class FundingMigration(BaseModel):
    """Explicit reviewed cash records to void before inferring purchase shortfalls."""

    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    source_reference: str = Field(min_length=1, max_length=240)
    remove_entry_ids: list[int] = Field(max_length=5000)
    expected_revision: str | None = None

    @model_validator(mode="after")
    def unique_records(self) -> "FundingMigration":
        """Require an unambiguous list of reviewed cash records."""
        if len(set(self.remove_entry_ids)) != len(self.remove_entry_ids):
            raise ValueError("Cash records to remove must be unique")
        return self


class DepositPreview(TypedDict):
    """Review one inferred deposit beside the purchase that needs it."""

    purchase_entry_id: int
    effective_date: str
    amount: str
    request_key: str


class FundingMigrationResult(TypedDict):
    """Financial preview and persistent retry receipt for a funding migration."""

    account_id: str
    revision: str
    applied: bool
    already_applied: bool
    removed_entry_ids: list[int]
    deposits: list[DepositPreview]
    inferred_deposits_total: str
    cash: str
    holdings_unchanged: bool
    funding_status: str
    new_entry_ids: list[int]
    previous_opening_cash: str | None


def funding_revision(account: Account, entries: list[LedgerEntry]) -> str:
    """Fingerprint all active records and account provenance before a reviewed migration."""
    rows: list[dict[str, str | None]] = [
        {
            column.name: None
            if getattr(entry, column.name) is None
            else str(getattr(entry, column.name))
            for column in LedgerEntry.__table__.columns
        }
        for entry in entries
    ]
    body: str = json.dumps(
        {
            "account": str(account.id),
            "currency": account.base_currency,
            "reconstruction": account.reconstruction,
            "entries": rows,
        },
        sort_keys=True,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def migrate_purchase_funding(
    engine: Engine,
    account_id: UUID,
    plan: FundingMigration,
    *,
    apply: bool = False,
    actor: Actor | None = None,
) -> FundingMigrationResult:
    """Void only reviewed placeholders and add exact dated funding, retaining every trade."""
    actor = actor or Actor(LOCAL_OWNER, LOCAL_WORKSPACE)
    body: dict = plan.model_dump(mode="json", exclude={"expected_revision"})
    digest: str = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    key: str = str(plan.request_key)
    with Session(engine) as session, localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        account: Account = owned_account(session, actor, account_id, lock=True)
        if not account.reconstruction:
            raise ValueError("Purchase funding migration requires an imported portfolio")
        receipts: dict = account.reconstruction.get("funding_migrations", {})
        previous: dict | None = receipts.get(key)
        if previous is not None:
            if previous["digest"] != digest:
                raise ValueError("This migration key was already used for a different plan")
            return previous["result"] | {"already_applied": True}
        if (
            account.reconstruction.get("funding_status", FundingStatus.INFERRED)
            != FundingStatus.INFERRED
        ):
            raise ValueError(
                "Verified cash history cannot be replaced by inferred purchase funding"
            )
        before: list[LedgerEntry] = entries_for(session, account_id)
        revision: str = funding_revision(account, before)
        if apply and plan.expected_revision != revision:
            raise ValueError("Records changed or were not previewed; preview this plan again")
        removed: set[int] = set(plan.remove_entry_ids)
        by_id: dict[int, LedgerEntry] = {entry.id: entry for entry in before}
        if not removed.issubset(by_id):
            raise ValueError("Review only currently active cash records for removal")
        entry: LedgerEntry
        for entry in before:
            if entry.kind == EntryKind.OPENING_CASH:
                opening: str | None = account.reconstruction.get("opening_cash")
                if opening is None or Decimal(opening) != entry.amount:
                    raise ValueError(
                        "Opening cash is not an explicitly inferred import placeholder"
                    )
                if entry.id not in removed:
                    raise ValueError("Explicitly review the opening cash placeholder for removal")
            if entry.id in removed and entry.kind not in {
                EntryKind.OPENING_CASH,
                EntryKind.DEPOSIT,
            }:
                raise ValueError(
                    "Only explicitly reviewed opening cash or deposit records may be removed"
                )
        old: LedgerView = ledger_view(before, account.base_currency)
        entry_id: int
        for entry_id in plan.remove_entry_ids:
            session.add(
                LedgerCorrection(
                    account_id=account_id,
                    original_id=entry_id,
                    replacement_id=None,
                    created_by=actor.owner_id,
                    request_key=uuid5(plan.request_key, f"void:{entry_id}"),
                    request_body=json.dumps({"funding_migration": key, "digest": digest}),
                    reason="Replace reviewed funding placeholder: " + plan.source_reference[:180],
                )
            )
        session.flush()
        previous_opening_cash: str | None = account.reconstruction.get("opening_cash")
        account.reconstruction = {
            field: value
            for field, value in account.reconstruction.items()
            if field != "opening_cash"
        } | {
            "cash_method": "purchase_shortfall",
            "funding_status": FundingStatus.INFERRED,
            "warning": FUNDING_WARNING,
        }
        sync_canonical_funding(session, account, actor, plan.request_key)
        after: list[LedgerEntry] = entries_for(session, account_id)
        updated: LedgerView = ledger_view(after, account.base_currency)
        purchases: dict[UUID, LedgerEntry] = {
            entry.request_key: entry for entry in after if entry.kind == EntryKind.BUY
        }
        generated: list[LedgerEntry] = [entry for entry in after if funding_purchase_key(entry)]
        added: list[LedgerEntry] = [entry for entry in generated if entry.id not in by_id]
        previews: list[DepositPreview] = [
            DepositPreview(
                purchase_entry_id=purchases[funding_purchase_key(entry)].id,
                effective_date=str(entry.effective_date),
                amount=str(entry.amount),
                request_key=str(entry.request_key),
            )
            for entry in generated
        ]
        if updated.holdings != old.holdings:
            raise ValueError("Funding migration cannot change holdings or cost basis")
        result: FundingMigrationResult = {
            "account_id": str(account_id),
            "revision": revision,
            "applied": apply,
            "already_applied": False,
            "removed_entry_ids": plan.remove_entry_ids,
            "deposits": previews,
            "inferred_deposits_total": str(sum((item.amount for item in generated), Decimal(0))),
            "cash": str(updated.balance),
            "holdings_unchanged": True,
            "funding_status": FundingStatus.INFERRED,
            "new_entry_ids": [entry.id for entry in added] if apply else [],
            "previous_opening_cash": previous_opening_cash,
        }
        if not apply:
            session.rollback()
            return result
        account.reconstruction = account.reconstruction | {
            "cash_method": "purchase_shortfall",
            "funding_status": FundingStatus.INFERRED,
            "warning": FUNDING_WARNING,
            "funding_migrations": receipts
            | {key: {"digest": digest, "plan": body, "result": result}},
        }
        session.commit()
        return result


def sync_canonical_funding(
    session: Session, account: Account, actor: Actor, operation_key: UUID
) -> None:
    """Maintain inferred funding atomically after a locked account's ledger mutation.

    Recorded cash rows remain unchanged. Generated rows are derived from the active
    original records, so backdated trades and actual deposits can change or remove
    earlier assumptions without losing their correction history.
    """
    if (
        not account.reconstruction
        or account.reconstruction.get("cash_method") != "purchase_shortfall"
        or account.reconstruction.get("funding_status", FundingStatus.INFERRED)
        != FundingStatus.INFERRED
    ):
        return
    active: list[LedgerEntry] = entries_for(session, account.id)
    generated: dict[UUID, LedgerEntry] = {}
    retained: list[LedgerEntry] = []
    entry: LedgerEntry
    for entry in active:
        reference: UUID | None = funding_purchase_key(entry)
        if reference is None:
            retained.append(entry)
        elif reference in generated:
            raise ValueError("Multiple generated funding records refer to the same purchase")
        else:
            generated[reference] = entry
    movements: list[CashMovement] = [
        CashMovement(entry.effective_date, EntryKind(entry.kind), entry.amount)
        for entry in retained
    ]
    desired: dict[UUID, InferredDepositInput] = {}
    shortfall: PurchaseShortfall
    for shortfall in infer_purchase_shortfalls(movements):
        purchase: LedgerEntry = retained[shortfall.index]
        desired[purchase.request_key] = inferred_deposit(
            shortfall, purchase.request_key, Currency(account.base_currency)
        )
    reference: UUID
    for reference in sorted(generated.keys() | desired.keys(), key=str):
        old: LedgerEntry | None = generated.get(reference)
        replacement_data: InferredDepositInput | None = desired.get(reference)
        if (
            old is not None
            and replacement_data is not None
            and old.amount == replacement_data.amount
            and old.effective_date == replacement_data.effective_date
            and old.currency == replacement_data.currency
        ):
            continue
        replacement: LedgerEntry | None = None
        if replacement_data is not None:
            replacement_data.request_key = uuid5(operation_key, f"purchase-funding:{reference}")
            replacement = LedgerEntry(
                account_id=account.id,
                created_by=actor.owner_id,
                request_body=fingerprint(replacement_data),
                **replacement_data.model_dump(exclude={"cash_method", "purchase_request_key"}),
            )
            session.add(replacement)
            session.flush()
        if old is not None:
            session.add(
                LedgerCorrection(
                    account_id=account.id,
                    original_id=old.id,
                    replacement_id=replacement.id if replacement is not None else None,
                    reason="Recalculate inferred purchase funding after a ledger change",
                    created_by=actor.owner_id,
                    request_key=uuid5(operation_key, f"purchase-funding-void:{old.id}"),
                    request_body=json.dumps(
                        {"cash_method": "purchase_shortfall", "operation": str(operation_key)}
                    ),
                )
            )
    session.flush()
