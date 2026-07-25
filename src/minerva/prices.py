"""Yahoo price snapshots and completed daily market movements.

Pulls prices from Yahoo Finance, persists dated snapshots to invest.db, and
reports where each ticker sits in its 52-week band:

    range_pct = (current - low) / (high - low)   # 0 = on 52w low, 1 = on 52w high

Yahoo covers US and international listings with one keyless call per ticker.
range_pct is computed on read (via the ``price_position`` view), never stored, so a
corrected input never leaves a stale value behind.

Network access stays behind injectable fetchers, keeping orchestration testable
without live HTTP.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from minerva.formatting import to_float

logger = logging.getLogger(__name__)

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Yahoo is tolerant of request volume; this spacing is politeness, not a hard limit.
DEFAULT_MIN_INTERVAL = 0.3

# Exchange code -> Yahoo symbol suffix. US listings (empty/None exchange) use the
# bare ticker. Symbols already carrying a "." pass through unchanged.
_EXCHANGE_SUFFIX = {
    "TSX": ".TO",
    "TSXV": ".V",
    "ASX": ".AX",
    "LSE": ".L",
    "TSE": ".T",     # Tokyo
    "ETR": ".DE",    # Xetra
    "EPA": ".PA",    # Euronext Paris
    "AMS": ".AS",    # Euronext Amsterdam
    "SWX": ".SW",    # SIX Swiss
    "STO": ".ST",    # Nasdaq Stockholm
    "BME": ".MC",    # Madrid
}

# Runtime source of truth for the prices schema. ``ensure_schema`` creates fresh
# databases and migrates existing workspace databases without an external file.
_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS prices (
    id              INTEGER PRIMARY KEY,
    ticker          TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    current         REAL,
    wk52_low        REAL,
    wk52_high       REAL,
    currency        TEXT,
    source          TEXT NOT NULL DEFAULT 'yahoo',
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    previous_close  REAL,
    change_pct      REAL,
    instrument_type TEXT NOT NULL DEFAULT 'security',
    UNIQUE (ticker, as_of)
);
CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
CREATE INDEX IF NOT EXISTS idx_prices_asof   ON prices(as_of);
"""

_PRICE_POSITION_SQL = """
DROP VIEW IF EXISTS price_position;
CREATE VIEW price_position AS
SELECT
    ticker, as_of, current, wk52_low, wk52_high, currency,
    ROUND((current - wk52_low) / NULLIF(wk52_high - wk52_low, 0), 4) AS range_pct,
    previous_close, change_pct, instrument_type
FROM prices;
"""

_MIGRATION_COLUMNS = {
    "previous_close": "REAL",
    "change_pct": "REAL",
    "instrument_type": "TEXT NOT NULL DEFAULT 'security'",
}


@dataclass(slots=True)
class PriceRow:
    """One dated price snapshot for a ticker."""

    ticker: str
    as_of: str
    current: float | None
    wk52_low: float | None
    wk52_high: float | None
    currency: str | None = None
    source: str = "yahoo"
    previous_close: float | None = None
    change_pct: float | None = None
    instrument_type: str = "security"


def range_pct(row: PriceRow) -> float | None:
    """Position in the 52-week range, 0..1. None when undefined (no range / missing data)."""
    current, low, high = row.current, row.wk52_low, row.wk52_high
    if current is None or low is None or high is None:
        return None
    span = high - low
    if span == 0:
        return None
    return (current - low) / span


def daily_change_pct(current: float | None, previous: float | None) -> float | None:
    """Return close-to-close change in percentage points, rounded deterministically."""
    if current is None or previous in {None, 0}:
        return None
    return round((current - previous) / previous * 100, 6)


def yahoo_symbol(ticker: str, exchange: str | None) -> str:
    """Map a company ticker + exchange to the symbol Yahoo expects.

    US listings (no exchange) use the bare ticker. Symbols that already carry an
    exchange suffix (a ".") pass through unchanged.
    """
    ticker = ticker.strip().upper()
    if "." in ticker:
        return ticker
    suffix = _EXCHANGE_SUFFIX.get((exchange or "").strip().upper())
    return f"{ticker}{suffix}" if suffix else ticker


