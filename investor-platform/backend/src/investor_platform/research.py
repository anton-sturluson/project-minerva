"""Read sourced managers and compare complete adjacent quarterly snapshots."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Actor, get_actor, get_session
from .models import ResearchFiling, ResearchHolding, ResearchManager

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


@router.get("/managers/{slug}/changes")
def get_changes(slug: str, quarter: date, session: DB, actor: Identity) -> dict:
    """Compare share or principal quantities only across adjacent complete quarters."""
    if not quarter_end(quarter):
        raise HTTPException(422, "Choose a calendar quarter end")
    manager: ResearchManager = owned_manager(session, actor, slug)
    prior: date = previous_quarter(quarter)
    filings: list[ResearchFiling] = list(
        session.scalars(
            select(ResearchFiling).where(
                ResearchFiling.manager_id == manager.id,
                ResearchFiling.report_period.in_([prior, quarter]),
            )
        )
    )
    current, current_error, current_sources = snapshot(
        session, [filing for filing in filings if filing.report_period == quarter]
    )
    previous, previous_error, previous_sources = snapshot(
        session, [filing for filing in filings if filing.report_period == prior]
    )
    error: str | None = current_error or previous_error
    changes: list[dict] = []
    key: HoldingKey
    if error is None:
        for key in sorted(current.keys() | previous.keys()):
            position: Position = current.get(key) or previous[key]
            old: Decimal = previous[key]["quantity"] if key in previous else Decimal(0)
            new: Decimal = current[key]["quantity"] if key in current else Decimal(0)
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
            changes.append(
                {
                    **{
                        field: position[field]
                        for field in ("cusip", "issuer", "security_class", "put_call", "share_type")
                    },
                    "kind": kind,
                    "previous_quantity": str(old),
                    "current_quantity": str(new),
                    "quantity_change": str(new - old),
                    "value_usd": str(current[key]["value_usd"] if key in current else Decimal(0)),
                }
            )
    return {
        "quarter": quarter.isoformat(),
        "previous_quarter": prior.isoformat(),
        "status": "unavailable" if error else "available",
        "reason": error,
        "source_urls": previous_sources + current_sources,
        "changes": changes,
    }
