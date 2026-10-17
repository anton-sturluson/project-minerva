"""Exact cash records; account locks serialize each account's mutations."""

import json
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .accounting import replay
from .accounts import DB, Identity, owned_account
from .domain import ACCOUNTING_PRECISION, MARKET_TIMEZONE, Currency, EntryKind, IncomeKind
from .models import LedgerCorrection, LedgerEntry, Security

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
        if value > datetime.now(MARKET_TIMEZONE).date():
            raise ValueError("Posted entries cannot be future dated (New York)")
        return value


class CashInput(EntryInput):
    kind: Literal[
        EntryKind.OPENING_CASH,
        EntryKind.DEPOSIT,
        EntryKind.WITHDRAWAL,
        EntryKind.INCOME,
        EntryKind.EXPENSE,
    ]
    amount: Money
    income_kind: IncomeKind | None = None
    income_security_id: UUID | None = None
    accrual_date: date | None = None

    @model_validator(mode="after")
    def positive_amount(self):
        if self.kind != EntryKind.OPENING_CASH and self.amount <= 0:
            raise ValueError("Cash entries other than opening cash must be positive")
        if self.kind != EntryKind.INCOME and any(
            value is not None
            for value in (self.income_kind, self.income_security_id, self.accrual_date)
        ):
            raise ValueError("Income attribution is only valid for investment income")
        if self.income_kind == IncomeKind.DIVIDEND:
            if self.income_security_id is None or self.accrual_date is None:
                raise ValueError("Dividends require a security and ex-dividend date")
            if self.accrual_date > self.effective_date:
                raise ValueError("Ex-dividend date must be on or before the cash payment date")
        elif self.income_kind in {IncomeKind.INTEREST, IncomeKind.OTHER}:
            if self.accrual_date is not None:
                raise ValueError("Only dividends use an ex-dividend date")
        elif self.income_security_id is not None or self.accrual_date is not None:
            raise ValueError("Classify income before linking a security")
        return self


WireDecimal = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class SecurityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ticker: str
    exchange: str
    currency: Currency
    market_identity: dict | None = Field(default=None, exclude=True)


class HoldingView(BaseModel):
    security: SecurityView
    quantity: WireDecimal
    cost_basis: WireDecimal | None


class EntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: EntryKind
    effective_date: date
    amount: WireDecimal
    currency: Currency
    note: str
    created_by: UUID
    created_at: datetime
    security: SecurityView | None = None
    income_kind: IncomeKind | None = None
    income_security: SecurityView | None = None
    accrual_date: date | None = None
    quantity: WireDecimal | None = None
    price: WireDecimal | None = None
    fees: WireDecimal = Decimal(0)
    cost_basis: WireDecimal | None = None
    realized_pnl: WireDecimal | None = None


class CorrectionView(BaseModel):
    id: int
    original: EntryView
    replacement: EntryView | None
    reason: str
    created_by: UUID
    created_at: datetime


class LedgerView(BaseModel):
    currency: Currency
    balance: WireDecimal
    entries: list[EntryView]
    holdings: list[HoldingView] = []
    corrections: list[CorrectionView] = []


def funding_purchase_key(entry: LedgerEntry) -> UUID | None:
    """Read explicit generated-deposit provenance without guessing from notes."""
    if entry.kind != EntryKind.DEPOSIT:
        return None
    try:
        body: dict = json.loads(entry.request_body)
        if isinstance(body, dict) and body.get("cash_method") == "purchase_shortfall":
            return UUID(body["purchase_request_key"])
    except (ValueError, TypeError, KeyError):
        pass
    return None


