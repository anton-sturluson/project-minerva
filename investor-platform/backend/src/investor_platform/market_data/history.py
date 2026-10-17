"""Collect provider histories and convert foreign listings using dated FX."""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import localcontext

from investor_platform.domain import ACCOUNTING_PRECISION
from investor_platform.market_data import yahoo as market_yahoo
from investor_platform.market_data.listings import FOREIGN_LISTINGS, symbol_for
from investor_platform.market_data.types import BENCHMARKS, MAX_CLOSE_AGE, History, MarketDataError


def usd_history(local, fx):
    """Value a foreign listing on FX dates, using only already available local closes.

    A bounded previous close bridges different exchange holidays. The current day's
    FX still moves its USD value. Missing FX is never filled or replaced with today's rate.
    """
    closes, adjusted, dividends = {}, {}, {}
    local_days = sorted(local.close)
    if not local_days:
        raise ValueError("No foreign closing prices")
    index = 0
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        for day, rate in sorted(fx.close.items()):
            while index + 1 < len(local_days) and local_days[index + 1] <= day:
                index += 1
            previous = local_days[index]
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
    )


def security_histories(
    securities,
    start,
    end,
    *,
    provisional=False,
    convert_fx=True,
    engine=None,
    workspace_id=None,
    windows=None,
    refresh_after=None,
):
    """Fetch each listing once; optionally convert valuation histories to USD."""
    securities = list(securities)
    by_symbol = {symbol_for(s, provisional=provisional): s for s in securities}
    requests = {b: {} for b in BENCHMARKS}
    foreign = {}
    for security in securities:
        symbol = symbol_for(security, provisional=provisional)
        listing = FOREIGN_LISTINGS.get(security.exchange)
        if listing:
            currency = listing[1]
            requests[symbol] = {"currency": currency}
            if convert_fx:
                requests[f"{currency}USD=X"] = {"instruments": ("CURRENCY",)}
                foreign[symbol] = currency
        else:
            requests[symbol] = {}

    def fetch(symbol):
        first, last = (
            (start, end) if symbol in BENCHMARKS else (windows or {}).get(symbol, (start, end))
        )
        first -= MAX_CLOSE_AGE
        try:
            if engine is not None and os.environ.get("TIINGO_API_KEY") and symbol.endswith("USD=X"):
                from investor_platform.market_data.tiingo import fx_history

                try:
                    return symbol, fx_history(
                        symbol[:-5], first, last, engine, workspace_id, refresh_after=refresh_after
                    )
                except OSError:
                    # An optional provider outage must not disable validated Yahoo FX.
                    # Identity/price validation failures still propagate unchanged.
                    pass
            return symbol, market_yahoo.cached_history(
                symbol,
                first,
                last,
                engine=engine,
                workspace_id=workspace_id,
                refresh_after=refresh_after,
                **requests[symbol],
            )
        except (OSError, KeyError, TypeError, IndexError):
            if engine is not None and os.environ.get("TIINGO_API_KEY") and symbol in by_symbol:
                from investor_platform.market_data.tiingo import stock_history

                try:
                    return symbol, stock_history(
                        by_symbol[symbol],
                        first + MAX_CLOSE_AGE,
                        last,
                        engine,
                        workspace_id,
                        refresh_after=refresh_after,
                    )
                except (OSError, KeyError, TypeError, IndexError):
                    pass
            return symbol, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = dict(pool.map(fetch, sorted(requests)))
    missing = [symbol for symbol, result in fetched.items() if result is None]
    if missing:
        raise MarketDataError(
            f"Missing historical prices: {', '.join(missing)}. "
            "Daily returns need closing prices between trades; transaction records are intact."
        )
    for symbol, currency in foreign.items():
        fetched[symbol] = usd_history(fetched[symbol], fetched[f"{currency}USD=X"])
    return fetched
