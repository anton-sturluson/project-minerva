"""52-week price position tracking.

Pulls current price and 52-week high/low from Finnhub, persists dated snapshots
to invest.db, and reports where each ticker sits in its 52-week band:

    range_pct = (current - low) / (high - low)   # 0 = on 52w low, 1 = on 52w high

The derived range_pct is computed on read (via the ``price_position`` view), never
stored, so a corrected input never leaves a stale value behind.

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

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# Finnhub free tier allows 60 calls/min. We spend 2 calls per ticker, so pace to
# stay comfortably under the ceiling: ~50 calls/min => one call every 1.2s.
DEFAULT_MIN_INTERVAL = 1.2
MAX_RETRIES = 3
BACKOFF_CAP_SECONDS = 30.0

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
    low_date    TEXT,
    high_date   TEXT,
    source      TEXT NOT NULL DEFAULT 'finnhub',
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ticker, as_of)
);
CREATE VIEW IF NOT EXISTS price_position AS
SELECT
    ticker, as_of, current, wk52_low, wk52_high, low_date, high_date,
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
    low_date: str | None = None
    high_date: str | None = None
    source: str = "finnhub"


def range_pct(row: PriceRow) -> float | None:
    """Position in the 52-week range, 0..1. None when undefined (no range / missing data)."""
    current, low, high = row.current, row.wk52_low, row.wk52_high
    if current is None or low is None or high is None:
        return None
    span = high - low
    if span == 0:
        return None
    return (current - low) / span


class RateLimiter:
    """Monotonic spacer: guarantees at least ``min_interval`` seconds between acquires.

    Single-threaded and sleep-based on purpose — the price pull is sequential, so a
    simple pacer is enough and there is nothing to coordinate across threads.
    """

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


def tracked_tickers(db_path: str | Path, *, statuses: Sequence[str] = ("tracking", "owned")) -> list[str]:
    """Return non-null tickers for companies in the given statuses, alphabetically."""
    placeholders = ",".join("?" for _ in statuses)
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            f"SELECT ticker FROM companies "
            f"WHERE ticker IS NOT NULL AND ticker != '' AND status IN ({placeholders}) "
            f"ORDER BY ticker ASC",
            tuple(statuses),
        ).fetchall()
    return [r[0] for r in rows]


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
                    (ticker, as_of, current, wk52_low, wk52_high, low_date, high_date, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(ticker, as_of) DO UPDATE SET
                    current    = excluded.current,
                    wk52_low   = excluded.wk52_low,
                    wk52_high  = excluded.wk52_high,
                    low_date   = excluded.low_date,
                    high_date  = excluded.high_date,
                    source     = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    row.ticker,
                    row.as_of,
                    row.current,
                    row.wk52_low,
                    row.wk52_high,
                    row.low_date,
                    row.high_date,
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
        sql = (
            "SELECT p.* FROM price_position p "
            "JOIN (SELECT ticker, MAX(as_of) AS as_of FROM prices GROUP BY ticker) latest "
            "  ON p.ticker = latest.ticker AND p.as_of = latest.as_of"
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
    api_key: str,
    session: requests.Session | None = None,
    limiter: RateLimiter | None = None,
    as_of: str | None = None,
) -> PriceRow:
    """Fetch current price + 52-week band for one ticker from Finnhub.

    Two calls: /quote (current) and /stock/metric (52-week high/low). Honors the
    shared rate limiter and retries on HTTP 429 with backoff.
    """
    session = session or requests.Session()
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()

    quote = _finnhub_get(session, "/quote", {"symbol": ticker, "token": api_key}, limiter)
    metric = _finnhub_get(
        session, "/stock/metric", {"symbol": ticker, "metric": "price", "token": api_key}, limiter
    )
    m = metric.get("metric", {}) if isinstance(metric, dict) else {}

    return PriceRow(
        ticker=ticker.upper(),
        as_of=as_of,
        current=_as_float(quote.get("c")),
        wk52_low=_as_float(m.get("52WeekLow")),
        wk52_high=_as_float(m.get("52WeekHigh")),
        low_date=m.get("52WeekLowDate"),
        high_date=m.get("52WeekHighDate"),
    )


def refresh_prices(
    db_path: str | Path,
    tickers: Sequence[str],
    *,
    api_key: str,
    fetcher: Callable[..., PriceRow] = fetch_price,
    limiter: RateLimiter | None = None,
) -> dict[str, Any]:
    """Fetch each ticker, upsert into the DB, and report results.

    Per-ticker failures are collected, not fatal — one bad ticker never aborts the run.
    """
    ensure_schema(db_path)
    limiter = limiter or RateLimiter()
    session = requests.Session()

    fetched: list[PriceRow] = []
    errors: list[dict[str, str]] = []
    for ticker in tickers:
        try:
            row = fetcher(ticker, api_key=api_key, session=session, limiter=limiter)
            fetched.append(row)
        except Exception as exc:  # noqa: BLE001 — isolate one ticker's failure
            logger.warning("price fetch failed for %s: %s", ticker, exc)
            errors.append({"ticker": ticker, "error": str(exc)})

    if fetched:
        upsert_prices(db_path, fetched)

    return {"fetched": len(fetched), "errors": errors}


def _finnhub_get(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    limiter: RateLimiter | None,
) -> dict[str, Any]:
    """GET a Finnhub endpoint, pacing via the limiter and retrying on 429."""
    delay = 1.0
    for attempt in range(MAX_RETRIES + 1):
        if limiter is not None:
            limiter.acquire()
        resp = session.get(f"{FINNHUB_BASE_URL}{path}", params=params, timeout=30)
        if resp.status_code == 429 and attempt < MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else min(delay, BACKOFF_CAP_SECONDS)
            logger.warning("finnhub 429 on %s; backing off %.1fs", path, wait)
            time.sleep(wait)
            delay = min(delay * 2, BACKOFF_CAP_SECONDS)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # exhausted retries on 429
    return resp.json()


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
