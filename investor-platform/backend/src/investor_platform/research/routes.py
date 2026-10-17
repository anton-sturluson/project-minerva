"""Research manager registry, coverage and comparison HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investor_platform.db import Actor, get_actor, get_session
from investor_platform.models import ResearchFiling, ResearchHolding, ResearchManager
from investor_platform.research.eligibility import manager_eligibility
from investor_platform.research.snapshots import (
    HoldingKey,
    Position,
    filing_state,
    load_holdings,
    manager_comparison,
    previous_quarter,
    snapshot,
)

router: APIRouter = APIRouter(prefix="/api/research")


DB = Annotated[Session, Depends(get_session)]


Identity = Annotated[Actor, Depends(get_actor)]


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


def manager_view(
    session: Session,
    manager: ResearchManager,
    *,
    detail: bool = False,
    filings: list[ResearchFiling] | None = None,
    holdings: dict[UUID, list[ResearchHolding]] | None = None,
) -> dict:
    """Report imported usable coverage separately from manager operating history."""
    filings = (
        filings
        if filings is not None
        else list(
            session.scalars(
                select(ResearchFiling)
                .where(ResearchFiling.manager_id == manager.id)
                .order_by(ResearchFiling.report_period.desc(), ResearchFiling.filed_date.desc())
            )
        )
    )
    by_period: dict[date, list[ResearchFiling]] = {}
    for filing in filings:
        by_period.setdefault(filing.report_period, []).append(filing)
    periods: list[date] = sorted(by_period)
    usable: list[date] = []
    period: date
    for period in periods:
        quarter_filings: list[ResearchFiling] = by_period[period]
        # Ordinary quarters need metadata only. Additions require identity overlap checks.
        if any(filing.amendment_type == "NEW HOLDINGS" for filing in quarter_filings):
            reason: str | None = snapshot(session, quarter_filings, holdings)[1]
        else:
            reason = "No original or restated holdings available"
            filing: ResearchFiling
            for filing in sorted(
                quarter_filings, key=lambda item: (item.filed_date, item.accession)
            ):
                reason = filing_state(filing, reason)[1]
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
    company_count: int | None = None
    latest_period: date | None = periods[-1] if periods else None
    if latest_period is not None and latest_period in usable:
        latest_positions: dict[HoldingKey, Position] = snapshot(
            session,
            [filing for filing in filings if filing.report_period == latest_period],
            holdings,
        )[0]
        company_count = len(
            {
                position["cusip"][:6]
                for position in latest_positions.values()
                if position["share_type"] == "SH"
                and not position["put_call"]
                and position["quantity"] > 0
            }
        )
    result: dict = {
        **manager.profile,
        "slug": manager.slug,
        "cik": manager.cik,
        "portfolio_company_count": company_count,
        "portfolio_company_count_quarter": latest_period.isoformat() if latest_period else None,
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
    filings: list[ResearchFiling] = list(
        session.scalars(
            select(ResearchFiling)
            .where(ResearchFiling.manager_id.in_([manager.id for manager in managers]))
            .order_by(ResearchFiling.report_period.desc(), ResearchFiling.filed_date.desc())
        )
    )
    grouped: dict[UUID, list[ResearchFiling]] = {}
    for filing in filings:
        grouped.setdefault(filing.manager_id, []).append(filing)
    amendment_periods: set[tuple[UUID, date]] = {
        (filing.manager_id, filing.report_period)
        for filing in filings
        if filing.amendment_type == "NEW HOLDINGS"
    }
    latest_periods: set[tuple[UUID, date]] = {
        (manager_id, max(filing.report_period for filing in manager_filings))
        for manager_id, manager_filings in grouped.items()
    }
    holdings: dict[UUID, list[ResearchHolding]] = load_holdings(
        session,
        [
            filing
            for filing in filings
            if (filing.manager_id, filing.report_period) in amendment_periods | latest_periods
        ],
    )
    return {
        "managers": [
            manager_view(session, manager, filings=grouped.get(manager.id, []), holdings=holdings)
            for manager in managers
        ]
    }


@router.get("/managers/{slug}")
def get_manager(slug: str, session: DB, actor: Identity) -> dict:
    """Read provenance and coverage for one manager."""
    return manager_view(session, owned_manager(session, actor, slug), detail=True)


@router.get("/managers/{slug}/changes")
def get_changes(slug: str, quarter: date, session: DB, actor: Identity) -> dict:
    """Compare quantities only across adjacent complete quarters and rank dollar changes."""
    return manager_comparison(session, owned_manager(session, actor, slug), quarter)


@router.get("/managers/{slug}/annual-changes")
def get_annual_changes(
    slug: str,
    year: Annotated[int, Query(ge=1901, le=9998)],
    session: DB,
    actor: Identity,
) -> dict:
    """Compare annual net holdings, using the latest loaded quarter for an unfinished year."""
    manager: ResearchManager = owned_manager(session, actor, slug)
    latest: date | None = session.scalar(
        select(func.max(ResearchFiling.report_period)).where(
            ResearchFiling.manager_id == manager.id
        )
    )
    end: date = latest if latest and latest.year == year else date(year, 12, 31)
    return {
        **manager_comparison(session, manager, end, prior=date(year - 1, 12, 31)),
        "year": year,
        "year_to_date": end.month != 12,
    }
