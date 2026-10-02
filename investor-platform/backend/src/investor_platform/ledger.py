"""Exact cash records; account locks serialize each account's mutations."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from .accounts import DB, Currency, Identity, owned_account
from .models import LedgerEntry

router = APIRouter(prefix="/api/accounts")
Money = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8, allow_inf_nan=False)]


class CashInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    kind: Literal["opening_cash", "deposit", "withdrawal"]
    effective_date: date
    amount: Money
    currency: Currency
    note: str = Field(default="", max_length=240)

    @field_validator("effective_date")
    @classmethod
    def no_future(cls, value):
        if value > datetime.now(UTC).date():
            raise ValueError("Posted entries cannot be future dated (UTC)")
        return value

    @model_validator(mode="after")
    def positive_amount(self):
        if self.kind != "opening_cash" and self.amount <= 0:
            raise ValueError("Deposits and withdrawals must be positive")
        return self


class EntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    effective_date: date
    amount: Decimal
    currency: str
    note: str
    created_by: UUID
    created_at: datetime


class LedgerView(BaseModel):
    currency: str
    balance: Decimal
    entries: list[EntryView]


def entries_for(session, account_id):
    return list(
        session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.effective_date, LedgerEntry.id)
        )
    )


def cash_balance(entries):
    balance = Decimal(0)
    for entry in entries:
        balance += -entry.amount if entry.kind == "withdrawal" else entry.amount
        if balance < 0:
            raise HTTPException(409, "This entry would make cash negative in the account history")
    return balance


def fingerprint(data):
    values = data.model_dump(mode="json", exclude={"request_key"})
    # Equivalent decimal spellings have the same retry identity.
    values["amount"] = format(data.amount.normalize(), "f")
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


@router.get("/{account_id}/ledger", response_model=LedgerView)
def read_ledger(account_id: UUID, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    entries = entries_for(session, account_id)
    return LedgerView(
        currency=account.base_currency,
        balance=cash_balance(entries),
        entries=[EntryView.model_validate(e) for e in entries],
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
        if existing.request_body != body:
            raise HTTPException(409, "This retry key was already used for different entries")
        return existing
    if data.currency != account.base_currency:
        raise HTTPException(422, "Entry currency must match the account")
    entries = entries_for(session, account_id)
    if data.kind == "opening_cash" and entries:
        raise HTTPException(409, "Opening cash must be the first entry; use a deposit instead")
    opening = next((e for e in entries if e.kind == "opening_cash"), None)
    if opening and data.effective_date < opening.effective_date:
        raise HTTPException(409, "Entries cannot precede the opening balance date")
    entry = LedgerEntry(
        account_id=account_id, created_by=actor.owner_id, request_body=body, **data.model_dump()
    )
    session.add(entry)
    session.flush()
    cash_balance(entries_for(session, account_id))
    session.commit()
    session.refresh(entry)
    return entry
