"""Small replaceable Yahoo adapter. Only public symbols/dates leave the app."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .domain import Currency

MAX_SECURITIES = 48
HISTORY_WINDOW = timedelta(days=3660)
MARKET_TIMEZONE = ZoneInfo("America/New_York")
SOURCE = "Yahoo Finance daily history"
BENCHMARKS = ("SPY", "QQQ")


@dataclass
class History:
    close: dict[date, Decimal]
    adjusted: dict[date, Decimal]
    dividends: dict[date, Decimal] = field(default_factory=dict)
    splits: set[date] = field(default_factory=set)
    exchange: str = ""


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
            amount = positive(e["amount"])
            for split_date, ratio in splits.items():
                if split_date > d:
                    amount *= ratio
            dividends[d] = dividends.get(d, Decimal(0)) + amount
    if not prices:
        raise ValueError("No completed market sessions in this period")
    return History(prices, returns, dividends, set(splits), result["meta"]["exchangeName"])


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
}

PROVIDER_EXCHANGES = frozenset().union(*EXCHANGES.values())


def symbol_for(security, *, provisional=False):
    supported = security.exchange in EXCHANGES or (
        provisional and security.exchange == "UNVERIFIED"
    )
    if security.currency != Currency.USD or not supported:
        raise ValueError(f"{security.ticker}: use a supported US exchange and USD")
    return security.ticker.replace(".", "-")


def verify_exchange(security, history, *, provisional=False):
    allowed = PROVIDER_EXCHANGES if provisional else EXCHANGES[security.exchange]
    if history.exchange not in allowed:
        raise ValueError(f"{security.ticker}: provider listing does not match {security.exchange}")


def histories(symbols, start, end):
    """Fetch each public symbol once, with bounded network concurrency."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(lambda symbol: (symbol, history(symbol, start, end)), sorted(symbols)))
