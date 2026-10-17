"""Authenticated Tiingo history, cached privately in PostgreSQL; never cache credentials."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from http.client import HTTPResponse
from typing import TYPE_CHECKING, cast
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import Engine

from investor_platform.domain import ACCOUNTING_PRECISION
from investor_platform.market_data.cache import cached_payload
from investor_platform.market_data.listings import EXCHANGES
from investor_platform.market_data.types import History, JsonValue, MarketDataError, MarketNumber
from investor_platform.market_data.yahoo import positive

if TYPE_CHECKING:
    from investor_platform.ledger.schemas import SecurityView
    from investor_platform.models import Security

PROVIDER: str = "tiingo"
EXCHANGE_CODES: dict[str, str] = {
    "NYSE": "NYQ",
    "NASDAQ": "NMS",
    "NYSE ARCA": "PCX",
    "NYSEARCA": "PCX",
    "NYSE MKT": "ASE",
    "AMEX": "ASE",
    "BATS": "BTS",
    "PINK": "PNK",
    "OTCQX": "OQX",
    "OTCQB": "OQB",
}


def get(path: str, key: str) -> JsonValue:
    """Read provider JSON while keeping credentials out of public failure messages."""
    request: Request = Request(
        "https://api.tiingo.com/tiingo/" + path,
        headers={"Authorization": "Token " + key, "Accept": "application/json"},
    )
    response: HTTPResponse
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response, parse_float=str)
    except (OSError, ValueError) as exc:
        # No headers, token-bearing URLs, or provider response bodies in public errors.
        raise MarketDataError(
            "Tiingo history unavailable; check the key or provider quota"
        ) from exc


def payload(
    engine: Engine | None,
    workspace_id: UUID | None,
    symbol: str,
    start: date,
    end: date,
    *,
    fx: bool = False,
    refresh_after: datetime | None = None,
) -> dict[str, JsonValue]:
    """Load and validate a private dated stock or FX payload before caching it."""
    key: str | None = os.environ.get("TIINGO_API_KEY")
    if not key:
        raise MarketDataError("Historical fallback requires TIINGO_API_KEY")
    cache_symbol: str = ("fx:" if fx else "stock:") + symbol

    def load(first: date, last: date) -> dict[str, JsonValue]:
        """Fetch a complete cache window and validate its provider identities."""
        query: str = urlencode({"startDate": first, "endDate": last})
        safe: str = quote(symbol, safe="")
        body: dict[str, JsonValue]
        if fx:
            body = {"rows": get(f"fx/{safe}/prices?{query}&resampleFreq=1day", key)}
            parse_fx(body, symbol)
        else:
            body = {
                "meta": get(f"daily/{safe}", key),
                "rows": get(f"daily/{safe}/prices?{query}", key),
            }
            parse_stock(body, symbol)
        return body

    return cached_payload(
        engine,
        workspace_id,
        PROVIDER,
        cache_symbol,
        start,
        end,
        load,
        refresh_after=refresh_after,
    )


def parse_stock(body: dict[str, JsonValue], symbol: str) -> History:
    """Validate Tiingo stock identity and retain its already as-traded prices."""
    meta: dict[str, str] = cast(dict[str, str], body["meta"])
    if meta["ticker"].upper() != symbol.upper():
        raise ValueError("Tiingo symbol identity does not match")
    close: dict[date, Decimal] = {}
    adjusted: dict[date, Decimal] = {}
    dividends: dict[date, Decimal] = {}
    splits: set[date] = set()
    row: dict[str, MarketNumber]
    for row in cast(list[dict[str, MarketNumber]], body["rows"]):
        day: date = date.fromisoformat(cast(str, row["date"])[:10])
        if day in close:
            raise ValueError("Duplicate Tiingo price date")
        # Tiingo close is already as-traded: do NOT undo later splits a second time.
        close[day], adjusted[day] = positive(row["close"]), positive(row["adjClose"])
        amount: Decimal = Decimal(str(row["divCash"]))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid Tiingo distribution")
        if amount:
            dividends[day] = amount
        if positive(row["splitFactor"]) != 1:
            splits.add(day)
    if not close:
        raise ValueError("No Tiingo sessions in the requested window")
    return History(
        close,
        adjusted,
        dividends,
        splits,
        EXCHANGE_CODES.get(meta["exchangeCode"], ""),
        source="Tiingo daily history",
    )


def stock_history(
    security: Security | SecurityView,
    start: date,
    end: date,
    engine: Engine | None,
    workspace_id: UUID | None,
    *,
    refresh_after: datetime | None = None,
) -> History:
    """Read a confirmed USD listing, honoring only explicitly dated identity exceptions."""
    if security.currency != "USD" or security.exchange not in EXCHANGES:
        raise ValueError("Tiingo fallback requires a confirmed US listing and USD records")
    # Providers describe the current exchange, even when the requested history predates a move.
    # Such exceptions require explicit, dated evidence stored with this security.
    review: dict[str, str] | None = cast(
        dict[str, str] | None, (security.market_identity or {}).get(PROVIDER)
    )
    symbol: str = review["symbol"] if review else security.ticker
    body: dict[str, JsonValue] = payload(
        engine, workspace_id, symbol, start, end, refresh_after=refresh_after
    )
    result: History = parse_stock(body, symbol)
    if result.exchange not in EXCHANGES[security.exchange]:
        if not (
            review
            and review.get("source")
            and review.get("exchange") == security.exchange
            and date.fromisoformat(review["through"]) >= end
            and date.fromisoformat(review["from"]) <= start
        ):
            raise ValueError(f"{security.ticker}: verify historical Tiingo listing identity")
        result.exchange = EXCHANGE_CODES.get(
            security.exchange, sorted(EXCHANGES[security.exchange])[0]
        )
    return result


def parse_fx(body: dict[str, JsonValue], symbol: str) -> History:
    """Validate a Tiingo FX pair and convert reciprocal USD pairs on the same date."""
    closes: dict[date, Decimal] = {}
    row: dict[str, MarketNumber]
    ctx: Context
    for row in cast(list[dict[str, MarketNumber]], body["rows"]):
        if cast(str, row["ticker"]).lower() != symbol:
            raise ValueError("Tiingo FX pair does not match")
        day: date = date.fromisoformat(cast(str, row["date"])[:10])
        if day in closes:
            raise ValueError("Duplicate Tiingo FX date")
        with localcontext() as ctx:
            ctx.prec = ACCOUNTING_PRECISION
            rate: Decimal = positive(row["close"])
            closes[day] = Decimal(1) / rate if symbol.startswith("usd") else rate
    if not closes:
        raise ValueError("No Tiingo FX sessions")
    return History(closes, dict(closes), source="Tiingo daily FX")


def fx_history(
    currency: str,
    start: date,
    end: date,
    engine: Engine | None,
    workspace_id: UUID | None,
    *,
    refresh_after: datetime | None = None,
) -> History:
    """Read dated USD conversion rates for a supported source currency."""
    symbol: str = (
        currency.lower() + "usd"
        if currency in {"AUD", "EUR", "GBP", "NZD"}
        else "usd" + currency.lower()
    )
    return parse_fx(
        payload(engine, workspace_id, symbol, start, end, fx=True, refresh_after=refresh_after),
        symbol,
    )
