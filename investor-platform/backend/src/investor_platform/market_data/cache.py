"""Private provider cache used by live calculations and revision-keyed Post-mortem reports."""

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from investor_platform.market_data.types import JsonValue
from investor_platform.models import MarketCache

CACHE_TTL: timedelta = timedelta(days=1)


def cached_payload(
    engine: Engine | None,
    workspace_id: UUID | None,
    provider: str,
    symbol: str,
    start: date,
    end: date,
    load: Callable[[date, date], dict[str, JsonValue]],
    *,
    refresh_after: datetime | None = None,
) -> dict[str, JsonValue]:
    """Reuse a fresh covering payload or validate and store an expanded date range."""
    identity: tuple[UUID | None, str, str] = (workspace_id, provider, symbol)
    session: Session
    with Session(engine) as session, session.begin():
        # Cross-process single flight, including a scheduled refresh racing a web request.
        lock: int = int.from_bytes(hashlib.sha256(str(identity).encode()).digest()[:8], signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        cached: MarketCache | None = session.get(MarketCache, identity)
        now: datetime = datetime.now(UTC)
        if (
            cached
            and cached.start <= start
            and cached.end >= end
            and now - cached.fetched_at < CACHE_TTL
            and (refresh_after is None or cached.fetched_at >= refresh_after)
        ):
            return cached.payload
        first: date = min(start, cached.start) if cached else start
        last: date = max(end, cached.end) if cached else end
        # Validate before replacing a good cache. Failures roll back.
        body: dict[str, JsonValue] = load(first, last)
        if cached is None:
            cached = MarketCache(workspace_id=workspace_id, provider=provider, symbol=symbol)
            session.add(cached)
        cached.start, cached.end, cached.payload = first, last, body
        cached.fetched_at = datetime.now(UTC)
        return body
