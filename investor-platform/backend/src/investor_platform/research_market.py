"""Resolve public research CUSIPs and summarize observed quarterly daily closes."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from http.client import HTTPException as HTTPClientError
from typing import Annotated, NotRequired, TypedDict
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from . import market, tiingo
from .domain import ACCOUNTING_PRECISION, Currency
from .market_cache import CACHE_TTL, cached_payload
from .models import MarketCache, ResearchFiling, ResearchHolding, ResearchManager
from .research import DB, Identity, previous_quarter, quarter_end

router: APIRouter = APIRouter(prefix="/api/research/activity")
MAPPING_PROVIDER: str = "openfigi-cusip-us-v1"
MAPPING_DATE: date = date(2000, 1, 1)
MAPPING_URL: str = "https://api.openfigi.com/v3/mapping"


class Mapping(TypedDict):
    """An exact US composite mapping or an explicit unusable mapping result."""

    symbol: str | None
    composite_figi: str | None
    reason: str | None
    mapped_at: str


class MarketContext(TypedDict):
    """Observed close statistics with dated public identity and provider evidence."""

    status: str
    reason: str | None
    symbol: str | None
    currency: str
    average_close_usd: str | None
    low_close_usd: str | None
    high_close_usd: str | None
    first_session: str | None
    last_session: str | None
    session_count: int
    source_urls: list[str]
    mapped_at: NotRequired[str]
    composite_figi: NotRequired[str]


def parse_mapping(body: dict) -> Mapping:
    """Require every returned US equity identity to agree on one composite and ticker."""
    result: Mapping = {
        "symbol": None,
        "composite_figi": None,
        "reason": "No exact US equity mapping available",
        "mapped_at": datetime.now(UTC).isoformat(),
    }
    rows: list[dict] | None = body.get("data")
    if not isinstance(rows, list) or not rows:
        return result
    identities: set[tuple[str, str]] = set()
    row: dict
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("marketSector") != "Equity"
            or row.get("exchCode") != "US"
            or not isinstance(row.get("compositeFIGI"), str)
            or not re.fullmatch(r"BBG[A-Z0-9]{9}", row["compositeFIGI"])
            or not isinstance(row.get("ticker"), str)
        ):
            result["reason"] = "Mapping identity could not be verified"
            return result
        identities.add((row["compositeFIGI"], row["ticker"]))
    if len(identities) != 1:
        result["reason"] = "Ambiguous CUSIP mapping; multiple security identities"
        return result
    composite: str
    symbol: str
    composite, symbol = next(iter(identities))
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", symbol):
        result["reason"] = "Mapped ticker format is unsupported by the price provider"
        return result
    result.update(symbol=symbol, composite_figi=composite, reason=None)
    return result


def fetch_mappings(cusips: list[str]) -> list[Mapping]:
    """Send at most ten exact mapping jobs without retrying provider quota failures."""
    if not 1 <= len(cusips) <= 10:
        raise ValueError("Mapping batches require one to ten CUSIPs")
    request: Request = Request(
        MAPPING_URL,
        data=json.dumps(
            [
                {
                    "idType": "ID_CUSIP",
                    "idValue": cusip,
                    "exchCode": "US",
                    "currency": "USD",
                    "marketSecDes": "Equity",
                }
                for cusip in cusips
            ]
        ).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=6) as response:
        body: list[dict] = json.load(response)
    if not isinstance(body, list) or len(body) != len(cusips):
        raise ValueError("Invalid mapping response")
    if any(not isinstance(item, dict) or "error" in item for item in body):
        raise ValueError("Invalid mapping result")
    return [parse_mapping(item) for item in body]


def resolve_mappings(engine: Engine, workspace_id: UUID, cusips: list[str]) -> dict[str, Mapping]:
    """Cache successful, unmatched and ambiguous mappings under the existing private cache."""
    found: dict[str, Mapping] = {}
    now: datetime = datetime.now(UTC)
    with Session(engine) as session:
        cached: MarketCache
        for cached in session.scalars(
            select(MarketCache).where(
                MarketCache.workspace_id == workspace_id,
                MarketCache.provider == MAPPING_PROVIDER,
                MarketCache.symbol.in_(cusips),
            )
        ):
            if now - cached.fetched_at < CACHE_TTL:
                found[cached.symbol] = cached.payload
    missing: list[str] = [cusip for cusip in cusips if cusip not in found]
    index: int
    for index in range(0, len(missing), 10):
        batch: list[str] = missing[index : index + 10]
        try:
            mappings: list[Mapping] = fetch_mappings(batch)
        except (OSError, HTTPClientError, ValueError, KeyError, TypeError):
            for cusip in missing[index:]:
                found[cusip] = {
                    "symbol": None,
                    "composite_figi": None,
                    "reason": "Security mapping provider unavailable; retry later",
                    "mapped_at": now.isoformat(),
                }
            break
        cusip: str
        mapping: Mapping
        for cusip, mapping in zip(batch, mappings, strict=True):

            def load(first: date, last: date, value: Mapping = mapping) -> Mapping:
                """Persist one already validated result using shared cache locking."""
                return value

            found[cusip] = cached_payload(
                engine,
                workspace_id,
                MAPPING_PROVIDER,
                cusip,
                MAPPING_DATE,
                MAPPING_DATE,
                load,
            )
    return found


def unavailable(mapping: Mapping, reason: str) -> MarketContext:
    """Return an explicit missing value without exposing provider error bodies."""
    result: MarketContext = {
        "status": "unavailable",
        "reason": reason,
        "symbol": mapping["symbol"],
        "currency": "USD",
        "average_close_usd": None,
        "low_close_usd": None,
        "high_close_usd": None,
        "first_session": None,
        "last_session": None,
        "session_count": 0,
        "source_urls": [],
        "mapped_at": mapping["mapped_at"],
    }
    if mapping["composite_figi"]:
        result["composite_figi"] = mapping["composite_figi"]
        result["source_urls"] = [f"https://www.openfigi.com/id/{mapping['composite_figi']}"]
    return result


def summarize(history: market.History, start: date, end: date, mapping: Mapping) -> MarketContext:
    """Compute the equal-session mean and range of actual daily closes in this quarter."""
    closes: dict[date, Decimal] = {
        day: value for day, value in history.close.items() if start <= day <= end
    }
    if not closes or any(not value.is_finite() or value <= 0 for value in closes.values()):
        raise ValueError("No valid completed sessions")
    result: MarketContext = unavailable(mapping, "")
    with localcontext() as context:
        context.prec = ACCOUNTING_PRECISION
        result.update(
            status="available",
            reason=None,
            average_close_usd=str(sum(closes.values(), Decimal(0)) / len(closes)),
            low_close_usd=str(min(closes.values())),
            high_close_usd=str(max(closes.values())),
            first_session=min(closes).isoformat(),
            last_session=max(closes).isoformat(),
            session_count=len(closes),
        )
    symbol: str = mapping["symbol"] or ""
    result["source_urls"].append(
        f"https://api.tiingo.com/tiingo/daily/{quote(symbol, safe='')}/prices"
        if history.source == "Tiingo daily history"
        else f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/history/"
    )
    return result


def price_context(
    engine: Engine, workspace_id: UUID, mapping: Mapping, start: date, end: date
) -> MarketContext:
    """Reuse validated cached daily histories with the configured optional Tiingo fallback."""
    if mapping["reason"] or not mapping["symbol"]:
        return unavailable(mapping, mapping["reason"] or "Security mapping unavailable")
    symbol: str = mapping["symbol"]
    history: market.History
    try:
        history = market.cached_history(
            symbol,
            start,
            end,
            engine=engine,
            workspace_id=workspace_id,
            currency=Currency.USD,
            instruments=("EQUITY", "ETF"),
        )
        if history.exchange not in market.PROVIDER_EXCHANGES:
            raise ValueError("Unsupported US listing exchange")
    except (OSError, HTTPClientError, ValueError, KeyError, TypeError, IndexError):
        if not os.environ.get("TIINGO_API_KEY"):
            return unavailable(mapping, "Daily closing prices unavailable for this quarter")
        try:
            body: dict = tiingo.payload(engine, workspace_id, symbol, start, end)
            if body.get("meta", {}).get("currency", "USD") != "USD":
                raise ValueError("Market currency is not USD")
            history = tiingo.parse_stock(body, symbol)
            if history.exchange not in market.PROVIDER_EXCHANGES:
                raise ValueError("Unsupported US listing exchange")
        except (OSError, HTTPClientError, ValueError, KeyError, TypeError, IndexError):
            return unavailable(mapping, "Daily closing prices unavailable for this quarter")
    try:
        return summarize(history, start, end, mapping)
    except ValueError:
        return unavailable(mapping, "No valid daily closing prices in this quarter")


@router.get("/market-context")
def get_market_context(
    quarter: date,
    cusips: Annotated[str, Query(min_length=9, max_length=199)],
    session: DB,
    actor: Identity,
) -> dict:
    """Price up to twenty ordinary-share identities already held in owned research filings."""
    requested: list[str] = cusips.split(",")
    if (
        not quarter_end(quarter)
        or len(requested) > 20
        or any(not re.fullmatch(r"[A-Z0-9]{9}", cusip) for cusip in requested)
    ):
        raise HTTPException(422, "Choose a calendar quarter end and at most twenty valid CUSIPs")
    requested = list(dict.fromkeys(requested))
    owned: set[str] = set(
        session.scalars(
            select(ResearchHolding.cusip)
            .join(ResearchFiling, ResearchHolding.filing_id == ResearchFiling.id)
            .join(ResearchManager, ResearchFiling.manager_id == ResearchManager.id)
            .where(
                ResearchManager.workspace_id == actor.workspace_id,
                ResearchFiling.report_period.in_([previous_quarter(quarter), quarter]),
                ResearchHolding.cusip.in_(requested),
                ResearchHolding.share_type == "SH",
                ResearchHolding.put_call == "",
                ResearchHolding.quantity > 0,
            )
        )
    )
    if owned != set(requested):
        raise HTTPException(404, "Requested security not found in workspace research filings")
    engine: Engine = session.get_bind().engine
    mappings: dict[str, Mapping] = resolve_mappings(engine, actor.workspace_id, requested)
    start: date = quarter.replace(month=((quarter.month - 1) // 3) * 3 + 1, day=1)

    def fetch(cusip: str) -> tuple[str, MarketContext]:
        """Load one public security history with bounded parallelism."""
        return cusip, price_context(engine, actor.workspace_id, mappings[cusip], start, quarter)

    with ThreadPoolExecutor(max_workers=4) as pool:
        prices: dict[str, MarketContext] = dict(pool.map(fetch, requested))
    return {"quarter": quarter.isoformat(), "prices": prices}
