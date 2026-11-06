"""Accrue recorded income and distinguish missing ledger inputs from market diagnostics."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from investor_platform.domain import EntryKind, IncomeKind
from investor_platform.market_data.types import History
from investor_platform.models import LedgerEntry, Security

ZERO: Decimal = Decimal(0)
CENT: Decimal = Decimal("0.01")


@dataclass
class IncomeReconciliation:
    """Recorded receivables, unresolved ledger inputs, and independent provider comparisons."""

    receivables: dict[date, Decimal]
    blockers: list[str]
    advisories: list[str]


def eligible_shares(entries: list[LedgerEntry], security_id: UUID, ex_date: date) -> Decimal:
    """Use recorded shares held before the ex-date for entitlement checks."""
    return sum(
        (
            entry.quantity * (-1 if entry.kind == EntryKind.SELL else 1)
            for entry in entries
            if entry.security_id == security_id and entry.effective_date < ex_date
        ),
        ZERO,
    )


def market_dividends(
    entries: list[LedgerEntry],
    prices: dict[UUID, History],
    through: date,
    *,
    validation_start: date | None = None,
) -> dict[tuple[UUID, date], Decimal]:
    """Estimate distributions on recorded shares using provider ex-dates and rates."""
    expected: dict[tuple[UUID, date], Decimal] = {}
    sid: UUID
    history: History
    exdate: date
    per_share: Decimal
    for sid, history in prices.items():
        for exdate, per_share in history.dividends.items():
            if exdate > through or (validation_start and exdate < validation_start):
                continue
            shares: Decimal = eligible_shares(entries, sid, exdate)
            if shares:
                expected[sid, exdate] = shares * per_share
    return expected


def reconcile_income(
    entries: list[LedgerEntry],
    prices: dict[UUID, History],
    securities: dict[UUID, Security],
    days: list[date],
    *,
    validation_start: date | None = None,
    assume_unrecorded_zero: bool = False,
) -> IncomeReconciliation:
    """Use recorded cash for accruals; provider amounts corroborate rather than replace it."""
    dividends: list[LedgerEntry] = [e for e in entries if e.income_kind == IncomeKind.DIVIDEND]
    blockers: list[str] = []
    advisories: list[str] = []
    if any(e.kind == EntryKind.INCOME and e.income_kind is None for e in entries):
        blockers.append("Classify recorded income as dividends, interest or other income.")
    expected: dict[tuple[UUID, date], Decimal] = market_dividends(
        entries, prices, days[-1], validation_start=validation_start
    )
    recorded: dict[tuple[UUID, date], Decimal] = {}
    entry: LedgerEntry
    key: tuple[UUID, date]
    for entry in dividends:
        if entry.accrual_date > days[-1] or (
            validation_start and entry.accrual_date < validation_start
        ):
            continue
        key = entry.income_security_id, entry.accrual_date
        recorded[key] = recorded.get(key, ZERO) + entry.amount
    for key in sorted(expected.keys() | recorded.keys(), key=lambda item: (item[1], str(item[0]))):
        sid: UUID
        exdate: date
        sid, exdate = key
        security: Security | None = securities.get(sid)
        label: str = security.ticker if security is not None else "Dividend"
        if key not in recorded:
            if not assume_unrecorded_zero and expected[key].quantize(CENT, ROUND_HALF_EVEN) > ZERO:
                blockers.append(
                    f"{label}: reconcile dividend on {exdate}; provider estimate "
                    f"{expected[key]:.2f}, no recorded dividend."
                )
        elif eligible_shares(entries, sid, exdate) <= ZERO:
            blockers.append(
                f"{label}: dividend on {exdate} has no recorded holdings before its ex-date."
            )
        elif key not in expected:
            advisories.append(
                f"{label}: recorded dividend on {exdate} has no matching provider event; "
                "check source records."
            )
        else:
            recorded_display: Decimal = recorded[key].quantize(CENT, ROUND_HALF_EVEN)
            estimated_display: Decimal = expected[key].quantize(CENT, ROUND_HALF_EVEN)
            if recorded_display != estimated_display:
                advisories.append(
                    f"{label}: dividend on {exdate}; provider estimate {estimated_display:.2f}, "
                    f"recorded gross {recorded_display:.2f} "
                    f"(difference {abs(recorded_display - estimated_display):.2f}); "
                    "check source records."
                )
    receivables: dict[date, Decimal] = {
        day: sum((e.amount for e in dividends if e.accrual_date <= day < e.effective_date), ZERO)
        for day in days
    }
    return IncomeReconciliation(receivables, blockers, advisories)
