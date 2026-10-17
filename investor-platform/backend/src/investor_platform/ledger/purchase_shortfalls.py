"""Infer only dated purchase shortfalls from preceding recorded cash movements."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field

from investor_platform.domain import ACCOUNTING_PRECISION, Currency, EntryKind
from investor_platform.ledger.schemas import CashInput

FUNDING_WARNING: str = (
    "Incomplete transaction reconstruction for testing. Opening shares and dated purchase funding "
    "are inferred minimums, not broker balances. Fees, cash flows, distributions and "
    "corporate actions are "
    "incomplete. Holdings, trade statistics and portfolio returns are provisional."
)


@dataclass(frozen=True)
class CashMovement:
    """One cash event in the preserved source or active-ledger order."""

    effective_date: date
    kind: EntryKind
    amount: Decimal


@dataclass(frozen=True)
class PurchaseShortfall:
    """Cash required immediately before one purchase, without future borrowing."""

    index: int
    effective_date: date
    amount: Decimal


class InferredDepositInput(CashInput):
    """An exact purchase funding assumption with a stable purchase-order anchor."""

    amount: Annotated[Decimal, Field(gt=0, max_digits=48, decimal_places=16, allow_inf_nan=False)]
    cash_method: Literal["purchase_shortfall"] = "purchase_shortfall"
    purchase_request_key: UUID


def infer_purchase_shortfalls(movements: list[CashMovement]) -> list[PurchaseShortfall]:
    """Use preceding cash first; infer deposits only when a buy would exhaust it."""
    cash: Decimal = Decimal(0)
    previous: date | None = None
    result: list[PurchaseShortfall] = []
    index: int
    movement: CashMovement
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        for index, movement in enumerate(movements):
            if previous is not None and movement.effective_date < previous:
                raise ValueError("Funding movements must preserve chronological source order")
            if not movement.amount.is_finite() or movement.amount < 0:
                raise ValueError("Funding movements require finite nonnegative cash amounts")
            previous = movement.effective_date
            if movement.kind == EntryKind.OPENING_CASH:
                raise ValueError(
                    "Review and remove the opening cash placeholder before inferring funding"
                )
            if movement.kind in {EntryKind.DEPOSIT, EntryKind.SELL, EntryKind.INCOME}:
                cash += movement.amount
            elif movement.kind == EntryKind.BUY:
                if movement.amount > cash:
                    result.append(
                        PurchaseShortfall(index, movement.effective_date, movement.amount - cash)
                    )
                    cash = movement.amount
                cash -= movement.amount
            elif movement.kind in {EntryKind.WITHDRAWAL, EntryKind.EXPENSE}:
                cash -= movement.amount
                if cash < 0:
                    raise ValueError(
                        "Recorded cash outflows need funding evidence before this purchase"
                    )
    return result


def inferred_deposit(
    shortfall: PurchaseShortfall, purchase_request_key: UUID, currency: Currency
) -> InferredDepositInput:
    """Create one retry-stable deposit without claiming a broker-recorded contribution."""
    return InferredDepositInput(
        request_key=uuid5(purchase_request_key, "purchase-shortfall"),
        kind=EntryKind.DEPOSIT,
        amount=shortfall.amount,
        effective_date=shortfall.effective_date,
        currency=currency,
        purchase_request_key=purchase_request_key,
        note="INFERRED purchase funding shortfall; historical deposit timing is assumed.",
    )
