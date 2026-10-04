"""Authenticated Tiingo history, cached privately in PostgreSQL; never cache credentials."""

import json
import os
from datetime import date
from decimal import Decimal, localcontext
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .domain import ACCOUNTING_PRECISION
from .market import EXCHANGES, History, MarketDataError, positive
from .market_cache import cached_payload

PROVIDER = "tiingo"
EXCHANGE_CODES = {
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


def get(path, key):
    request = Request(
        "https://api.tiingo.com/tiingo/" + path,
        headers={"Authorization": "Token " + key, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response, parse_float=str)
    except (OSError, ValueError) as exc:
        # No headers, token-bearing URLs, or provider response bodies in public errors.
        raise MarketDataError(
            "Tiingo history unavailable; check the key or provider quota"
        ) from exc


def payload(engine, workspace_id, symbol, start, end, *, fx=False):
    key = os.environ.get("TIINGO_API_KEY")
    if not key:
        raise MarketDataError("Historical fallback requires TIINGO_API_KEY")
    cache_symbol = ("fx:" if fx else "stock:") + symbol

    def load(first, last):
        query = urlencode({"startDate": first, "endDate": last})
        safe = quote(symbol, safe="")
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

    return cached_payload(engine, workspace_id, PROVIDER, cache_symbol, start, end, load)


def parse_stock(body, symbol):
    meta = body["meta"]
    if meta["ticker"].upper() != symbol.upper():
        raise ValueError("Tiingo symbol identity does not match")
    close, adjusted, dividends, splits = {}, {}, {}, set()
    for row in body["rows"]:
        day = date.fromisoformat(row["date"][:10])
        if day in close:
            raise ValueError("Duplicate Tiingo price date")
        # Tiingo close is already as-traded: do NOT undo later splits a second time.
        close[day], adjusted[day] = positive(row["close"]), positive(row["adjClose"])
        amount = Decimal(str(row["divCash"]))
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


def stock_history(security, start, end, engine, workspace_id):
    if security.currency != "USD" or security.exchange not in EXCHANGES:
        raise ValueError("Tiingo fallback requires a confirmed US listing and USD records")
    # Providers describe the current exchange, even when the requested history predates a move.
    # Such exceptions require explicit, dated evidence stored with this security.
    review = (security.market_identity or {}).get(PROVIDER)
    symbol = review["symbol"] if review else security.ticker
    body = payload(engine, workspace_id, symbol, start, end)
    result = parse_stock(body, symbol)
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


def parse_fx(body, symbol):
    closes = {}
    for row in body["rows"]:
        if row["ticker"].lower() != symbol:
            raise ValueError("Tiingo FX pair does not match")
        day = date.fromisoformat(row["date"][:10])
        if day in closes:
            raise ValueError("Duplicate Tiingo FX date")
        with localcontext() as ctx:
            ctx.prec = ACCOUNTING_PRECISION
            rate = positive(row["close"])
            closes[day] = Decimal(1) / rate if symbol.startswith("usd") else rate
    if not closes:
        raise ValueError("No Tiingo FX sessions")
    return History(closes, dict(closes), source="Tiingo daily FX")


def fx_history(currency, start, end, engine, workspace_id):
    symbol = (
        currency.lower() + "usd"
        if currency in {"AUD", "EUR", "GBP", "NZD"}
        else "usd" + currency.lower()
    )
    return parse_fx(payload(engine, workspace_id, symbol, start, end, fx=True), symbol)
