"""Account cash, trade and ledger HTTP routes."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from investor_platform.accounts import DB, Identity, owned_account
from investor_platform.domain import EntryKind
from investor_platform.ledger.accounting import replay
from investor_platform.ledger.commands import build_cash, build_trade
from investor_platform.ledger.schemas import (
    CashInput,
    CorrectionView,
    EntryView,
    LedgerView,
    TradeInput,
)
from investor_platform.ledger.state import (
    entries_for,
    fingerprint,
    ledger_snapshot,
    ledger_view,
    normalize_request_body,
)
from investor_platform.models import LedgerEntry

router = APIRouter(prefix="/api/accounts")


@router.get("/{account_id}/ledger", response_model=LedgerView)
def read_ledger(account_id: UUID, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    entries, all_entries, audit = ledger_snapshot(session, account_id)
    corrections = [
        CorrectionView(
            id=c.id,
            original=EntryView.model_validate(all_entries[c.original_id]),
            replacement=EntryView.model_validate(all_entries[c.replacement_id])
            if c.replacement_id
            else None,
            reason=c.reason,
            created_by=c.created_by,
            created_at=c.created_at,
        )
        for c in audit
    ]
    return ledger_view(entries, account.base_currency).model_copy(
        update={"corrections": corrections}
    )


@router.post("/{account_id}/cash", response_model=EntryView, status_code=201)
def record_cash(account_id: UUID, data: CashInput, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id, lock=True)
    body = fingerprint(data)
    existing = session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.account_id == account_id, LedgerEntry.request_key == data.request_key
        )
    )
    if existing:
        if normalize_request_body(existing.request_body) != body:
            raise HTTPException(409, "This retry key was already used for different entries")
        return existing
    if data.currency != account.base_currency:
        raise HTTPException(422, "Entry currency must match the account")
    entries = entries_for(session, account_id)
    if data.kind == EntryKind.OPENING_CASH and entries:
        raise HTTPException(409, "Opening cash must be the first entry; use a deposit instead")
    entry = build_cash(account, data, session, actor, body)
    session.add(entry)
    session.flush()
    from investor_platform.ledger.purchase_funding import sync_canonical_funding

    try:
        sync_canonical_funding(session, account, actor, data.request_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    replay(entries_for(session, account_id))
    session.commit()
    session.refresh(entry)
    return entry


@router.post("/{account_id}/trades", response_model=EntryView, status_code=201)
def record_trade(account_id: UUID, data: TradeInput, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id, lock=True)
    body = fingerprint(data)
    existing = session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.account_id == account_id, LedgerEntry.request_key == data.request_key
        )
    )
    if existing:
        if normalize_request_body(existing.request_body) != body:
            raise HTTPException(409, "This retry key was already used for different entries")
        return existing
    entry = build_trade(account, data, session, actor, body)
    entries = entries_for(session, account_id)
    if data.kind == EntryKind.OPENING_POSITION and any(
        e.security_id == entry.security_id for e in entries
    ):
        raise HTTPException(
            409, "Opening positions must be recorded before trades in that security"
        )
    session.add(entry)
    session.flush()
    from investor_platform.ledger.purchase_funding import sync_canonical_funding

    try:
        sync_canonical_funding(session, account, actor, data.request_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    replay(entries_for(session, account_id))
    session.commit()
    session.refresh(entry)
    return entry
