"""Read quantity cohorts and signed portfolio weight changes for one common quarter."""

from datetime import date
from decimal import Decimal, localcontext
from typing import TypedDict
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import ACCOUNTING_PRECISION
from .models import ResearchFiling, ResearchManager
from .research import (
    DB,
    Identity,
    PositionChange,
    manager_comparison,
    previous_quarter,
    quarter_end,
)
from .research_eligibility import Eligibility, manager_eligibility

router: APIRouter = APIRouter(prefix="/api/research")


class Contributor(TypedDict):
    """One manager's quantity direction and disclosed portfolio fractions."""

    slug: str
    name: str
    kind: str
    previous_quantity: str
    current_quantity: str
    previous_weight: str
    current_weight: str
    weight_change_pp: str
    source_urls: list[str]


class ActivityRow(TypedDict):
    """A CUSIP cohort with equal-weighted manager changes in percentage points."""

    cusip: str
    issuer: str
    security_class: str
    manager_count: int
    average_weight_change_pp: str
    contributors: list[Contributor]


def rank_cohort(rows: dict[str, ActivityRow], *, increased: bool) -> list[ActivityRow]:
    """Rank manager count before the signed cohort average and a stable CUSIP tie."""
    activity: ActivityRow
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        for activity in rows.values():
            activity["manager_count"] = len(activity["contributors"])
            total: Decimal = sum(
                (
                    Decimal(contributor["weight_change_pp"])
                    for contributor in activity["contributors"]
                ),
                Decimal(0),
            )
            activity["average_weight_change_pp"] = str(total / activity["manager_count"])

    def sort_key(item: ActivityRow) -> tuple[int, Decimal, str]:
        """Keep signed negative and positive averages without rounding or clamping."""
        average: Decimal = Decimal(item["average_weight_change_pp"])
        return (
            -item["manager_count"],
            average.copy_negate() if increased else average,
            item["cusip"],
        )

    return sorted(rows.values(), key=sort_key)


def activity_for_quarter(
    session: Session,
    managers: list[ResearchManager],
    periods: dict[UUID, set[date]],
    quarter: date,
    available_quarters: list[date],
) -> dict:
    """Compare each manager at the selected quarter, retaining exclusions and evidence."""
    prior: date = previous_quarter(quarter)
    increased: dict[str, ActivityRow] = {}
    decreased: dict[str, ActivityRow] = {}
    excluded: list[dict[str, str]] = []
    included: int = 0
    manager: ResearchManager
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        for manager in managers:
            name: str = manager.profile["name"]
            manager_periods: set[date] = periods.get(manager.id, set())
            eligibility: Eligibility = manager_eligibility(manager.profile, date.today())
            reason: str | None = eligibility["reason"]
            comparison: dict = {}
            changes: list[PositionChange] = []
            if reason is None and (quarter not in manager_periods or prior not in manager_periods):
                reason = "Missing selected or previous adjacent quarter"
            elif reason is None:
                comparison = manager_comparison(session, manager, quarter)
                changes = comparison["changes"]
                reason = comparison["reason"]
                if reason is None and (
                    not changes or any(change["weight_change"] is None for change in changes)
                ):
                    reason = "A quarter has zero disclosed portfolio value; weights are unavailable"
            if reason is not None:
                excluded.append({"slug": manager.slug, "name": name, "reason": reason})
                continue
            included += 1
            seen: set[str] = set()
            change: PositionChange
            for change in changes:
                if (
                    change["share_type"] != "SH"
                    or change["put_call"]
                    or change["category"] == "unchanged"
                    or Decimal(change["current_quantity"]) == Decimal(change["previous_quantity"])
                    or change["cusip"] in seen
                ):
                    continue
                seen.add(change["cusip"])
                cohort: dict[str, ActivityRow] = (
                    increased if change["category"] == "increased" else decreased
                )
                activity: ActivityRow = cohort.setdefault(
                    change["cusip"],
                    ActivityRow(
                        cusip=change["cusip"],
                        issuer=change["issuer"],
                        security_class=change["security_class"],
                        manager_count=0,
                        average_weight_change_pp="0",
                        contributors=[],
                    ),
                )
                # Completeness and positive totals above ensure these values are known.
                assert change["previous_weight"] is not None
                assert change["current_weight"] is not None
                assert change["weight_change"] is not None
                activity["contributors"].append(
                    Contributor(
                        slug=manager.slug,
                        name=name,
                        kind=change["kind"],
                        previous_quantity=change["previous_quantity"],
                        current_quantity=change["current_quantity"],
                        previous_weight=change["previous_weight"],
                        current_weight=change["current_weight"],
                        weight_change_pp=str(Decimal(change["weight_change"]) * 100),
                        source_urls=comparison["source_urls"],
                    )
                )
    return {
        "quarter": quarter.isoformat(),
        "previous_quarter": prior.isoformat(),
        "available_quarters": [period.isoformat() for period in available_quarters],
        "status": "available" if included else "unavailable",
        "reason": None
        if included
        else "No eligible managers have a usable adjacent-quarter comparison",
        "included_managers": included,
        "total_managers": len(managers),
        "excluded_managers": excluded,
        "increased": rank_cohort(increased, increased=True),
        "decreased": rank_cohort(decreased, increased=False),
    }


@router.get("/activity")
def get_activity(session: DB, actor: Identity, quarter: date | None = None) -> dict:
    """Select the newest usable common quarter, or inspect an explicit quarter."""
    if quarter is not None and not quarter_end(quarter):
        raise HTTPException(422, "Choose a calendar quarter end")
    managers: list[ResearchManager] = list(
        session.scalars(
            select(ResearchManager)
            .where(ResearchManager.workspace_id == actor.workspace_id)
            .order_by(ResearchManager.slug)
        )
    )
    periods: dict[UUID, set[date]] = {}
    # The selector reads filing metadata only, never historical holdings.
    manager_id: UUID
    period: date
    for manager_id, period in session.execute(
        select(ResearchFiling.manager_id, ResearchFiling.report_period)
        .join(ResearchManager, ResearchManager.id == ResearchFiling.manager_id)
        .where(ResearchManager.workspace_id == actor.workspace_id)
    ):
        if quarter_end(period):
            periods.setdefault(manager_id, set()).add(period)
    eligible_ids: set[UUID] = {
        manager.id
        for manager in managers
        if manager_eligibility(manager.profile, date.today())["status"] == "eligible"
    }
    available: list[date] = sorted(
        {
            period
            for manager_id, manager_periods in periods.items()
            if manager_id in eligible_ids
            for period in manager_periods
            if previous_quarter(period) in manager_periods
        },
        reverse=True,
    )
    if quarter is not None:
        return activity_for_quarter(session, managers, periods, quarter, available)
    newest_unavailable: dict | None = None
    for period in available:
        result: dict = activity_for_quarter(session, managers, periods, period, available)
        if result["included_managers"]:
            return result
        if newest_unavailable is None:
            newest_unavailable = result
    if newest_unavailable is not None:
        return newest_unavailable
    return {
        "quarter": None,
        "previous_quarter": None,
        "available_quarters": [],
        "status": "unavailable",
        "reason": "No eligible managers have an adjacent-quarter filing pair",
        "included_managers": 0,
        "total_managers": len(managers),
        "excluded_managers": [
            {
                "slug": manager.slug,
                "name": manager.profile["name"],
                "reason": manager_eligibility(manager.profile, date.today())["reason"]
                or "No adjacent-quarter filing pair has been imported",
            }
            for manager in managers
        ],
        "increased": [],
        "decreased": [],
    }
