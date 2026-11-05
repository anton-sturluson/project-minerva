"""Collect provider histories and convert foreign listings using dated FX."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import Engine

from investor_platform.domain import ACCOUNTING_PRECISION
from investor_platform.market_data import yahoo as market_yahoo
from investor_platform.market_data.listings import FOREIGN_LISTINGS, symbol_for, verify_exchange
from investor_platform.market_data.types import (
    BENCHMARKS,
    MAX_CLOSE_AGE,
    History,
    HistoryOptions,
    MarketDataError,
    collected_at,
)

if TYPE_CHECKING:
    from investor_platform.ledger.schemas import SecurityView
    from investor_platform.models import Security


def usd_history(local: History, fx: History) -> History:
    """Value a foreign listing on FX dates, using only already available local closes.

    A bounded previous close bridges different exchange holidays. The current day's
    FX still moves its USD value. Missing FX is never filled or replaced with today's rate.
    """
    closes: dict[date, Decimal] = {}
    adjusted: dict[date, Decimal] = {}
    dividends: dict[date, Decimal] = {}
    local_days: list[date] = sorted(local.close)
    if not local_days:
        raise ValueError("No foreign closing prices")
    index: int = 0
    ctx: Context
    day: date
    rate: Decimal
    amount: Decimal
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        for day, rate in sorted(fx.close.items()):
            while index + 1 < len(local_days) and local_days[index + 1] <= day:
                index += 1
            previous: date = local_days[index]
            if previous > day or day - previous > MAX_CLOSE_AGE:
                continue
            # Carrying a pre-split share price across a missing split-day quote is unsafe.
            if any(previous < split <= day for split in local.splits):
                continue
            closes[day] = local.close[previous] * rate
            if previous in local.adjusted:
                adjusted[day] = local.adjusted[previous] * rate
        for day, amount in local.dividends.items():
            if day not in fx.close:
                raise ValueError(f"Missing USD exchange rate for distribution on {day}")
            dividends[day] = amount * fx.close[day]
    return History(
        closes,
        adjusted,
        dividends,
        local.splits,
        local.exchange,
        source=" + ".join(sorted({local.source, fx.source})),
        fetched_at=collected_at((local, fx)),
    )


def listing_history(
    security: Security | SecurityView,
    start: date,
    end: date,
    *,
    provisional: bool = False,
    engine: Engine | None = None,
    workspace_id: UUID | None = None,
    refresh_after: datetime | None = None,
) -> History:
    """Read one validated listing in its quote currency, with bounded prior closes."""
    symbol: str = symbol_for(security, provisional=provisional)
    foreign: tuple[str, str, set[str]] | None = FOREIGN_LISTINGS.get(security.exchange)
    options: HistoryOptions = {"currency": foreign[1]} if foreign else {}
    result: History
    try:
        result = market_yahoo.cached_history(
            symbol,
            start - MAX_CLOSE_AGE,
            end,
            engine=engine,
            workspace_id=workspace_id,
            refresh_after=refresh_after,
            **options,
        )
    except (OSError, KeyError, TypeError, IndexError):
        if foreign or engine is None or not os.environ.get("TIINGO_API_KEY"):
            raise
        from investor_platform.market_data.tiingo import stock_history

        result = stock_history(
            security, start, end, engine, workspace_id, refresh_after=refresh_after
        )
    verify_exchange(security, result, provisional=provisional)
    return result


def fx_history(
    currency: str,
    start: date,
    end: date,
    *,
    engine: Engine | None = None,
    workspace_id: UUID | None = None,
    refresh_after: datetime | None = None,
) -> History:
    """Read dated USD conversion rates; only provider availability permits fallback."""
    if engine is not None and os.environ.get("TIINGO_API_KEY"):
        from investor_platform.market_data import tiingo

        try:
            return tiingo.fx_history(
                currency, start, end, engine, workspace_id, refresh_after=refresh_after
            )
        except OSError:
            pass
    return market_yahoo.cached_history(
        f"{currency}USD=X",
        start,
        end,
        instruments=("CURRENCY",),
        engine=engine,
        workspace_id=workspace_id,
        refresh_after=refresh_after,
    )


def security_histories(
    securities: Iterable[Security | SecurityView],
    start: date,
    end: date,
    *,
    provisional: bool = False,
    convert_fx: bool = True,
    engine: Engine | None = None,
    workspace_id: UUID | None = None,
    windows: Mapping[str, tuple[date, date]] | None = None,
    refresh_after: datetime | None = None,
) -> dict[str, History]:
    """Fetch each listing once; optionally convert valuation histories to USD."""
    securities = list(securities)
    by_symbol: dict[str, Security | SecurityView] = {
        symbol_for(s, provisional=provisional): s for s in securities
    }
    requests: set[str] = set(BENCHMARKS) | set(by_symbol)
    foreign: dict[str, str] = {}
    security: Security | SecurityView
    symbol: str
    currency: str
    for security in securities:
        symbol = symbol_for(security, provisional=provisional)
        listing: tuple[str, str, set[str]] | None = FOREIGN_LISTINGS.get(security.exchange)
        if listing:
            currency = listing[1]
            if convert_fx:
                requests.add(f"{currency}USD=X")
                foreign[symbol] = currency

    def fetch(symbol: str) -> tuple[str, History | None]:
        """Read one bounded symbol history with the configured validated fallback."""
        first: date
        last: date
        first, last = (
            (start, end) if symbol in BENCHMARKS else (windows or {}).get(symbol, (start, end))
        )
        try:
            if symbol in by_symbol:
                return symbol, listing_history(
                    by_symbol[symbol],
                    first,
                    last,
                    provisional=provisional,
                    engine=engine,
                    workspace_id=workspace_id,
                    refresh_after=refresh_after,
                )
            if symbol.endswith("USD=X"):
                return symbol, fx_history(
                    symbol[:-5],
                    first - MAX_CLOSE_AGE,
                    last,
                    engine=engine,
                    workspace_id=workspace_id,
                    refresh_after=refresh_after,
                )
            return symbol, market_yahoo.cached_history(
                symbol,
                first - MAX_CLOSE_AGE,
                last,
                engine=engine,
                workspace_id=workspace_id,
                refresh_after=refresh_after,
            )
        except (OSError, KeyError, TypeError, IndexError):
            return symbol, None

    pool: ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched: dict[str, History | None] = dict(pool.map(fetch, sorted(requests)))
    missing: list[str] = [symbol for symbol, result in fetched.items() if result is None]
    if missing:
        raise MarketDataError(
            f"Missing historical prices: {', '.join(missing)}. "
            "Daily returns need closing prices between trades; transaction records are intact."
        )
    for symbol, currency in foreign.items():
        fetched[symbol] = usd_history(
            cast(History, fetched[symbol]), cast(History, fetched[f"{currency}USD=X"])
        )
    return cast(dict[str, History], fetched)
