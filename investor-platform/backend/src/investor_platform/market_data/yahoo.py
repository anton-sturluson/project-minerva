"""Yahoo response parsing and validated history caching."""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from investor_platform.domain import Currency
from investor_platform.market_data.cache import cached_payload
from investor_platform.market_data.types import History


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
