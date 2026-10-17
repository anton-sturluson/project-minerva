"""Read active ledger state and canonical request identities."""

import json
from collections.abc import Sequence
from datetime import date
from decimal import Context, Decimal, localcontext
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Row, select
from sqlalchemy.orm import Session, joinedload

from investor_platform.domain import (
    ACCOUNTING_PRECISION,
    Currency,
    EntryKind,
)
from investor_platform.ledger.accounting import Lot, replay
from investor_platform.ledger.schemas import (
    EntryView,
    HoldingView,
    LedgerRecord,
    LedgerValue,
    LedgerView,
    SecurityView,
)
from investor_platform.models import LedgerCorrection, LedgerEntry, Security


def funding_purchase_key(entry: LedgerEntry) -> UUID | None:
    """Read explicit generated-deposit provenance without guessing from notes."""
    if entry.kind != EntryKind.DEPOSIT:
        return None
    try:
        body: LedgerRecord = json.loads(entry.request_body)
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


def ledger_snapshot(
    session: Session, account_id: UUID
) -> tuple[list[LedgerEntry], dict[int, LedgerEntry], list[LedgerCorrection]]:
    """Read active entries and correction provenance from one database snapshot."""
    # One SQL snapshot prevents a concurrent correction from exposing both old and new entries.
    rows: Sequence[Row[tuple[LedgerEntry, LedgerCorrection | None]]] = session.execute(
        select(LedgerEntry, LedgerCorrection)
        .outerjoin(LedgerCorrection, LedgerCorrection.original_id == LedgerEntry.id)
        .options(joinedload(LedgerEntry.security), joinedload(LedgerEntry.income_security))
        .where(LedgerEntry.account_id == account_id)
    ).all()
    entries: list[LedgerEntry] = [entry for entry, _ in rows]
    corrections: list[LedgerCorrection] = sorted(
        (c for _, c in rows if c is not None), key=lambda c: c.id
    )
    superseded: set[int] = {c.original_id for c in corrections}
    roots: dict[int, int] = {}
    c: LedgerCorrection
    for c in corrections:
        if c.replacement_id is not None:
            roots[c.replacement_id] = roots.get(c.original_id, c.original_id)
    # A replacement retains the original same-day position, including through repeated corrections.
    by_key: dict[str, LedgerEntry] = {str(entry.request_key): entry for entry in entries}
    active: list[LedgerEntry] = sorted(
        (e for e in entries if e.id not in superseded),
        key=lambda e: purchase_funding_order(e, by_key, roots),
    )
    return active, {e.id: e for e in entries}, corrections


def active_entries_for_account(session: Session, account_id: UUID) -> list[LedgerEntry]:
    """Read chronologically ordered entries after applying append-only corrections."""
    return ledger_snapshot(session, account_id)[0]


def normalize_request_body(body: str) -> str:
    """Canonicalize effective fields, including legacy nested correction amounts."""
    values: LedgerRecord = json.loads(body)
    decimal_fields: frozenset[str] = frozenset(
        {"amount", "quantity", "price", "fees", "cost_basis"}
    )

    def normalize(value: LedgerRecord) -> None:
        """Remove retry-only keys and normalize money without changing notes or dates."""
        value.pop("request_key", None)
        key: str
        nested: LedgerValue
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


def ledger_view(entries: Sequence[LedgerEntry], currency: Currency | str) -> LedgerView:
    """Build the active ledger view once, shared by reads and correction previews."""
    balance: Decimal
    lots: dict[UUID, list[Lot]]
    realized: dict[int, Decimal | None]
    balance, lots, realized = replay(entries)
    securities: dict[UUID, Security | None] = {
        e.security_id: e.security for e in entries if e.security_id
    }
    holdings: list[HoldingView] = []
    context: Context
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        security_id: UUID
        security_lots: list[Lot]
        for security_id, security_lots in lots.items():
            active: list[Lot] = [lot for lot in security_lots if lot.quantity > 0]
            if not active:
                continue
            quantity: Decimal = sum((lot.quantity for lot in active), Decimal(0))
            basis: Decimal | None = (
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
    views: list[EntryView] = [
        EntryView.model_validate(e).model_copy(update={"realized_pnl": realized.get(e.id)})
        for e in entries
    ]
    return LedgerView(
        currency=currency,
        balance=balance,
        entries=views,
        holdings=sorted(holdings, key=lambda h: (h.security.ticker, h.security.exchange)),
    )
