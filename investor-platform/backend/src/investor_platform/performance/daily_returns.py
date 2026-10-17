"""The shared daily time-weighted return convention for accounts and funded indexes."""

from decimal import Decimal

ZERO: Decimal = Decimal(0)
ONE: Decimal = Decimal(1)


def daily_return_factor(
    previous: Decimal,
    ending: Decimal,
    incoming: Decimal = ZERO,
    outgoing: Decimal = ZERO,
    receipts: Decimal = ZERO,
) -> Decimal:
    """Place cash inflows at session start and outflows and share receipts at close."""
    denominator: Decimal = previous + incoming
    return (ending + outgoing - receipts) / denominator if denominator else ONE
