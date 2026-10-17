"""Shared dated market histories and supported collection limits."""

from dataclasses import dataclass, field
from datetime import date, timedelta
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


MAX_CLOSE_AGE: timedelta = timedelta(days=4)
