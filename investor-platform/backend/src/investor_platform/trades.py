from decimal import Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field, StringConstraints, field_validator, model_validator
from sqlalchemy import select

from .accounting import replay
from .accounts import DB, Identity, owned_account
from .ledger import EntryInput, EntryView, Money, entries_for, fingerprint
from .models import LedgerEntry, Security

router = APIRouter(prefix="/api/accounts")
Quantity = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8, allow_inf_nan=False)]


class TradeInput(EntryInput):
    kind: Literal["opening_position", "buy", "sell"]
    ticker: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,19}$"
        ),
    ]
    exchange: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9][A-Z0-9_\-]{1,11}$"
        ),
    ]
    quantity: Quantity
    price: Quantity | None = None
    fees: Money = Decimal(0)
    cost_basis: Money | None = None

    @field_validator("ticker", "exchange", mode="before")
    @classmethod
    def normalize_identity(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def valid_trade(self):
        if self.kind == "opening_position":
            if self.price is not None or self.fees != 0:
                raise ValueError(
                    "Opening positions use optional total cost basis, not a price or fee"
                )
        elif self.price is None or self.cost_basis is not None:
            raise ValueError(
                "Trades require a price and cannot override their calculated cost basis"
            )
        return self


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
        if existing.request_body != body:
            raise HTTPException(409, "This retry key was already used for different entries")
        return existing
    if data.currency != account.base_currency:
        raise HTTPException(422, "Security currency must match the account")
    security = session.scalar(
        select(Security).where(
            Security.workspace_id == actor.workspace_id,
            Security.ticker == data.ticker,
            Security.exchange == data.exchange,
            Security.currency == data.currency,
        )
    )
    if security is None:
        security = Security(
            workspace_id=actor.workspace_id,
            ticker=data.ticker,
            exchange=data.exchange,
            currency=data.currency,
        )
        session.add(security)
        session.flush()
    entries = entries_for(session, account_id)
    if data.kind == "opening_position" and any(e.security_id == security.id for e in entries):
        raise HTTPException(
            409, "Opening positions must be recorded before trades in that security"
        )
    with localcontext() as context:
        context.prec = 64
        amount = Decimal(0)
        if data.kind != "opening_position":
            gross = data.quantity * data.price
            amount = gross + data.fees if data.kind == "buy" else gross - data.fees
            if amount < 0:
                raise HTTPException(422, "Sale fees cannot exceed proceeds")
    entry = LedgerEntry(
        account_id=account_id,
        security_id=security.id,
        created_by=actor.owner_id,
        request_body=body,
        amount=amount,
        **data.model_dump(exclude={"amount", "ticker", "exchange"}),
    )
    session.add(entry)
    session.flush()
    replay(entries_for(session, account_id))
    session.commit()
    session.refresh(entry)
    return entry
