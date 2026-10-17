"""Yahoo response parsing and validated persistent history cache."""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from http.client import HTTPResponse
from typing import Unpack, cast
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from investor_platform.domain import Currency
from investor_platform.market_data.cache import cached_payload
from investor_platform.market_data.types import History, HistoryOptions, JsonValue, MarketNumber


def positive(value: MarketNumber) -> Decimal:
    """Parse a finite positive price, split ratio or distribution."""
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError("Invalid market price")
    return value


def history(
    symbol: str,
    start: date,
    end: date,
    *,
    currency: str = Currency.USD,
    instruments: tuple[str, ...] = ("EQUITY", "ETF"),
) -> History:
    """Fetch validated Yahoo daily prices and restore their as-traded share units."""
    # Fetch through today even for historical reports: later splits adjust earlier closes.
    params: str = urlencode(
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
    request: Request = Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response: HTTPResponse
    with urlopen(request, timeout=6) as response:
        payload: dict[str, JsonValue] = json.load(response, parse_float=Decimal)
    chart: dict[str, JsonValue] = cast(dict[str, JsonValue], payload["chart"])
    result: dict[str, JsonValue] = cast(list[dict[str, JsonValue]], chart["result"])[0]
    meta: dict[str, str] = cast(dict[str, str], result["meta"])
    if meta["currency"] != currency:
        raise ValueError(f"Market currency is not {currency}")
    if meta["instrumentType"] not in instruments:
        raise ValueError("Unexpected market instrument type")
    tz: ZoneInfo = ZoneInfo(meta["exchangeTimezoneName"])

    def day(stamp: MarketNumber) -> date:
        """Interpret a provider timestamp in its listing's local timezone."""
        return datetime.fromtimestamp(int(stamp), tz).date()

    events: dict[str, dict[str, dict[str, MarketNumber]]] = cast(
        dict[str, dict[str, dict[str, MarketNumber]]], result.get("events", {})
    )
    splits: dict[date, Decimal] = {
        day(e["date"]): positive(e["numerator"]) / positive(e["denominator"])
        for e in events.get("splits", {}).values()
    }
    dates: list[date] = [day(t) for t in cast(list[MarketNumber], result.get("timestamp", []))]
    indicators: dict[str, list[dict[str, list[MarketNumber | None]]]] = cast(
        dict[str, list[dict[str, list[MarketNumber | None]]]], result["indicators"]
    )
    closes: list[MarketNumber | None] = indicators["quote"][0]["close"]
    adjusted: list[MarketNumber | None] = (
        closes if instruments == ("CURRENCY",) else indicators["adjclose"][0]["adjclose"]
    )
    prices: dict[date, Decimal] = {}
    returns: dict[date, Decimal] = {}
    d: date
    close: MarketNumber | None
    adj: MarketNumber | None
    split_date: date
    ratio: Decimal
    for d, close, adj in zip(dates, closes, adjusted, strict=True):
        if not start <= d <= end or close is None or adj is None:
            continue
        factor: Decimal = Decimal(1)
        for split_date, ratio in splits.items():
            if split_date > d:
                factor *= ratio
        prices[d] = positive(close) * factor  # Undo split adjustment for actual share units.
        returns[d] = positive(adj)
    dividends: dict[date, Decimal] = {}
    kind: str
    e: dict[str, MarketNumber]
    for kind in ("dividends", "capitalGains"):
        for e in events.get(kind, {}).values():
            d = day(e["date"])
            if not start <= d <= end:
                continue
            amount: Decimal = positive(e["amount"])
            for split_date, ratio in splits.items():
                if split_date > d:
                    amount *= ratio
            dividends[d] = dividends.get(d, Decimal(0)) + amount
    if not prices:
        raise ValueError("No completed market sessions in this period")
    return History(prices, returns, dividends, set(splits), meta["exchangeName"])


def cached_history(
    symbol: str,
    start: date,
    end: date,
    *,
    engine: Engine | None = None,
    workspace_id: UUID | None = None,
    refresh_after: datetime | None = None,
    **options: Unpack[HistoryOptions],
) -> History:
    """Cache a validated listing history without bypassing currency or instrument checks."""
    if engine is None:
        return history(symbol, start, end, **options)
    # Currency and instrument validation must not be bypassed by a cache hit.
    variant: str = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()[:12]

    def load(first: date, last: date) -> dict[str, JsonValue]:
        """Serialize validated history for the private provider cache."""
        result: History = history(symbol, first, last, **options)
        return {
            name: {day.isoformat(): str(value) for day, value in getattr(result, name).items()}
            for name in ("close", "adjusted", "dividends")
        } | {
            "splits": sorted(day.isoformat() for day in result.splits),
            "exchange": result.exchange,
            "source": result.source,
        }

    body: dict[str, JsonValue] = cached_payload(
        engine,
        workspace_id,
        "yahoo-v1",
        f"{symbol}:{variant}",
        start,
        end,
        load,
        refresh_after=refresh_after,
    )
    values: dict[str, dict[date, Decimal]] = {
        name: {
            date.fromisoformat(day): Decimal(value)
            for day, value in cast(dict[str, str], body[name]).items()
            if start <= date.fromisoformat(day) <= end
        }
        for name in ("close", "adjusted", "dividends")
    }
    return History(
        **values,
        splits={date.fromisoformat(day) for day in cast(list[str], body["splits"])},
        exchange=cast(str, body["exchange"]),
        source=cast(str, body["source"]),
    )
