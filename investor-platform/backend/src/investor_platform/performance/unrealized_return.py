"""Annualize the purchase costs of shares still held, excluding realized cash flows."""

from datetime import date
from decimal import Decimal, DecimalException, localcontext

from investor_platform.ledger.accounting import Lot
from investor_platform.performance.daily_returns import DAYS_PER_YEAR


def annualized_unrealized_return(
    lots: list[Lot], value: Decimal, quote_date: date
) -> tuple[Decimal | None, str | None]:
    """Solve the remaining FIFO costs' annual growth to their quoted market value."""
    if not lots or any(lot.basis is None or lot.basis < 0 for lot in lots):
        return None, "Positive purchase cost unavailable"
    if not any(lot.basis > 0 for lot in lots):
        return None, "Positive purchase cost unavailable"
    if any(lot.acquired_on is None for lot in lots):
        return None, "Original purchase date unavailable"
    dated_costs: list[tuple[Decimal, int]] = [
        (lot.basis, (quote_date - lot.acquired_on).days) for lot in lots
    ]
    if any(age < 0 for _, age in dated_costs):
        return None, "Quote precedes a remaining purchase"
    dated_costs = [(cost, age) for cost, age in dated_costs if cost > 0]
    if max(age for _, age in dated_costs) < 365:
        return None, "Less than one year of holding history"
    try:
        with localcontext() as context:
            context.prec = 28
            same_day_cost: Decimal = sum(
                (cost for cost, age in dated_costs if age == 0), Decimal(0)
            )
            terminal: Decimal = value - same_day_cost
            if terminal == 0:
                return Decimal(-1), None
            if terminal < 0:
                return None, "No finite annualized return"
            aged: list[tuple[Decimal, Decimal]] = [
                (cost, Decimal(age) / DAYS_PER_YEAR) for cost, age in dated_costs if age > 0
            ]
            total: Decimal = sum((cost for cost, _ in aged), Decimal(0))
            target: Decimal = (terminal / total).ln()
            times: list[Decimal] = [years for _, years in aged]
            lower, upper = sorted((target / min(times), target / max(times)))
            weighted: list[tuple[Decimal, Decimal]] = [
                ((cost / total).ln(), years) for cost, years in aged
            ]
            # Work in log-growth space: all exponentials below are at most one.
            for _ in range(80):
                middle: Decimal = (lower + upper) / 2
                terms: list[Decimal] = [weight + middle * years for weight, years in weighted]
                largest: Decimal = max(terms)
                projected: Decimal = (
                    largest + sum(((term - largest).exp() for term in terms), Decimal(0)).ln()
                )
                if projected < target:
                    lower = middle
                else:
                    upper = middle
                if upper - lower < Decimal("1e-16"):
                    break
            rate: Decimal = ((lower + upper) / 2).exp() - 1
            if rate.is_finite() and rate > -1:
                return rate, None
    except DecimalException:
        pass
    return None, "No finite annualized return"
