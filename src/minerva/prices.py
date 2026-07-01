"""52-week price position tracking.

Pulls current price and 52-week high/low from Yahoo Finance, persists dated
snapshots to invest.db, and reports where each ticker sits in its 52-week band:

    range_pct = (current - low) / (high - low)   # 0 = on 52w low, 1 = on 52w high

Yahoo covers US and international listings with one keyless call per ticker.
range_pct is computed on read (via the ``price_position`` view), never stored, so a
corrected input never leaves a stale value behind.

Network access is isolated in ``fetch_price`` and injected into ``refresh_prices`` as
a ``fetcher`` callable, which keeps the orchestration testable without mocking HTTP.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

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

# Mirrored in hard-disk/data/04-database/schema.sql. Kept here so tests and the CLI
# can materialize the table + view into any database without reading that file.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    current     REAL,
    wk52_low    REAL,
    wk52_high   REAL,
    currency    TEXT,
    source      TEXT NOT NULL DEFAULT 'yahoo',
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ticker, as_of)
);
CREATE VIEW IF NOT EXISTS price_position AS
SELECT
    ticker, as_of, current, wk52_low, wk52_high, currency,
    ROUND((current - wk52_low) / NULLIF(wk52_high - wk52_low, 0), 4) AS range_pct
FROM prices;
CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
CREATE INDEX IF NOT EXISTS idx_prices_asof   ON prices(as_of);
"""


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


def range_pct(row: PriceRow) -> float | None:
    """Position in the 52-week range, 0..1. None when undefined (no range / missing data)."""
    current, low, high = row.current, row.wk52_low, row.wk52_high
    if current is None or low is None or high is None:
        return None
    span = high - low
    if span == 0:
        return None
    return (current - low) / span


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
    """Create the prices table + view if absent. Idempotent."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()


def upsert_prices(db_path: str | Path, rows: Iterable[PriceRow]) -> int:
    """Insert or update snapshots, keyed on (ticker, as_of). Returns rows written."""
    written = 0
    with sqlite3.connect(str(db_path)) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO prices
                    (ticker, as_of, current, wk52_low, wk52_high, currency, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(ticker, as_of) DO UPDATE SET
                    current    = excluded.current,
                    wk52_low   = excluded.wk52_low,
                    wk52_high  = excluded.wk52_high,
                    currency   = excluded.currency,
                    source     = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    row.ticker,
                    row.as_of,
                    row.current,
                    row.wk52_low,
                    row.wk52_high,
                    row.currency,
                    row.source,
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
        as_of=datetime.now(timezone.utc).date().isoformat(),
        current=price,
        wk52_low=to_float(meta.get("fiftyTwoWeekLow")),
        wk52_high=to_float(meta.get("fiftyTwoWeekHigh")),
        currency=meta.get("currency"),
    )


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

