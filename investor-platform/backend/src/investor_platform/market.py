"""Small replaceable Yahoo adapter. Only public symbols/dates leave the app."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .domain import ACCOUNTING_PRECISION, Currency
from .market_cache import cached_payload

MAX_SECURITIES = 128
HISTORY_WINDOW = timedelta(days=3660)
SOURCE = "Yahoo Finance daily history"
BENCHMARKS = ("SPY", "QQQ")


class MarketDataError(OSError):
    """A public symbol could not be priced; carries no provider payload."""


@dataclass
class History:
    close: dict[date, Decimal]
    adjusted: dict[date, Decimal]
    dividends: dict[date, Decimal] = field(default_factory=dict)
    splits: set[date] = field(default_factory=set)
    exchange: str = ""
    source: str = SOURCE


def positive(value):
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError("Invalid market price")
    return value


def history(
    symbol: str, start: date, end: date, *, currency=Currency.USD, instruments=("EQUITY", "ETF")
) -> History:
    # Fetch through today even for historical reports: later splits adjust earlier closes.
    params = urlencode(
        {
            "period1": int(datetime.combine(start, time(), UTC).timestamp()),
            "period2": int(
                datetime.combine(
                    datetime.now(UTC).date() + timedelta(days=1), time(), UTC
                ).timestamp()
            ),
            "interval": "1d",
            "events": "div,splits,capitalGains",
            "includeAdjustedClose": "true",
        }
    )
    request = Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=6) as response:
        payload = json.load(response, parse_float=Decimal)
    result = payload["chart"]["result"][0]
    if result["meta"]["currency"] != currency:
        raise ValueError(f"Market currency is not {currency}")
    if result["meta"]["instrumentType"] not in instruments:
        raise ValueError("Unexpected market instrument type")
    tz = ZoneInfo(result["meta"]["exchangeTimezoneName"])

    def day(stamp):
        return datetime.fromtimestamp(int(stamp), tz).date()

    events = result.get("events", {})
    splits = {
        day(e["date"]): positive(e["numerator"]) / positive(e["denominator"])
        for e in events.get("splits", {}).values()
    }
    dates = [day(t) for t in result.get("timestamp", [])]
    closes = result["indicators"]["quote"][0]["close"]
    adjusted = (
        closes if instruments == ("CURRENCY",) else result["indicators"]["adjclose"][0]["adjclose"]
    )
    prices, returns = {}, {}
    for d, close, adj in zip(dates, closes, adjusted, strict=True):
        if not start <= d <= end or close is None or adj is None:
            continue
        factor = Decimal(1)
        for split_date, ratio in splits.items():
            if split_date > d:
                factor *= ratio
        prices[d] = positive(close) * factor  # Undo split adjustment for actual share units.
        returns[d] = positive(adj)
    dividends = {}
    for kind in ("dividends", "capitalGains"):
        for e in events.get(kind, {}).values():
            d = day(e["date"])
            if not start <= d <= end:
                continue
            amount = positive(e["amount"])
            for split_date, ratio in splits.items():
                if split_date > d:
                    amount *= ratio
            dividends[d] = dividends.get(d, Decimal(0)) + amount
    if not prices:
        raise ValueError("No completed market sessions in this period")
    return History(prices, returns, dividends, set(splits), result["meta"]["exchangeName"])


def cached_history(
    symbol, start, end, *, engine=None, workspace_id=None, refresh_after=None, **options
):
    if engine is None:
        return history(symbol, start, end, **options)
    # Currency and instrument validation must not be bypassed by a cache hit.
    variant = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()[:12]

    def load(first, last):
        result = history(symbol, first, last, **options)
        return {
            name: {day.isoformat(): str(value) for day, value in getattr(result, name).items()}
            for name in ("close", "adjusted", "dividends")
        } | {
            "splits": sorted(day.isoformat() for day in result.splits),
            "exchange": result.exchange,
            "source": result.source,
        }

    body = cached_payload(
        engine,
        workspace_id,
        "yahoo-v1",
        f"{symbol}:{variant}",
        start,
        end,
        load,
        refresh_after=refresh_after,
    )
    values = {
        name: {
            date.fromisoformat(day): Decimal(value)
            for day, value in body[name].items()
            if start <= date.fromisoformat(day) <= end
        }
        for name in ("close", "adjusted", "dividends")
    }
    return History(
        **values,
        splits={date.fromisoformat(day) for day in body["splits"]},
        exchange=body["exchange"],
        source=body["source"],
    )


EXCHANGES = {
    "NYSE": {"NYQ"},
    "XNYS": {"NYQ"},
    "NASDAQ": {"NMS", "NGM", "NCM"},
    "XNAS": {"NMS", "NGM", "NCM"},
    "NYSEARCA": {"PCX"},
    "ARCA": {"PCX"},
    "ARCX": {"PCX"},
    "AMEX": {"ASE"},
    "BATS": {"BTS"},
    "OTC": {"PNK", "OQB", "OQX"},
}

PROVIDER_EXCHANGES = frozenset().union(*EXCHANGES.values())

# Quote currency is independent of the ledger's USD settlement currency.
FOREIGN_LISTINGS = {
    "ASX": (".AX", "AUD", {"ASX"}),
    "TSXV": (".V", "CAD", {"VAN"}),
    "TSX": (".TO", "CAD", {"TOR"}),
    "XSTO": (".ST", "SEK", {"STO"}),
    "FNSE": (".ST", "SEK", {"STO"}),
    "WSE": (".WA", "PLN", {"WSE"}),
}
MAX_CLOSE_AGE = timedelta(days=4)


def symbol_for(security, *, provisional=False):
    if security.currency != Currency.USD:
        raise ValueError(f"{security.ticker}: recorded cash amounts must be in USD")
    if security.exchange in FOREIGN_LISTINGS:
        return security.ticker + FOREIGN_LISTINGS[security.exchange][0]
    supported = security.exchange in EXCHANGES or (
        provisional and security.exchange == "UNVERIFIED"
    )
    if not supported:
        raise ValueError(f"{security.ticker}: confirm a supported listing exchange")
    return security.ticker.replace(".", "-")


def verify_exchange(security, history, *, provisional=False):
    if security.exchange in FOREIGN_LISTINGS:
        allowed = FOREIGN_LISTINGS[security.exchange][2]
    elif provisional and security.exchange == "UNVERIFIED":
        allowed = PROVIDER_EXCHANGES
    else:
        allowed = EXCHANGES[security.exchange]
    if history.exchange not in allowed:
        raise ValueError(f"{security.ticker}: provider listing does not match {security.exchange}")


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
                from .tiingo import fx_history

                try:
                    return symbol, fx_history(
                        symbol[:-5], first, last, engine, workspace_id, refresh_after=refresh_after
                    )
                except OSError:
                    # An optional provider outage must not disable validated Yahoo FX.
                    # Identity/price validation failures still propagate unchanged.
                    pass
            return symbol, cached_history(
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
                from .tiingo import stock_history

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
