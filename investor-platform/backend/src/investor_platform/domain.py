"""Stable API values shared by validation and accounting; storage remains plain text."""

from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")
PRICE_REFRESH_TIME = time(17)


def completed_market_date(now=None):
    now = (now or datetime.now(MARKET_TIMEZONE)).astimezone(MARKET_TIMEZONE)
    return now.date() if now.time() >= PRICE_REFRESH_TIME else now.date() - timedelta(days=1)


# Share-price products exceed Decimal's default precision.
ACCOUNTING_PRECISION = 64


class EntryKind(StrEnum):
    OPENING_CASH = "opening_cash"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INCOME = "income"
    EXPENSE = "expense"
    OPENING_POSITION = "opening_position"
    TRANSFER_IN = "transfer_in"
    BUY = "buy"
    SELL = "sell"


class IncomeKind(StrEnum):
    DIVIDEND = "dividend"
    INTEREST = "interest"
    OTHER = "other"


class FundingStatus(StrEnum):
    RECORDED = "recorded"
    INFERRED = "inferred"
    RECONCILED = "reconciled"


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    AUD = "AUD"
    JPY = "JPY"
    CHF = "CHF"
    HKD = "HKD"
    SGD = "SGD"


IN_KIND_ENTRIES = frozenset({EntryKind.OPENING_POSITION, EntryKind.TRANSFER_IN})
