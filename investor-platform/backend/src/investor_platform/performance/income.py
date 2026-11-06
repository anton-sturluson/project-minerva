"""Recorded dividend receivables; market events validate rather than invent income."""

from datetime import date
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, model_validator

from investor_platform.domain import EntryKind, IncomeKind
from investor_platform.market_data.types import History
from investor_platform.models import LedgerEntry, Security

ZERO = Decimal(0)
CENT = Decimal("0.01")


class ReviewedDividend(BaseModel):
    """Final USD gross entitlement reviewed against a dated issuer or depositary source."""

    model_config = ConfigDict(extra="forbid")
    ex_date: date
    pay_date: date
    gross_per_share: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: Literal["USD"]
    status: Literal["final"]
    source_url: HttpUrl
    reviewed_on: date

    @model_validator(mode="after")
    def payment_follows_entitlement(self) -> Self:
        """Reject an internally inconsistent distribution event."""
        if self.pay_date < self.ex_date:
            raise ValueError("Dividend payment cannot precede its ex-date")
        return self


REVIEWED_DIVIDENDS: TypeAdapter[list[ReviewedDividend]] = TypeAdapter(list[ReviewedDividend])


def eligible_shares(entries: list[LedgerEntry], security_id: UUID, ex_date: date) -> Decimal:
    """Use recorded shares held before the ex-date for every entitlement source."""
    return sum(
        (
            entry.quantity * (-1 if entry.kind == EntryKind.SELL else 1)
            for entry in entries
            if entry.security_id == security_id and entry.effective_date < ex_date
        ),
        ZERO,
    )


def reviewed_dividends(security: Security) -> dict[date, ReviewedDividend]:
    """Validate persisted evidence once, rejecting ambiguous duplicate event reviews."""
    result: dict[date, ReviewedDividend] = {}
    review: ReviewedDividend
    for review in REVIEWED_DIVIDENDS.validate_python(
        (security.market_identity or {}).get("reviewed_dividends", [])
    ):
        if review.ex_date in result:
            raise ValueError(
                f"Duplicate reviewed dividend for {security.ticker} on {review.ex_date}"
            )
        result[review.ex_date] = review
    return result


def market_dividends(
    entries: list[LedgerEntry],
    prices: dict[UUID, History],
    through: date,
    *,
    validation_start: date | None = None,
) -> dict[tuple[UUID, date], Decimal]:
    """Calculate distributions earned by recorded shares on provider ex-dates."""
    expected = {}
    for sid, history in prices.items():
        for exdate, per_share in history.dividends.items():
            if exdate > through or (validation_start and exdate < validation_start):
                continue
            shares = eligible_shares(entries, sid, exdate)
            if shares:
                expected[sid, exdate] = shares * per_share
    return expected


def dividend_receivables(
    entries: list[LedgerEntry],
    prices: dict[UUID, History],
    securities: dict[UUID, Security],
    days: list[date],
    *,
    validation_start: date | None = None,
    assume_unrecorded_zero: bool = False,
) -> tuple[dict[date, Decimal], list[str]]:
    """Accrue recorded income; optionally assume zero only for absent dividend records."""
    dividends = [e for e in entries if e.income_kind == IncomeKind.DIVIDEND]
    warnings = []
    if any(e.kind == EntryKind.INCOME and e.income_kind is None for e in entries):
        warnings.append("Classify recorded income as dividends, interest or other income.")
    expected = market_dividends(entries, prices, days[-1], validation_start=validation_start)
    sid: UUID
    source_security: Security
    exdate: date
    review: ReviewedDividend
    for sid, source_security in securities.items():
        for exdate, review in reviewed_dividends(source_security).items():
            if (sid, exdate) in expected:
                expected[sid, exdate] = (
                    eligible_shares(entries, sid, exdate) * review.gross_per_share
                )
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
        if assume_unrecorded_zero and key in expected and key not in recorded:
            continue
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
