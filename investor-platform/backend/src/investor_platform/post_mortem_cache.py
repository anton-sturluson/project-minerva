"""Bounded private memory cache for completed Post-mortem performance responses."""

import hashlib
import json
from collections import OrderedDict
from datetime import date, datetime
from threading import Lock
from time import monotonic
from typing import cast
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .db import Actor
from .models import Account, LedgerEntry, MarketCache, Security

type CacheKey = tuple[Engine, UUID, UUID, UUID, str, str]
TTL_SECONDS: int = 300
MAX_REPORTS: int = 16
_reports: OrderedDict[CacheKey, tuple[float, bytes]] = OrderedDict()
_lock: Lock = Lock()


def cache_key(
    session: Session,
    actor: Actor,
    account: Account,
    entries: list[LedgerEntry],
    period: str,
    market_date: date,
) -> CacheKey:
    """Bind a response to its owner, active ledger, listing evidence and provider revision."""
    securities: dict[str, tuple[str, str, str, dict | None]] = {}
    entry: LedgerEntry
    for entry in entries:
        security: Security | None
        for security in (entry.security, entry.income_security):
            if security is not None:
                securities[str(security.id)] = (
                    security.ticker,
                    security.exchange,
                    security.currency,
                    security.market_identity,
                )
    fingerprint: str = hashlib.sha256(
        json.dumps(
            {
                "entries": [str(entry.id) for entry in entries],
                "securities": securities,
                "currency": account.base_currency,
                "reconstruction": account.reconstruction,
                "period": period,
                "market_date": market_date.isoformat(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    provider: str
    symbol: str
    stamp: datetime
    revisions: list[tuple[str, str, str]] = []
    for provider, symbol, stamp in session.execute(
        select(MarketCache.provider, MarketCache.symbol, MarketCache.fetched_at)
        .where(MarketCache.workspace_id == actor.workspace_id)
        .order_by(MarketCache.provider, MarketCache.symbol)
    ):
        revisions.append((provider, symbol, stamp.isoformat()))
    revision: str = hashlib.sha256(json.dumps(revisions).encode()).hexdigest()
    return (
        cast(Engine, session.get_bind()),
        actor.owner_id,
        actor.workspace_id,
        account.id,
        fingerprint,
        revision,
    )


def cached_report(key: CacheKey) -> bytes | None:
    """Return immutable response bytes while keeping memory and lifetime bounded."""
    with _lock:
        item: tuple[float, bytes] | None = _reports.get(key)
        if item is None:
            return None
        if item[0] <= monotonic():
            del _reports[key]
            return None
        _reports.move_to_end(key)
        return item[1]


def remember_report(key: CacheKey, body: bytes) -> None:
    """Store only a successfully calculated report under its pre-calculation revision."""
    with _lock:
        _reports[key] = (monotonic() + TTL_SECONDS, body)
        _reports.move_to_end(key)
        while len(_reports) > MAX_REPORTS:
            _reports.popitem(last=False)
