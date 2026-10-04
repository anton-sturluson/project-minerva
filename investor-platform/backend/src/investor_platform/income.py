"""Recorded dividend receivables; market events validate rather than invent income."""

from decimal import Decimal

from .domain import EntryKind, IncomeKind

ZERO = Decimal(0)
CENT = Decimal("0.01")


def market_dividends(entries, prices, through, *, validation_start=None):
    expected = {}
    for sid, history in prices.items():
        for exdate, per_share in history.dividends.items():
            if exdate > through or (validation_start and exdate < validation_start):
                continue
            shares = sum(
                (
                    e.quantity * (-1 if e.kind == EntryKind.SELL else 1)
                    for e in entries
                    if e.security_id == sid and e.effective_date < exdate
                ),
                ZERO,
            )
            if shares:
                expected[sid, exdate] = shares * per_share
    return expected


def dividend_receivables(entries, prices, securities, days, *, validation_start=None):
    dividends = [e for e in entries if e.income_kind == IncomeKind.DIVIDEND]
    warnings = []
    if any(e.kind == EntryKind.INCOME and e.income_kind is None for e in entries):
        warnings.append("Classify recorded income as dividends, interest or other income.")
    expected = market_dividends(entries, prices, days[-1], validation_start=validation_start)
    recorded = {}
    for entry in dividends:
        if entry.accrual_date > days[-1] or (
            validation_start and entry.accrual_date < validation_start
        ):
            continue
        key = entry.income_security_id, entry.accrual_date
        recorded[key] = recorded.get(key, ZERO) + entry.amount
    for key in sorted(expected.keys() | recorded.keys(), key=lambda item: (item[1], str(item[0]))):
        sid, exdate = key
        security = securities.get(sid)
        label = security.ticker if security is not None else "Dividend"
        if key not in expected:
            warnings.append(
                f"{label}: dividend on {exdate} needs matching holding and market evidence."
            )
        elif key not in recorded or abs(recorded[key] - expected[key]) > CENT:
            warnings.append(
                f"{label}: reconcile dividend on {exdate}; expected gross {expected[key]:.2f}, "
                f"recorded {recorded.get(key, ZERO):.2f}."
            )
    receivables = {
        day: sum((e.amount for e in dividends if e.accrual_date <= day < e.effective_date), ZERO)
        for day in days
    }
    return receivables, warnings
