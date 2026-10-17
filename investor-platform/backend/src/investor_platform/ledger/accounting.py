"""Deterministic chronological replay and FIFO lot allocation."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from uuid import UUID

from fastapi import HTTPException

from investor_platform.domain import ACCOUNTING_PRECISION, IN_KIND_ENTRIES, EntryKind
from investor_platform.models import LedgerEntry

UNIT: Decimal = Decimal("0.0000000000000001")


@dataclass
class Lot:
    """Remaining recorded shares and their optional FIFO cost basis."""

    quantity: Decimal
    basis: Decimal | None


@dataclass
class ReplayState:
    """Apply ordered entries once for full-ledger and daily performance replay."""

    cash: Decimal = Decimal(0)
    lots: dict[UUID, list[Lot]] = field(default_factory=dict)
    realized: dict[int, Decimal | None] = field(default_factory=dict)
    seen: set[UUID] = field(default_factory=set)
    opening_date: date | None = None
    entry_count: int = 0

    def apply(self, entry: LedgerEntry, *, day_end: bool) -> None:
        """Apply one entry, checking cash only after its final same-day movement."""
        with localcontext() as context:
            context.prec = ACCOUNTING_PRECISION
            if entry.kind == EntryKind.OPENING_CASH:
                if self.opening_date is not None:
                    raise HTTPException(409, "Only one opening cash entry is allowed")
                if self.entry_count:
                    raise HTTPException(409, "Opening cash must be the first entry")
                self.opening_date = entry.effective_date
            if self.opening_date and entry.effective_date < self.opening_date:
                raise HTTPException(409, "Entries cannot precede the opening balance date")
            if entry.kind in {EntryKind.OPENING_CASH, EntryKind.DEPOSIT, EntryKind.INCOME}:
                self.cash += entry.amount
            elif entry.kind in {EntryKind.WITHDRAWAL, EntryKind.EXPENSE, EntryKind.BUY}:
                self.cash -= entry.amount
            elif entry.kind == EntryKind.SELL:
                self.cash += entry.amount
            if day_end and self.cash < 0:
                raise HTTPException(
                    409, "This entry would make cash negative in the account history"
                )
            if entry.kind in IN_KIND_ENTRIES or entry.kind == EntryKind.BUY:
                if entry.kind == EntryKind.OPENING_POSITION and entry.security_id in self.seen:
                    raise HTTPException(
                        409, "An opening position must precede all trades in that security"
                    )
                self.lots.setdefault(entry.security_id, []).append(
                    Lot(
                        entry.quantity,
                        entry.cost_basis if entry.kind in IN_KIND_ENTRIES else entry.amount,
                    )
                )
            elif entry.kind == EntryKind.SELL:
                remaining: Decimal = entry.quantity
                basis: Decimal = Decimal(0)
                unknown: bool = False
                lot: Lot
                for lot in self.lots.get(entry.security_id, []):
                    take: Decimal = min(remaining, lot.quantity)
                    if take == 0:
                        continue
                    if lot.basis is None:
                        unknown = True
                    else:
                        allocated: Decimal = (
                            lot.basis
                            if take == lot.quantity
                            else (lot.basis * take / lot.quantity).quantize(
                                UNIT, rounding=ROUND_HALF_EVEN
                            )
                        )
                        basis += allocated
                        lot.basis -= allocated
                    remaining -= take
                    lot.quantity -= take
                    if remaining == 0:
                        break
                if remaining:
                    raise HTTPException(
                        409, "This sale would leave negative shares in the account history"
                    )
                self.realized[entry.id] = None if unknown else entry.amount - basis
            if entry.security_id is not None:
                self.seen.add(entry.security_id)
            self.entry_count += 1


def replay(
    entries: Sequence[LedgerEntry],
) -> tuple[Decimal, dict[UUID, list[Lot]], dict[int, Decimal | None]]:
    """Replay immutable source entries without changing source quantities or basis."""
    state: ReplayState = ReplayState()
    index: int
    entry: LedgerEntry
    for index, entry in enumerate(entries):
        state.apply(
            entry,
            day_end=index + 1 == len(entries)
            or entries[index + 1].effective_date != entry.effective_date,
        )
    return state.cash, state.lots, state.realized