class RateLimiter:
    """Monotonic spacer: guarantees at least ``min_interval`` seconds between acquires."""

    def __init__(self, min_interval: float = DEFAULT_MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._last: float | None = None

    def acquire(self) -> None:
        now = time.monotonic()
        if self._last is not None:
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
        self._last = time.monotonic()


def default_db_path(workspace_root: str | Path) -> Path:
    """Locate invest.db under the workspace's database folder."""
    return Path(workspace_root) / "data" / "04-database" / "invest.db"


def tracked_companies(db_path: str | Path) -> list[tuple[str, str | None]]:
    """Return (ticker, exchange) for every company with a non-empty ticker, alphabetically."""
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT ticker, exchange FROM companies "
            "WHERE ticker IS NOT NULL AND ticker != '' ORDER BY ticker ASC"
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def ensure_schema(db_path: str | Path) -> None:
    """Create or minimally migrate the prices table and compatible view."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(_TABLE_SQL)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(prices)")}
        for name, declaration in _MIGRATION_COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE prices ADD COLUMN {name} {declaration}")
        conn.executescript(_PRICE_POSITION_SQL)
        conn.commit()


def upsert_prices(db_path: str | Path, rows: Iterable[PriceRow]) -> int:
    """Insert or update snapshots, keyed on (ticker, as_of). Returns rows written."""
    written = 0
    with sqlite3.connect(str(db_path)) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO prices
                    (ticker, as_of, current, wk52_low, wk52_high, currency, source,
                     fetched_at, previous_close, change_pct, instrument_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
                ON CONFLICT(ticker, as_of) DO UPDATE SET
                    current         = excluded.current,
                    wk52_low        = excluded.wk52_low,
                    wk52_high       = excluded.wk52_high,
                    currency        = excluded.currency,
                    source          = excluded.source,
                    fetched_at      = excluded.fetched_at,
                    previous_close  = COALESCE(excluded.previous_close, prices.previous_close),
                    change_pct      = CASE
                        WHEN excluded.previous_close IS NULL THEN prices.change_pct
                        ELSE excluded.change_pct
                    END,
                    instrument_type = excluded.instrument_type
                """,
                (
                    row.ticker,
                    row.as_of,
                    row.current,
                    row.wk52_low,
                    row.wk52_high,
                    row.currency,
                    row.source,
                    row.previous_close,
                    row.change_pct,
                    row.instrument_type,
                ),
            )
            written += 1
        conn.commit()
    return written


def read_positions(
    db_path: str | Path,
    *,
    tickers: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Read the latest snapshot per ticker, sorted ascending by range_pct (NULLs last).

    Rows sitting near their 52-week low come first; near their high come last.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        # Pull the exchange label from companies when that table exists (prices stores
        # only the ticker). A bare/fresh DB without companies still reads fine.
        has_companies = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='companies'"
        ).fetchone()
        exch_select = "c.exchange AS exchange" if has_companies else "NULL AS exchange"
        exch_join = "LEFT JOIN companies c ON UPPER(c.ticker) = p.ticker" if has_companies else ""
        sql = (
            f"SELECT p.*, {exch_select} FROM price_position p "
            "JOIN (SELECT ticker, MAX(as_of) AS as_of FROM prices GROUP BY ticker) latest "
            "  ON p.ticker = latest.ticker AND p.as_of = latest.as_of "
            f"{exch_join}"
        )
        params: list[Any] = []
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            sql += f" WHERE p.ticker IN ({placeholders})"
            params.extend(t.upper() for t in tickers)
        sql += " ORDER BY (p.range_pct IS NULL), p.range_pct ASC, p.ticker ASC"
        return [dict(r) for r in conn.execute(sql, params)]


def fetch_price(
    ticker: str,
    *,
    exchange: str | None = None,
    session: requests.Session | None = None,
    limiter: RateLimiter | None = None,
) -> PriceRow:
    """Fetch current price + 52-week band for one ticker from Yahoo Finance.

    One call to the chart endpoint. Raises on a missing/empty response so the caller
    records it as a per-ticker failure rather than persisting bogus data.
    """
    session = session or requests.Session()
    symbol = yahoo_symbol(ticker, exchange)

    if limiter is not None:
        limiter.acquire()
    resp = session.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"interval": "1d", "range": "1d"},
        headers=YAHOO_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"no chart data for {symbol}")
    meta = result[0].get("meta") or {}

    price = to_float(meta.get("regularMarketPrice"))
    if price is None:
        raise ValueError(f"no price in chart meta for {symbol}")

    return PriceRow(
        ticker=ticker.upper(),
        as_of=datetime.now(UTC).date().isoformat(),
        current=price,
        wk52_low=to_float(meta.get("fiftyTwoWeekLow")),
        wk52_high=to_float(meta.get("fiftyTwoWeekHigh")),
        currency=meta.get("currency"),
    )


