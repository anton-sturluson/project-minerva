"""Index holdings bought from canonical external deposits, without replaying a portfolio."""

from datetime import date
from decimal import Decimal

from . import market
from .domain import IN_KIND_ENTRIES, EntryKind
from .models import LedgerEntry
from .performance_math import daily_return_factor

ZERO: Decimal = Decimal(0)
ONE: Decimal = Decimal(1)


def funded_series(
    entries: list[LedgerEntry],
    histories: dict[str, market.History],
    days: list[date],
    *,
    provisional: bool = False,
) -> dict[date, dict[str, dict[str, Decimal]]]:
    """Invest recorded deposits at closes and retain shares after stock sales.

    Deposits use the account's beginning-of-session daily convention. They remain
    cash until the closing index purchase; share receipts contribute at the close.
    This index-only replay neither estimates cash shortages nor changes stock returns.
    """
    entry: LedgerEntry
    if any(entry.kind == EntryKind.OPENING_CASH for entry in entries):
        raise ValueError(
            "Deposit-matched indexes require dated deposits; "
            "recorded opening cash cannot be matched"
        )
    if any(entry.kind == EntryKind.WITHDRAWAL for entry in entries):
        raise ValueError("Never-sold index comparisons do not support recorded cash withdrawals")
    timeline: list[date] = sorted(
        day
        for day in histories["SPY"].close
        if min(days[0], entries[0].effective_date) <= day <= days[-1]
    )
    result: dict[date, dict[str, dict[str, Decimal]]] = {day: {} for day in days}
    symbol: str
    for symbol in market.BENCHMARKS:
        units: Decimal = ZERO
        capital: Decimal = ZERO
        growth: Decimal = ONE
        previous: Decimal | None = None
        baseline: Decimal | None = None
        cursor: int = 0
        day: date
        for day in timeline:
            price: Decimal | None = histories[symbol].adjusted.get(day)
            if price is None or price <= ZERO:
                raise ValueError(f"Deposit-matched indexes need a valid {symbol} close on {day}")
            incoming: Decimal = ZERO
            receipts: Decimal = ZERO
            while cursor < len(entries) and entries[cursor].effective_date <= day:
                entry = entries[cursor]
                cursor += 1
                if entry.kind == EntryKind.DEPOSIT:
                    incoming += entry.amount
                elif entry.kind in IN_KIND_ENTRIES:
                    security_symbol: str = market.symbol_for(
                        entry.security, provisional=provisional
                    )
                    close: Decimal | None = histories[security_symbol].close.get(day)
                    if close is None:
                        raise ValueError(
                            "Deposit-matched indexes need a received-share closing value"
                        )
                    receipts += entry.quantity * close
            capital += incoming + receipts
            units += (incoming + receipts) / price
            value: Decimal = units * price
            if previous is not None:
                factor: Decimal = daily_return_factor(previous, value, incoming, receipts=receipts)
                if factor < ZERO:
                    raise ValueError("Deposit-matched index daily return is invalid")
                growth *= factor
            if day in result:
                if baseline is None:
                    baseline = growth
                if baseline <= ZERO:
                    raise ValueError("Deposit-matched index return is undefined after a total loss")
                result[day][symbol] = {
                    "return": growth / baseline - ONE,
                    "value": value,
                    "gain": value - capital,
                }
            previous = value
    return result
