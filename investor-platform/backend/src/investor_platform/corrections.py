"""Preview, then append a reasoned replacement or void; never rewrite originals."""

from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from .accounting import replay
from .accounts import DB, Identity, owned_account
from .ledger import CashInput, EntryView, entries_for, fingerprint, read_ledger
from .models import LedgerCorrection, LedgerEntry
from .trades import TradeInput, build_trade

router = APIRouter(prefix="/api/accounts")
Replacement = Annotated[CashInput | TradeInput, Field(discriminator="kind")]


class CorrectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    replacement: Replacement | None
    expected_revision: str | None = None


@router.post("/{account_id}/entries/{entry_id}/correction")
def correct(
    account_id: UUID,
    entry_id: int,
    data: CorrectionInput,
    session: DB,
    actor: Identity,
    preview: bool = False,
):
    account = owned_account(session, actor, account_id, lock=True)
    body = fingerprint(data)
    existing = session.scalar(
        select(LedgerCorrection).where(
            LedgerCorrection.account_id == account_id,
            LedgerCorrection.request_key == data.request_key,
        )
    )
    if existing:
        if existing.request_body != body or existing.original_id != entry_id:
            raise HTTPException(409, "This retry key was already used for a different correction")
        return {"id": existing.id}
    entries = entries_for(session, account_id)
    original = next((e for e in entries if e.id == entry_id), None)
    if original is None:
        raise HTTPException(409, "Entry is no longer active in this account; reload records")
    revision = sha256(",".join(str(e.id) for e in entries).encode()).hexdigest()
    if not preview and data.expected_revision != revision:
        raise HTTPException(
            409, "Records changed or were not previewed; preview the correction again"
        )
    previous_balance = replay(entries)[0]
    replacement = None
    if data.replacement is not None:
        values = data.replacement.model_copy(update={"request_key": data.request_key})
        if values.currency != account.base_currency:
            raise HTTPException(422, "Replacement currency must match the account")
        if isinstance(values, TradeInput):
            replacement = build_trade(account, values, session, actor, fingerprint(values))
        else:
            replacement = LedgerEntry(
                account_id=account_id,
                created_by=actor.owner_id,
                request_body=fingerprint(values),
                **values.model_dump(),
            )
        session.add(replacement)
        session.flush()
    correction = LedgerCorrection(
        account_id=account_id,
        original_id=entry_id,
        replacement_id=replacement.id if replacement else None,
        reason=data.reason,
        created_by=actor.owner_id,
        request_key=data.request_key,
        request_body=body,
    )
    session.add(correction)
    session.flush()
    replay(entries_for(session, account_id))
    if preview:
        projected = read_ledger(account_id, session, actor)
        result = {
            "revision": revision,
            "previous_balance": format(previous_balance, "f"),
            "balance": format(projected.balance, "f"),
            "holdings": projected.holdings,
            "replacement": EntryView.model_validate(replacement) if replacement else None,
        }
        session.rollback()
        return result
    session.commit()
    return {"id": correction.id}
