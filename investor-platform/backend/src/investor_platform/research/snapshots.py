"""Disclosed filing snapshots and adjacent-quarter comparisons."""

from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Literal, TypedDict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from investor_platform.domain import ACCOUNTING_PRECISION
from investor_platform.models import ResearchFiling, ResearchHolding, ResearchManager

HoldingKey = tuple[str, str, str]


class Position(TypedDict):
    """Exact quantities for a stable reported security identity."""

    cusip: str
    issuer: str
    security_class: str
    put_call: str
    share_type: str
    quantity: Decimal
    value_usd: Decimal


def previous_quarter(quarter: date) -> date:
    """Return the immediately preceding calendar quarter end."""
    first: date = quarter.replace(day=1, month=((quarter.month - 1) // 3) * 3 + 1)
    return first - timedelta(days=1)


def quarter_end(value: date) -> bool:
    """Check calendar quarter end dates."""
    return value.month in (3, 6, 9, 12) and (value + timedelta(days=1)).day == 1


def filing_state(filing: ResearchFiling, reason: str | None) -> tuple[bool, str | None]:
    """Apply the shared replacement, amendment and completeness rules for one filing."""
    replacement: bool = filing.form == "13F-HR" or filing.amendment_type == "RESTATEMENT"
    if replacement:
        reason = None
    elif filing.amendment_type != "NEW HOLDINGS":
        reason = "Unknown amendment type; comparison needs review"
    if filing.status != "complete":
        reason = filing.reason or "Filing has incomplete holdings"
    return replacement, reason


def load_holdings(
    session: Session, filings: list[ResearchFiling]
) -> dict[UUID, list[ResearchHolding]]:
    """Read selected filings in one query without loading unrelated historical holdings."""
    result: dict[UUID, list[ResearchHolding]] = {}
    if not filings:
        return result
    holding: ResearchHolding
    for holding in session.scalars(
        select(ResearchHolding).where(
            ResearchHolding.filing_id.in_([filing.id for filing in filings])
        )
    ):
        result.setdefault(holding.filing_id, []).append(holding)
    return result


def snapshot(
    session: Session,
    filings: list[ResearchFiling],
    holdings: dict[UUID, list[ResearchHolding]] | None = None,
) -> tuple[dict[HoldingKey, Position], str | None, list[str]]:
    """Apply known amendments; block uncertain additions rather than infer trades."""
    if holdings is None:
        holdings = load_holdings(session, filings)
    positions: dict[HoldingKey, Position] = {}
    sources: list[str] = []
    reason: str | None = "No original or restated holdings available"
    filing: ResearchFiling
    for filing in sorted(filings, key=lambda item: (item.filed_date, item.accession)):
        sources.append(filing.source_url)
        replacement: bool
        replacement, reason = filing_state(filing, reason)
        if replacement:
            positions = {}
        holding: ResearchHolding
        rows: list[ResearchHolding] = holdings.get(filing.id, [])
        additions: dict[HoldingKey, Position] = {}
        for holding in rows:
            key: HoldingKey = (
                holding.cusip,
                holding.put_call,
                holding.share_type,
            )
            additions[key] = Position(
                cusip=holding.cusip,
                issuer=holding.issuer,
                security_class=holding.security_class,
                put_call=holding.put_call,
                share_type=holding.share_type,
                quantity=holding.quantity,
                value_usd=holding.value_usd,
            )
        if not replacement:
            overlaps: set[HoldingKey] = positions.keys() & additions.keys()
            if overlaps and (
                overlaps != positions.keys()
                or any(additions[key] != positions[key] for key in overlaps)
            ):
                reason = "Amendment overlaps an existing security; comparison needs review"
        positions.update(additions)
    return positions, reason, sources


class PositionChange(TypedDict):
    """Quantity category and signed disclosed value and portfolio fraction changes."""

    cusip: str
    issuer: str
    security_class: str
    put_call: str
    share_type: str
    kind: str
    category: Literal["increased", "decreased", "unchanged"]
    previous_quantity: str
    current_quantity: str
    quantity_change: str
    previous_value_usd: str
    current_value_usd: str
    value_change_usd: str
    previous_weight: str | None
    current_weight: str | None
    weight_change: str | None


def compare_positions(
    current: dict[HoldingKey, Position],
    previous: dict[HoldingKey, Position],
) -> list[PositionChange]:
    """Group quantities and rank absolute disclosed value changes within each group."""
    changes: list[PositionChange] = []
    categories: dict[str, Literal["increased", "decreased", "unchanged"]] = {
        "new": "increased",
        "increased": "increased",
        "exited": "decreased",
        "decreased": "decreased",
        "unchanged": "unchanged",
    }
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        current_total: Decimal = sum(
            (position["value_usd"] for position in current.values()), Decimal(0)
        )
        previous_total: Decimal = sum(
            (position["value_usd"] for position in previous.values()), Decimal(0)
        )
        key: HoldingKey
        for key in current.keys() | previous.keys():
            position: Position = current.get(key) or previous[key]
            old: Decimal = previous[key]["quantity"] if key in previous else Decimal(0)
            new: Decimal = current[key]["quantity"] if key in current else Decimal(0)
            old_value: Decimal = previous[key]["value_usd"] if key in previous else Decimal(0)
            new_value: Decimal = current[key]["value_usd"] if key in current else Decimal(0)
            kind: str = (
                "new"
                if key not in previous
                else "exited"
                if key not in current
                else "increased"
                if new > old
                else "decreased"
                if new < old
                else "unchanged"
            )
            previous_weight: Decimal | None = old_value / previous_total if previous_total else None
            current_weight: Decimal | None = new_value / current_total if current_total else None
            weight_change: Decimal | None = (
                current_weight - previous_weight
                if current_weight is not None and previous_weight is not None
                else None
            )
            changes.append(
                PositionChange(
                    cusip=position["cusip"],
                    issuer=position["issuer"],
                    security_class=position["security_class"],
                    put_call=position["put_call"],
                    share_type=position["share_type"],
                    kind=kind,
                    category=categories[kind],
                    previous_quantity=str(old),
                    current_quantity=str(new),
                    quantity_change=str(new - old),
                    previous_value_usd=str(old_value),
                    current_value_usd=str(new_value),
                    value_change_usd=str(new_value - old_value),
                    previous_weight=str(previous_weight) if previous_weight is not None else None,
                    current_weight=str(current_weight) if current_weight is not None else None,
                    weight_change=str(weight_change) if weight_change is not None else None,
                )
            )

    def sort_key(change: PositionChange) -> tuple[int, Decimal, str, str, str]:
        """Keep category order and deterministic ranking for equal dollar changes."""
        group_order: dict[str, int] = {"increased": 0, "decreased": 1, "unchanged": 2}
        return (
            group_order[change["category"]],
            Decimal(change["value_change_usd"]).copy_abs().copy_negate(),
            change["cusip"],
            change["put_call"],
            change["share_type"],
        )

    return sorted(changes, key=sort_key)


def manager_comparison(
    session: Session,
    manager: ResearchManager,
    quarter: date,
    *,
    prior: date | None = None,
    filings: list[ResearchFiling] | None = None,
    holdings: dict[UUID, list[ResearchHolding]] | None = None,
) -> dict:
    """Read complete calendar-quarter snapshots between two comparison boundaries."""
    if not quarter_end(quarter):
        raise HTTPException(422, "Choose a calendar quarter end")
    prior = prior or previous_quarter(quarter)
    filings = (
        filings
        if filings is not None
        else list(
            session.scalars(
                select(ResearchFiling).where(
                    ResearchFiling.manager_id == manager.id,
                    ResearchFiling.report_period.between(prior, quarter),
                )
            )
        )
    )
    if holdings is None:
        holdings = load_holdings(session, filings)
    current: dict[HoldingKey, Position] = {}
    previous: dict[HoldingKey, Position] = {}
    sources: list[str] = []
    error: str | None = None
    period: date = quarter
    while period >= prior:
        positions: dict[HoldingKey, Position]
        reason: str | None
        period_sources: list[str]
        positions, reason, period_sources = snapshot(
            session, [filing for filing in filings if filing.report_period == period], holdings
        )
        sources = period_sources + sources
        if reason and error is None:
            error = (
                f"{period.isoformat()}: {reason}" if prior != previous_quarter(quarter) else reason
            )
        if period == quarter:
            current = positions
        if period == prior:
            previous = positions
        period = previous_quarter(period)
    changes: list[PositionChange] = compare_positions(current, previous) if error is None else []
    return {
        "quarter": quarter.isoformat(),
        "previous_quarter": prior.isoformat(),
        "status": "unavailable" if error else "available",
        "reason": error,
        "source_urls": sources,
        "changes": changes,
    }
