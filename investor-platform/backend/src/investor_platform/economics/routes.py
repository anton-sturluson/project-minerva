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
from investor_platform.models import EconomicObservation, EconomicRefreshState

router: APIRouter = APIRouter(prefix="/api/research/economics")


def series_view(definition: Series, rows: list[EconomicObservation]) -> dict:
    """Expose definition and coverage, keeping exact values as decimal strings."""
    latest: EconomicObservation | None = rows[-1] if rows else None
    return {
        **asdict(definition),
        "observation_count": len(rows),
        "latest": (
            {
                "date": latest.observation_date.isoformat(),
                "value": str(latest.value) if latest.value is not None else None,
                "missing": latest.missing,
            }
            if latest
            else None
        ),
    }


def current_rows(
    session: Session,
    workspace: UUID,
    key: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[EconomicObservation]:
    """Select the most recently admitted version of each date within workspace scope."""
    query: Select[tuple[EconomicObservation]] = select(EconomicObservation).where(
        EconomicObservation.workspace_id == workspace
    )
    if key:
        query = query.where(EconomicObservation.series_key == key)
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
            series_view(definition, [row for row in rows if row.series_key == definition.key])
            for definition in SERIES
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
    rows: list[EconomicObservation] = current_rows(session, actor.workspace_id, key, start, end)
    return {
        "series": series_view(definition, rows),
        "observations": [
            {
                "date": row.observation_date.isoformat(),
                "value": str(row.value) if row.value is not None else None,
                "missing": row.missing,
                "source_url": row.provenance["source_url"],
                "footnotes": row.provenance["footnotes"],
                "derived_from": row.provenance["derived_from"],
                "collected_at": row.collected_at,
                "sha256": row.provenance["sha256"],
            }
            for row in rows
        ],
    }
