"""Fully closed position statistics, independent of market data."""

from decimal import Decimal, localcontext
from uuid import UUID

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .accounting import replay
from .accounts import DB, Identity, owned_account
from .ledger import entries_for

router = APIRouter(prefix="/api/accounts")
ZERO = Decimal(0)


def wire(value):
    return JSONResponse(jsonable_encoder(value, custom_encoder={Decimal: lambda d: format(d, "f")}))


def position_episodes(entries):
    """Group each security from flat to flat, retaining buys and partial exits."""
    active, quantities, closed = {}, {}, []
    for entry in entries:
        sid = entry.security_id
        if sid is None:
            continue
        active.setdefault(sid, []).append(entry)
        quantities[sid] = quantities.get(sid, ZERO) + entry.quantity * (
            -1 if entry.kind == "sell" else 1
        )
        if quantities[sid] == 0:
            closed.append(active.pop(sid))
    return closed, len(active)


def trade_statistics(entries):
    _, _, realized = replay(entries)
    episodes, open_count = position_episodes(entries)
    closed = []
    for episode in episodes:
        last = episode[-1]
        gains = [realized[e.id] for e in episode if e.kind == "sell"]
        closed.append(
            {
                "ticker": last.security.ticker,
                "exchange": last.security.exchange,
                "closed_on": last.effective_date,
                "pnl": None if None in gains else sum(gains, ZERO),
            }
        )
    known = [e["pnl"] for e in closed if e["pnl"] is not None]
    wins = [p for p in known if p > 0]
    losses = [-p for p in known if p < 0]
    avg_win = sum(wins, ZERO) / len(wins) if wins else None
    avg_loss = sum(losses, ZERO) / len(losses) if losses else None
    return {
        "closed": len(closed),
        "open": open_count,
        "unknown": len(closed) - len(known),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": known.count(ZERO),
        "win_rate": Decimal(len(wins)) / len(known) if known else None,
        "average_win": avg_win,
        "average_loss": avg_loss,
        "payoff_ratio": avg_win / avg_loss if avg_win is not None and avg_loss else None,
        "realized_pnl": sum(known, ZERO) if known else None,
        "episodes": closed,
    }


@router.get("/{account_id}/statistics")
def statistics(account_id: UUID, session: DB, actor: Identity):
    owned_account(session, actor, account_id)
    with localcontext() as ctx:
        ctx.prec = 64
        return wire(trade_statistics(entries_for(session, account_id)))
