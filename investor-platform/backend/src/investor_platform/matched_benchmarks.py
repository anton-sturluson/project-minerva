"""Read-only index investments matched to stock purchases and FIFO share exits."""

from dataclasses import dataclass
from decimal import Decimal

from . import market
from .domain import IN_KIND_ENTRIES, EntryKind

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass
class IndexLot:
    quantity: Decimal
    units: Decimal


def matched_series(entries, histories, days, *, recorded=False, provisional=False):
    """Use adjusted closes as reinvesting units; exit the matching FIFO stock quantity.

    Closing execution is an explicit approximation. Buys fund the sleeve at session
    start, sales withdraw their hypothetical proceeds at session end, and receipts
    contribute at the close. Flat intervals retain the last linked return.
    """
    entries = [e for e in entries if e.security_id is not None]
    if not entries:
        raise ValueError("Same-money indexes need recorded stock holdings or trades")
    timeline = (
        days
        if recorded
        else sorted(
            d
            for d in histories["SPY"].close
            if min(days[0], entries[0].effective_date) <= d <= days[-1]
        )
    )
    result = {d: {} for d in days}
    securities = {e.security_id: e.security for e in entries}

    def receipt_value(sid, quantity, day):
        symbol = market.symbol_for(securities[sid], provisional=provisional)
        price = histories[symbol].close.get(day)
        if price is None:
            raise ValueError("Same-money indexes need an opening/received stock valuation")
        return quantity * price

    for benchmark in market.BENCHMARKS:
        adjusted = histories[benchmark].adjusted
        lots = {}
        previous = None
        growth = ONE
        baseline_growth = None
        contributed = withdrawn = ZERO
        baseline_capital = baseline_withdrawn = baseline_contributed = ZERO
        if recorded:
            for sid in securities:
                quantity = sum(
                    (
                        e.quantity * (-1 if e.kind == EntryKind.SELL else 1)
                        for e in entries
                        if e.security_id == sid and e.effective_date < days[0]
                    ),
                    ZERO,
                )
                if quantity:
                    capital = receipt_value(sid, quantity, days[0])
                    lots[sid] = [IndexLot(quantity, capital / adjusted[days[0]])]
                    contributed += capital
        cursor = 0
        if recorded:
            while cursor < len(entries) and entries[cursor].effective_date < days[0]:
                cursor += 1
        for day in timeline:
            price = adjusted.get(day)
            if price is None or price <= ZERO:
                raise ValueError(f"Same-money indexes need a valid {benchmark} close on {day}")
            incoming = outgoing = receipts = ZERO
            while cursor < len(entries) and entries[cursor].effective_date <= day:
                entry = entries[cursor]
                cursor += 1
                position = lots.setdefault(entry.security_id, [])
                if entry.kind == EntryKind.BUY or entry.kind in IN_KIND_ENTRIES:
                    capital = (
                        entry.amount
                        if entry.kind == EntryKind.BUY
                        else receipt_value(entry.security_id, entry.quantity, day)
                    )
                    position.append(IndexLot(entry.quantity, capital / price))
                    contributed += capital
                    if entry.kind == EntryKind.BUY:
                        incoming += capital
                    else:
                        receipts += capital
                elif entry.kind == EntryKind.SELL:
                    remaining = entry.quantity
                    for lot in position:
                        take = min(remaining, lot.quantity)
                        if not take:
                            continue
                        units = (
                            lot.units if take == lot.quantity else lot.units * take / lot.quantity
                        )
                        outgoing += units * price
                        lot.quantity -= take
                        lot.units -= units
                        remaining -= take
                    if remaining:
                        raise ValueError("Same-money index sale exceeds matched stock holdings")
            withdrawn += outgoing
            value = sum((lot.units * price for position in lots.values() for lot in position), ZERO)
            if previous is not None:
                denominator = previous + incoming
                growth *= (value + outgoing - receipts) / denominator if denominator else ONE
            if day in result:
                if baseline_growth is None:
                    baseline_growth = growth
                    baseline_capital = value
                    baseline_contributed = contributed
                    baseline_withdrawn = withdrawn
                result[day][benchmark] = {
                    "return": growth / baseline_growth - ONE,
                    "value": value,
                    "gain": value
                    + withdrawn
                    - baseline_withdrawn
                    - baseline_capital
                    - (contributed - baseline_contributed),
                    "proceeds": withdrawn - baseline_withdrawn,
                }
            previous = value
    return result
