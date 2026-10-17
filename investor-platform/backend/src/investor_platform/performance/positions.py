"""Group recorded position episodes and required market-data windows."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from investor_platform.domain import EntryKind
from investor_platform.ledger.accounting import Lot, replay
from investor_platform.market_data import listings as market_listings
from investor_platform.models import LedgerEntry, Security

ZERO: Decimal = Decimal(0)


def position_episodes(entries: Sequence[LedgerEntry]) -> tuple[list[list[LedgerEntry]], int]:
    """Group each security from flat to flat, retaining buys and partial exits."""
    active: dict[UUID, list[LedgerEntry]] = {}
    quantities: dict[UUID, Decimal] = {}
    closed: list[list[LedgerEntry]] = []
    entry: LedgerEntry
    for entry in entries:
        sid: UUID | None = entry.security_id
        if sid is None:
            continue
        active.setdefault(sid, []).append(entry)
        quantities[sid] = quantities.get(sid, ZERO) + entry.quantity * (
            -1 if entry.kind == EntryKind.SELL else 1
        )
        if quantities[sid] == 0:
            closed.append(active.pop(sid))
    return closed, len(active)


def period_securities(
    entries: Sequence[LedgerEntry], start: date | None = None
) -> dict[UUID, Security]:
    """Keep every ledger lot; only skip price history for positions already closed."""
    securities: dict[UUID, Security] = {e.security_id: e.security for e in entries if e.security_id}
    if start is None:
        return securities
    lots: dict[UUID, list[Lot]]
    _, lots, _ = replay([e for e in entries if e.effective_date < start])
    needed: set[UUID] = {
        sid for sid, position in lots.items() if any(lot.quantity for lot in position)
    }
    needed.update(e.security_id for e in entries if e.effective_date >= start and e.security_id)
    return {sid: security for sid, security in securities.items() if sid in needed}


def holding_windows(
    entries: Sequence[LedgerEntry],
    securities: dict[UUID, Security],
    start: date,
    end: date,
    *,
    provisional: bool,
) -> dict[str, tuple[date, date]]:
    """Daily valuation only needs prices while a position is held, never after its final sale."""
    windows: dict[str, tuple[date, date]] = {}
    sid: UUID
    security: Security
    for sid, security in securities.items():
        rows: list[LedgerEntry] = [e for e in entries if e.security_id == sid]
        quantity: Decimal = sum(
            (e.quantity * (-1 if e.kind == EntryKind.SELL else 1) for e in rows), ZERO
        )
        first: date = max(start, rows[0].effective_date)
        last: date = end if quantity else min(end, rows[-1].effective_date)
        windows[market_listings.symbol_for(security, provisional=provisional)] = (first, last)
    return windows
