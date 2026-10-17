"""Dated market histories and supported collection limits."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

MAX_SECURITIES = 128


HISTORY_WINDOW = timedelta(days=3660)


SOURCE = "Yahoo Finance daily history"


BENCHMARKS = ("SPY", "QQQ")


class MarketDataError(OSError):
    """A public symbol could not be priced; carries no provider payload."""


@dataclass
class History:
    close: dict[date, Decimal]
    adjusted: dict[date, Decimal]
    dividends: dict[date, Decimal] = field(default_factory=dict)
    splits: set[date] = field(default_factory=set)
    exchange: str = ""
    source: str = SOURCE


MAX_CLOSE_AGE = timedelta(days=4)
