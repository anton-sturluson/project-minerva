"""Shared dated market histories and supported collection limits."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

type MarketNumber = str | int | float | Decimal
type JsonValue = str | int | float | Decimal | bool | None | list[JsonValue] | dict[str, JsonValue]


class HistoryOptions(TypedDict, total=False):
    """Provider identity checks included in a Yahoo cache variant."""

    currency: str
    instruments: tuple[str, ...]


MAX_SECURITIES: int = 128
HISTORY_WINDOW: timedelta = timedelta(days=3660)
SOURCE: str = "Yahoo Finance daily history"
BENCHMARKS: tuple[str, ...] = ("SPY", "QQQ")


class MarketDataError(OSError):
    """A public symbol could not be priced; carries no provider payload."""


@dataclass
class History:
    """Dated prices, distributions, split events and provider listing identity."""

    close: dict[date, Decimal]
    adjusted: dict[date, Decimal]
    dividends: dict[date, Decimal] = field(default_factory=dict)
    splits: set[date] = field(default_factory=set)
    exchange: str = ""
    source: str = SOURCE
    fetched_at: datetime | None = None


def collected_at(histories: Iterable[History]) -> datetime | None:
    """Report the oldest contributing collection, or unknown if any date is missing."""
    dates: list[datetime | None] = [history.fetched_at for history in histories]
    if not dates or any(stamp is None for stamp in dates):
        return None
    return min(stamp for stamp in dates if stamp is not None)


MAX_CLOSE_AGE: timedelta = timedelta(days=4)
