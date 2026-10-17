"""Recorded position episodes and required market-data windows."""

from decimal import Decimal

from investor_platform.domain import EntryKind
from investor_platform.ledger.accounting import replay
from investor_platform.market_data import listings as market_listings


def position_episodes(entries):
    """Group each security from flat to flat, retaining buys and partial exits."""
    active, quantities, closed = {}, {}, []
    for entry in entries:
        sid = entry.security_id
        if sid is None:
            continue
        active.setdefault(sid, []).append(entry)
        quantities[sid] = quantities.get(sid, ZERO) + entry.quantity * (
            -1 if entry.kind == EntryKind.SELL else 1
        )
        if quantities[sid] == 0:
            closed.append(active.pop(sid))
    return closed, len(active)


def period_securities(entries, start=None):
    """Keep every ledger lot; only skip price history for positions already closed."""
    securities = {e.security_id: e.security for e in entries if e.security_id}
    if start is None:
        return securities
    _, lots, _ = replay([e for e in entries if e.effective_date < start])
    needed = {sid for sid, position in lots.items() if any(lot.quantity for lot in position)}
    needed.update(e.security_id for e in entries if e.effective_date >= start and e.security_id)
    return {sid: security for sid, security in securities.items() if sid in needed}


def holding_windows(entries, securities, start, end, *, provisional):
    """Daily valuation only needs prices while a position is held, never after its final sale."""
    windows = {}
    for sid, security in securities.items():
        rows = [e for e in entries if e.security_id == sid]
        quantity = sum((e.quantity * (-1 if e.kind == EntryKind.SELL else 1) for e in rows), ZERO)
        first = max(start, rows[0].effective_date)
        last = end if quantity else min(end, rows[-1].effective_date)
        windows[market_listings.symbol_for(security, provisional=provisional)] = (first, last)
    return windows


ZERO = Decimal(0)
