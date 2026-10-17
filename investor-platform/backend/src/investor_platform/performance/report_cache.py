"""Bounded private memory cache for completed Post-mortem performance responses."""

import hashlib
import json
from collections import OrderedDict
from datetime import date, datetime
from threading import Lock
from time import monotonic
from typing import cast
from uuid import UUID

from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from investor_platform.db import Actor
from investor_platform.market_data import listings as market_listings
from investor_platform.market_data import types as market_types
from investor_platform.models import Account, LedgerEntry, MarketCache, Security

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
                "provisional": bool(account.reconstruction),
                "reconstruction": {
                    key: (account.reconstruction or {}).get(key)
                    for key in ("cash_method", "funding_status", "dividend_policy", "opening_cash")
                },
                "period": period,
                "market_date": market_date.isoformat(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    yahoo_symbols: set[str] = set(market_types.BENCHMARKS)
    tiingo_symbols: set[str] = set()
    for entry in entries:
        for security in (entry.security, entry.income_security):
            if security is None:
                continue
            yahoo_symbols.add(
                market_listings.symbol_for(security, provisional=bool(account.reconstruction))
            )
            review: dict = (security.market_identity or {}).get("tiingo", {})
            tiingo_symbols.add("stock:" + review.get("symbol", security.ticker))
            foreign: tuple | None = market_listings.FOREIGN_LISTINGS.get(security.exchange)
            if foreign:
                currency: str = foreign[1]
                yahoo_symbols.add(f"{currency}USD=X")
                pair: str = (
                    currency.lower() + "usd"
                    if currency in {"AUD", "EUR", "GBP", "NZD"}
                    else "usd" + currency.lower()
                )
                tiingo_symbols.add("fx:" + pair)
    provider: str
    symbol: str
    stamp: datetime
    revisions: list[tuple[str, str, str]] = []
    for provider, symbol, stamp in session.execute(
        select(MarketCache.provider, MarketCache.symbol, MarketCache.fetched_at)
        .where(
            MarketCache.workspace_id == actor.workspace_id,
            or_(
                and_(
                    MarketCache.provider == "yahoo-v1",
                    or_(
                        *(
                            MarketCache.symbol.startswith(symbol + ":", autoescape=True)
                            for symbol in yahoo_symbols
                        )
                    ),
                ),
                and_(MarketCache.provider == "tiingo", MarketCache.symbol.in_(tiingo_symbols)),
            ),
        )
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
