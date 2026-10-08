"""Read sourced managers and compare complete adjacent quarterly snapshots."""

from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Actor, get_actor, get_session
from .domain import ACCOUNTING_PRECISION
from .models import ResearchFiling, ResearchHolding, ResearchManager
from .research_eligibility import manager_eligibility

router: APIRouter = APIRouter(prefix="/api/research")
DB = Annotated[Session, Depends(get_session)]
Identity = Annotated[Actor, Depends(get_actor)]
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


def snapshot(
    session: Session, filings: list[ResearchFiling]
) -> tuple[dict[HoldingKey, Position], str | None, list[str]]:
    """Apply known amendments; block uncertain additions rather than infer trades."""
    positions: dict[HoldingKey, Position] = {}
    sources: list[str] = []
    reason: str | None = "No original or restated holdings available"
    filing: ResearchFiling
    for filing in sorted(filings, key=lambda item: (item.filed_date, item.accession)):
        sources.append(filing.source_url)
        replacement: bool = filing.form == "13F-HR" or filing.amendment_type == "RESTATEMENT"
        if replacement:
            positions = {}
            reason = None
        elif filing.amendment_type != "NEW HOLDINGS":
            reason = "Unknown amendment type; comparison needs review"
        if filing.status != "complete":
            reason = filing.reason or "Filing has incomplete holdings"
        holding: ResearchHolding
        rows: list[ResearchHolding] = list(
            session.scalars(select(ResearchHolding).where(ResearchHolding.filing_id == filing.id))
        )
        for holding in rows:
            key: HoldingKey = (
                holding.cusip,
                holding.put_call,
                holding.share_type,
            )
            if not replacement and key in positions:
                reason = "Amendment overlaps an existing security; comparison needs review"
            positions[key] = Position(
                cusip=holding.cusip,
                issuer=holding.issuer,
                security_class=holding.security_class,
                put_call=holding.put_call,
                share_type=holding.share_type,
                quantity=holding.quantity,
                value_usd=holding.value_usd,
            )
    return positions, reason, sources


def owned_manager(session: Session, actor: Actor, slug: str) -> ResearchManager:
    """Find a registry record in the current workspace."""
    manager: ResearchManager | None = session.scalar(
        select(ResearchManager).where(
            ResearchManager.workspace_id == actor.workspace_id, ResearchManager.slug == slug
        )
    )
    if manager is None:
        raise HTTPException(404, "Manager not found")
    return manager


def manager_view(session: Session, manager: ResearchManager, *, detail: bool = False) -> dict:
    """Report imported usable coverage separately from manager operating history."""
    filings: list[ResearchFiling] = list(
        session.scalars(
            select(ResearchFiling)
            .where(ResearchFiling.manager_id == manager.id)
            .order_by(ResearchFiling.report_period.desc(), ResearchFiling.filed_date.desc())
        )
    )
    periods: list[date] = sorted({filing.report_period for filing in filings})
    usable: list[date] = []
    period: date
    for period in periods:
        quarter_filings: list[ResearchFiling] = [
            filing for filing in filings if filing.report_period == period
        ]
        # Ordinary quarters need metadata only. Additions require identity overlap checks.
        if any(filing.amendment_type == "NEW HOLDINGS" for filing in quarter_filings):
            reason: str | None = snapshot(session, quarter_filings)[1]
        else:
            reason = "No original or restated holdings available"
            filing: ResearchFiling
            for filing in sorted(
                quarter_filings, key=lambda item: (item.filed_date, item.accession)
            ):
                if filing.form == "13F-HR" or filing.amendment_type == "RESTATEMENT":
                    reason = None
                else:
                    reason = "Unknown amendment type"
                if filing.status != "complete":
                    reason = filing.reason or "Incomplete filing"
        if reason is None:
            usable.append(period)
    streak: int = 0
    cursor: date | None = None
    period: date
    for period in reversed(usable):
        if cursor is not None and previous_quarter(cursor) != period:
            break
        streak += 1
        cursor = period
    result: dict = {
        **manager.profile,
        "slug": manager.slug,
        "cik": manager.cik,
        "eligibility": manager_eligibility(manager.profile, date.today()),
        "coverage": {
            "quarters": len(usable),
            "first_quarter": usable[0].isoformat() if usable else None,
            "last_quarter": usable[-1].isoformat() if usable else None,
            "continuous_decade": bool(
                streak >= 40 and usable and periods and usable[-1] == periods[-1]
            ),
        },
    }
    if detail:
        result["filings"] = [
            {
                "accession": filing.accession,
                "quarter": filing.report_period.isoformat(),
                "filed_date": filing.filed_date.isoformat(),
                "form": filing.form,
                "source_url": filing.source_url,
                "amendment_type": filing.amendment_type,
                "status": filing.status,
                "reason": filing.reason,
            }
            for filing in filings
        ]
    return result


@router.get("/managers")
def list_managers(session: DB, actor: Identity) -> dict:
    """Read the seeded registry without network access."""
    managers: list[ResearchManager] = list(
        session.scalars(
            select(ResearchManager)
            .where(ResearchManager.workspace_id == actor.workspace_id)
            .order_by(ResearchManager.slug)
        )
    )
    return {"managers": [manager_view(session, manager) for manager in managers]}


@router.get("/managers/{slug}")
def get_manager(slug: str, session: DB, actor: Identity) -> dict:
    """Read provenance and coverage for one manager."""
    return manager_view(session, owned_manager(session, actor, slug), detail=True)


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


def manager_comparison(session: Session, manager: ResearchManager, quarter: date) -> dict:
    """Read adjacent filing snapshots and their common comparison response."""
    if not quarter_end(quarter):
        raise HTTPException(422, "Choose a calendar quarter end")
    prior: date = previous_quarter(quarter)
    filings: list[ResearchFiling] = list(
        session.scalars(
            select(ResearchFiling).where(
                ResearchFiling.manager_id == manager.id,
                ResearchFiling.report_period.in_([prior, quarter]),
            )
        )
    )
    current: dict[HoldingKey, Position]
    current_error: str | None
    current_sources: list[str]
    previous: dict[HoldingKey, Position]
    previous_error: str | None
    previous_sources: list[str]
    current, current_error, current_sources = snapshot(
        session, [filing for filing in filings if filing.report_period == quarter]
    )
    previous, previous_error, previous_sources = snapshot(
        session, [filing for filing in filings if filing.report_period == prior]
    )
    error: str | None = current_error or previous_error
    changes: list[PositionChange] = compare_positions(current, previous) if error is None else []
    return {
        "quarter": quarter.isoformat(),
        "previous_quarter": prior.isoformat(),
        "status": "unavailable" if error else "available",
        "reason": error,
        "source_urls": previous_sources + current_sources,
        "changes": changes,
    }


@router.get("/managers/{slug}/changes")
def get_changes(slug: str, quarter: date, session: DB, actor: Identity) -> dict:
    """Compare quantities only across adjacent complete quarters and rank dollar changes."""
    return manager_comparison(session, owned_manager(session, actor, slug), quarter)
