"""Read-only economics catalog and dated chart data; GET never fetches publishers."""

from dataclasses import asdict
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from investor_platform.db import CurrentActor, DatabaseSession
from investor_platform.economics.registry import SERIES, SOURCES, Series, Source
from investor_platform.economics.views import Point, point_view, points_for
from investor_platform.models import EconomicObservation, EconomicRefreshState

router: APIRouter = APIRouter(prefix="/api/research/economics")


def series_view(definition: Series, points: list[Point]) -> dict:
    """Expose a displayed definition, current coverage and provisional measurement flag."""
    latest: Point | None = points[-1] if points else None
    available: list[Point] = [point for point in points if point.value is not None]
    return {
        **asdict(definition),
        "observation_count": len(points),
        "available_start": available[0].date.isoformat() if available else None,
        "available_end": available[-1].date.isoformat() if available else None,
        "latest": point_view(latest) if latest else None,
    }


def current_rows(
    session: Session,
    workspace: UUID,
    key: str | tuple[str, ...] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[EconomicObservation]:
    """Select the most recently admitted version of each date within workspace scope."""
    query: Select[tuple[EconomicObservation]] = select(EconomicObservation).where(
        EconomicObservation.workspace_id == workspace
    )
    if key:
        query = query.where(
            EconomicObservation.series_key.in_(key)
            if isinstance(key, tuple)
            else EconomicObservation.series_key == key
        )
    if start:
        query = query.where(EconomicObservation.observation_date >= start)
    if end:
        query = query.where(EconomicObservation.observation_date <= end)
    return list(
        session.scalars(
            query.ext(
                distinct_on(EconomicObservation.series_key, EconomicObservation.observation_date)
            ).order_by(
                EconomicObservation.series_key,
                EconomicObservation.observation_date,
                EconomicObservation.id.desc(),
            )
        )
    )


@router.get("")
def catalog(request: Request, session: DatabaseSession, actor: CurrentActor) -> dict:
    """Return catalog metadata and persisted last-good facts without collecting data."""
    rows: list[EconomicObservation] = current_rows(session, actor.workspace_id)
    states: dict[str, EconomicRefreshState] = {
        state.provider: state
        for state in session.scalars(
            select(EconomicRefreshState).where(
                EconomicRefreshState.workspace_id == actor.workspace_id
            )
        )
    }
    sources: list[dict] = []
    source: Source
    for source in SOURCES:
        state: EconomicRefreshState | None = states.get(source.id)
        sources.append(
            {
                **asdict(source),
                "status": (
                    "disabled" if not source.enabled else state.status if state else "not_run"
                ),
                "last_attempt": state.last_attempt if state else None,
                "last_success": state.last_success if state else None,
                "next_due": state.next_due if state else None,
                "error": state.error if state else None,
            }
        )
    return {
        "automatic_collection_enabled": bool(request.app.state.economics_refresh),
        "sources": sources,
        "series": [
            series_view(definition, points_for(definition, rows))
            for definition in SERIES
            if definition.visible
        ],
    }


@router.get("/series/{key}")
def observations(
    key: str,
    session: DatabaseSession,
    actor: CurrentActor,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Return date-filtered current facts with citations and calculation components."""
    definition: Series | None = next((item for item in SERIES if item.key == key), None)
    if definition is None:
        raise HTTPException(404, "Economic series not found")
    if start and end and start > end:
        raise HTTPException(422, "Start must precede end")
    # Load comparison periods before applying the visible date range. Growth must use t-12,
    # even when that base month is outside the selected chart window.
    rows: list[EconomicObservation] = current_rows(
        session, actor.workspace_id, definition.inputs or (definition.key,)
    )
    history: list[Point] = points_for(definition, rows)
    points: list[Point] = [
        point
        for point in history
        if (start is None or point.date >= start) and (end is None or point.date <= end)
    ]
    return {
        "series": series_view(definition, history),
        "observations": [point_view(point) for point in points],
    }
