"""Closed-position FIFO profit and payoff statistics."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import NotRequired, TypedDict, cast

from investor_platform.domain import EntryKind
from investor_platform.ledger.accounting import replay
from investor_platform.models import LedgerEntry
from investor_platform.performance.positions import position_episodes

ZERO: Decimal = Decimal(0)


class ClosedPosition(TypedDict):
    """One flat-to-flat decision with optional FIFO profit and simulated-sale marker."""

    ticker: str
    exchange: str
    closed_on: date
    pnl: Decimal | None
    hypothetical: NotRequired[bool]


class TradeStatistics(TypedDict):
    """Closed-position counts and profit statistics, retaining unknown cost bases."""

    closed: int
    open: int
    unknown: int
    wins: int
    losses: int
    breakeven: int
    win_rate: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    payoff_ratio: Decimal | None
    realized_pnl: Decimal | None
    episodes: list[ClosedPosition]


def trade_statistics(entries: Sequence[LedgerEntry]) -> TradeStatistics:
    """Summarize fully closed positions while withholding profit with unknown basis."""
    realized: dict[int, Decimal | None]
    _, _, realized = replay(entries)
    episodes: list[list[LedgerEntry]]
    open_count: int
    episodes, open_count = position_episodes(entries)
    closed: list[ClosedPosition] = []
    episode: list[LedgerEntry]
    for episode in episodes:
        last: LedgerEntry = episode[-1]
        gains: list[Decimal | None] = [realized[e.id] for e in episode if e.kind == EntryKind.SELL]
        closed.append(
            {
                "ticker": last.security.ticker,
                "exchange": last.security.exchange,
                "closed_on": last.effective_date,
                "pnl": None if None in gains else sum(cast(list[Decimal], gains), ZERO),
            }
        )
    known: list[Decimal] = [e["pnl"] for e in closed if e["pnl"] is not None]
    wins: list[Decimal] = [p for p in known if p > 0]
    losses: list[Decimal] = [-p for p in known if p < 0]
    avg_win: Decimal | None = sum(wins, ZERO) / len(wins) if wins else None
    avg_loss: Decimal | None = sum(losses, ZERO) / len(losses) if losses else None
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