def purchase_funding_order(
    entry: LedgerEntry, by_key: dict[str, LedgerEntry], roots: dict[int, int]
) -> tuple[date, int, int]:
    """Place explicitly anchored inferred deposits immediately before their original purchase."""
    reference: UUID | None = funding_purchase_key(entry)
    purchase: LedgerEntry | None = by_key.get(str(reference)) if reference is not None else None
    if (
        purchase is not None
        and purchase.kind == EntryKind.BUY
        and purchase.effective_date == entry.effective_date
    ):
        return entry.effective_date, roots.get(purchase.id, purchase.id), -1
    return entry.effective_date, roots.get(entry.id, entry.id), 0


def ledger_snapshot(session, account_id):
    # One SQL snapshot prevents a concurrent correction from exposing both old and new entries.
    rows = session.execute(
        select(LedgerEntry, LedgerCorrection)
        .outerjoin(LedgerCorrection, LedgerCorrection.original_id == LedgerEntry.id)
        .options(joinedload(LedgerEntry.security), joinedload(LedgerEntry.income_security))
        .where(LedgerEntry.account_id == account_id)
    ).all()
    entries = [entry for entry, _ in rows]
    corrections = sorted((c for _, c in rows if c is not None), key=lambda c: c.id)
    superseded = {c.original_id for c in corrections}
    roots = {}
    for c in corrections:
        if c.replacement_id is not None:
            roots[c.replacement_id] = roots.get(c.original_id, c.original_id)
    # A replacement retains the original same-day position, including through repeated corrections.
    by_key: dict[str, LedgerEntry] = {str(entry.request_key): entry for entry in entries}
    active = sorted(
        (e for e in entries if e.id not in superseded),
        key=lambda e: purchase_funding_order(e, by_key, roots),
    )
    return active, {e.id: e for e in entries}, corrections


def entries_for(session, account_id):
    return ledger_snapshot(session, account_id)[0]


type RequestValue = (
    str | int | float | Decimal | bool | None | list[RequestValue] | dict[str, RequestValue]
)
type RequestRecord = dict[str, RequestValue]


def normalize_request_body(body: str) -> str:
    """Canonicalize effective fields, including legacy nested correction amounts."""
    values: RequestRecord = json.loads(body)
    decimal_fields: frozenset[str] = frozenset(
        {"amount", "quantity", "price", "fees", "cost_basis"}
    )

    def normalize(value: RequestRecord) -> None:
        """Remove retry-only keys and normalize money without changing notes or dates."""
        value.pop("request_key", None)
        key: str
        nested: RequestValue
        for key, nested in list(value.items()):
            if key in {"income_kind", "income_security_id", "accrual_date"} and nested is None:
                value.pop(key)
            elif isinstance(nested, dict):
                normalize(nested)
            elif key in decimal_fields and nested is not None:
                value[key] = format(Decimal(str(nested)).normalize(), "f")

    context: Context
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        normalize(values)
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def fingerprint(data: BaseModel) -> str:
    """Identify effective request values independent of nested decimal spelling."""
    return normalize_request_body(data.model_dump_json())


def ledger_view(entries, currency):
    """Build the active ledger view once, shared by reads and correction previews."""
    balance, lots, realized = replay(entries)
    securities = {e.security_id: e.security for e in entries if e.security_id}
    holdings = []
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
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
        currency=currency,
        balance=balance,
        entries=views,
        holdings=sorted(holdings, key=lambda h: (h.security.ticker, h.security.exchange)),
    )


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
    from .purchase_funding import sync_canonical_funding

    try:
        sync_canonical_funding(session, account, actor, data.request_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    replay(entries_for(session, account_id))
    session.commit()
    session.refresh(entry)
    return entry


def build_cash(account, data, session, actor, body):
    if data.currency != account.base_currency:
        raise HTTPException(422, "Entry currency must match the account")
    if data.income_security_id is not None:
        security = session.scalar(
            select(Security).where(
                Security.id == data.income_security_id,
                Security.workspace_id == actor.workspace_id,
            )
        )
        if security is None:
            raise HTTPException(404, "Income security not found")
    return LedgerEntry(
        account_id=account.id, created_by=actor.owner_id, request_body=body, **data.model_dump()
    )
