"""Exact cash records; account locks serialize each account's mutations."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .accounting import replay
from .accounts import DB, Currency, Identity, owned_account
from .models import LedgerEntry

router = APIRouter(prefix="/api/accounts")
Money = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8, allow_inf_nan=False)]


class EntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    effective_date: date
    currency: Currency
    note: str = Field(default="", max_length=240)

    @field_validator("effective_date")
    @classmethod
    def no_future(cls, value):
        if value > datetime.now(UTC).date():
            raise ValueError("Posted entries cannot be future dated (UTC)")
        return value


class CashInput(EntryInput):
    kind: Literal["opening_cash", "deposit", "withdrawal", "income"]
    amount: Money

    @model_validator(mode="after")
    def positive_amount(self):
        if self.kind != "opening_cash" and self.amount <= 0:
            raise ValueError("Deposits, withdrawals and income must be positive")
        return self


WireDecimal = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class SecurityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ticker: str
    exchange: str
    currency: str


class HoldingView(BaseModel):
    security: SecurityView
    quantity: WireDecimal
    cost_basis: WireDecimal | None


class EntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    effective_date: date
    amount: WireDecimal
    currency: str
    note: str
    created_by: UUID
    created_at: datetime
    security: SecurityView | None = None
    quantity: WireDecimal | None = None
    price: WireDecimal | None = None
    fees: WireDecimal = Decimal(0)
    cost_basis: WireDecimal | None = None
    realized_pnl: WireDecimal | None = None


class LedgerView(BaseModel):
    currency: str
    balance: WireDecimal
    entries: list[EntryView]
    holdings: list[HoldingView] = []


def entries_for(session, account_id):
    return list(
        session.scalars(
            select(LedgerEntry)
            .options(joinedload(LedgerEntry.security))
            .where(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.effective_date, LedgerEntry.id)
        )
    )


def fingerprint(data):
    values = data.model_dump(mode="json", exclude={"request_key"})
    # Equivalent decimal spellings have the same retry identity.
    with localcontext() as context:
        context.prec = 64
        for key, value in data.model_dump().items():
            if isinstance(value, Decimal):
                values[key] = format(value.normalize(), "f")
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


@router.get("/{account_id}/ledger", response_model=LedgerView)
def read_ledger(account_id: UUID, session: DB, actor: Identity):
    account = owned_account(session, actor, account_id)
    entries = entries_for(session, account_id)
    balance, lots, realized = replay(entries)
    securities = {e.security_id: e.security for e in entries if e.security_id}
    holdings = []
    with localcontext() as context:
        context.prec = 64
        for security_id, security_lots in lots.items():
            active = [lot for lot in security_lots if lot.quantity > 0]
            if not active:
                continue
            quantity = sum((lot.quantity for lot in active), Decimal(0))
            basis = (
                None
                if any(lot.basis is None for lot in active)
                else sum((lot.basis for lot in active), Decimal(0))
            )
            holdings.append(
                HoldingView(
                    security=SecurityView.model_validate(securities[security_id]),
                    quantity=quantity,
                    cost_basis=basis,
                )
            )
    views = [
        EntryView.model_validate(e).model_copy(update={"realized_pnl": realized.get(e.id)})
        for e in entries
    ]
    return LedgerView(
        currency=account.base_currency,
        balance=balance,
        entries=views,
        holdings=sorted(holdings, key=lambda h: (h.security.ticker, h.security.exchange)),
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
    entry = LedgerEntry(
        account_id=account_id, created_by=actor.owner_id, request_body=body, **data.model_dump()
    )
    session.add(entry)
    session.flush()
    replay(entries_for(session, account_id))
    session.commit()
    session.refresh(entry)
    return entry