def market_movement_from_chart(
    ticker: str,
    target_date: date,
    payload: dict[str, Any],
    *,
    instrument_type: str = "security",
    now: datetime | None = None,
) -> PriceRow:
    """Select the latest two completed Yahoo sessions on or before a date."""
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        raise ValueError(f"no chart data for {ticker}")
    chart = results[0]
    meta = chart.get("meta") or {}
    timezone_name = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        exchange_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown exchange timezone {timezone_name}") from exc

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    local_today = current_time.astimezone(exchange_timezone).date()
    completed_through = min(target_date, local_today)
    if completed_through == local_today:
        regular_end = to_float(
            ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("end")
        )
        if regular_end is None or current_time.timestamp() < regular_end:
            completed_through -= timedelta(days=1)

    timestamps = chart.get("timestamp") or []
    quotes = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    sessions: dict[date, float] = {}
    for timestamp, raw_close in zip(timestamps, closes, strict=False):
        close = to_float(raw_close)
        if close is None:
            continue
        session_date = (
            datetime.fromtimestamp(float(timestamp), tz=UTC)
            .astimezone(exchange_timezone)
            .date()
        )
        if session_date <= completed_through:
            sessions[session_date] = close

    selected = sorted(sessions.items())[-2:]
    if len(selected) < 2:
        raise ValueError(f"fewer than two completed trading sessions for {ticker}")
    (_, previous_close), (as_of, current_close) = selected

    return PriceRow(
        ticker=ticker.strip().upper(),
        as_of=as_of.isoformat(),
        current=current_close,
        wk52_low=to_float(meta.get("fiftyTwoWeekLow")),
        wk52_high=to_float(meta.get("fiftyTwoWeekHigh")),
        currency=meta.get("currency"),
        previous_close=previous_close,
        change_pct=daily_change_pct(current_close, previous_close),
        instrument_type=instrument_type,
    )


def fetch_market_movement(
    ticker: str,
    *,
    target_date: date,
    exchange: str | None = None,
    instrument_type: str = "security",
    session: requests.Session | None = None,
    limiter: RateLimiter | None = None,
) -> PriceRow:
    """Fetch Yahoo daily history and return one completed close-to-close movement."""
    session = session or requests.Session()
    symbol = yahoo_symbol(ticker, exchange)
    if limiter is not None:
        limiter.acquire()

    # Thirty-two calendar days comfortably spans ordinary exchange closures while
    # Yahoo timestamps, rather than calendar arithmetic, determine the two sessions.
    query_end = min(
        target_date + timedelta(days=1),
        datetime.now(UTC).date() + timedelta(days=1),
    )
    query_start = query_end - timedelta(days=32)
    response = session.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={
            "interval": "1d",
            "period1": int(
                datetime.combine(query_start, datetime_time(), tzinfo=UTC).timestamp()
            ),
            "period2": int(
                datetime.combine(query_end, datetime_time(), tzinfo=UTC).timestamp()
            ),
        },
        headers=YAHOO_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return market_movement_from_chart(
        ticker,
        target_date,
        response.json(),
        instrument_type=instrument_type,
    )


def download_market_data(
    db_path: str | Path,
    instruments: Sequence[tuple[str, str | None, str]],
    target_date: date,
    *,
    fetcher: Callable[..., PriceRow] | None = None,
    limiter: RateLimiter | None = None,
) -> dict[str, Any]:
    """Fetch and upsert daily movements with compact per-symbol accounting."""
    ensure_schema(db_path)
    active_fetcher = fetcher or fetch_market_movement
    limiter = limiter or RateLimiter()
    session = requests.Session()
    fetched: list[PriceRow] = []
    errors: list[dict[str, str]] = []

    for ticker, exchange, instrument_type in instruments:
        try:
            row = active_fetcher(
                ticker,
                target_date=target_date,
                exchange=exchange,
                instrument_type=instrument_type,
                session=session,
                limiter=limiter,
            )
            row.instrument_type = instrument_type
            row.change_pct = daily_change_pct(row.current, row.previous_close)
            fetched.append(row)
        except Exception as exc:  # noqa: BLE001 — isolate one symbol's failure
            logger.warning("market data fetch failed for %s: %s", ticker, exc)
            message = str(exc)
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                message = f"HTTP {exc.response.status_code}"
            errors.append({"symbol": ticker, "error": message})

    if fetched:
        upsert_prices(db_path, fetched)
    return {
        "requested": len(instruments),
        "written": len(fetched),
        "trading_dates": sorted({row.as_of for row in fetched}),
        "errors": errors,
    }


def refresh_prices(
    db_path: str | Path,
    companies: Sequence[tuple[str, str | None]],
    *,
    fetcher: Callable[..., PriceRow] = fetch_price,
    limiter: RateLimiter | None = None,
) -> dict[str, Any]:
    """Fetch each (ticker, exchange), upsert into the DB, and report results.

    Per-ticker failures are collected, not fatal — one bad ticker never aborts the run.
    """
    ensure_schema(db_path)
    limiter = limiter or RateLimiter()
    session = requests.Session()

    fetched: list[PriceRow] = []
    errors: list[dict[str, str]] = []
    for ticker, exchange in companies:
        try:
            fetched.append(fetcher(ticker, exchange=exchange, session=session, limiter=limiter))
        except Exception as exc:  # noqa: BLE001 — isolate one ticker's failure
            logger.warning("price fetch failed for %s: %s", ticker, exc)
            errors.append({"ticker": ticker, "error": str(exc)})

    if fetched:
        upsert_prices(db_path, fetched)

    return {"fetched": len(fetched), "errors": errors}
