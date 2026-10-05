"""Private provider cache; ledger-derived values are always recalculated."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import MarketCache

CACHE_TTL = timedelta(days=1)


def cached_payload(engine, workspace_id, provider, symbol, start, end, load, *, refresh_after=None):
    identity = (workspace_id, provider, symbol)
    with Session(engine) as session, session.begin():
        # Cross-process single flight, including a scheduled refresh racing a web request.
        lock = int.from_bytes(hashlib.sha256(str(identity).encode()).digest()[:8], signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        cached = session.get(MarketCache, identity)
        now = datetime.now(UTC)
        if (
            cached
            and cached.start <= start
            and cached.end >= end
            and now - cached.fetched_at < CACHE_TTL
            and (refresh_after is None or cached.fetched_at >= refresh_after)
        ):
            return cached.payload
        first = min(start, cached.start) if cached else start
        last = max(end, cached.end) if cached else end
        body = load(first, last)  # Validate before replacing a good cache. Failures roll back.
        if cached is None:
            cached = MarketCache(workspace_id=workspace_id, provider=provider, symbol=symbol)
            session.add(cached)
        cached.start, cached.end, cached.payload = first, last, body
        cached.fetched_at = datetime.now(UTC)
        return body
