# Plan: 52-Week Price Position Tracking

## Goal

Track current price against the 52-week range for tracked companies, so we can sort by
where each stock sits in its band (0 = on 52w low, 1 = on 52w high). Data source is
Finnhub (already wired into the harness via `FINNHUB_API_KEY`).

## Command surface

```
minerva portfolio prices                 # read-only: print stored table, sorted by range_pct. Zero API calls.
minerva portfolio prices AAPL            # fetch AAPL live, upsert, print it
minerva portfolio prices AAPL MSFT       # fetch several, upsert, print them
minerva portfolio prices --refresh       # fetch ALL tracked companies, upsert all
```

**One rule:** naming tickers (or `--refresh`) fetches live + persists; naming nothing is a
read-only view. `--refresh` just means "the universe is every tracked company."

Refresh universe = `companies` where `status IN ('tracking','owned')`. (Exited/passed names
are excluded by default; `--all-status` flag can override if we want everything.)

## Data model

New table + view in `hard-disk/data/04-database/schema.sql` (idempotent, re-runnable):

```sql
CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    as_of       TEXT NOT NULL,            -- ISO date of the pull (UTC)
    current     REAL,
    wk52_low    REAL,
    wk52_high   REAL,
    low_date    TEXT,                     -- Finnhub 52WeekLowDate (bonus context)
    high_date   TEXT,                     -- Finnhub 52WeekHighDate
    source      TEXT NOT NULL DEFAULT 'finnhub',
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ticker, as_of)                -- one row per ticker per day; re-pull upserts
);
CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
CREATE INDEX IF NOT EXISTS idx_prices_asof   ON prices(as_of);

-- range_pct computed on read, never stored (avoids drift if inputs get corrected).
CREATE VIEW IF NOT EXISTS price_position AS
SELECT
    ticker, as_of, current, wk52_low, wk52_high, low_date, high_date,
    ROUND((current - wk52_low) / NULLIF(wk52_high - wk52_low, 0), 4) AS range_pct
FROM prices;
```

`range_pct = (current - low) / (high - low)` — bounded 0..1, comparable across companies.
`NULLIF` guards divide-by-zero when high == low.

Upsert keeps latest pull per (ticker, day):
`INSERT ... ON CONFLICT(ticker, as_of) DO UPDATE SET ...`.

## Finnhub calls (2 per ticker)

| Endpoint | Field | Meaning |
|---|---|---|
| `/quote?symbol=X` | `c` | current price (ignore `h`/`l` — those are today's intraday range) |
| `/stock/metric?symbol=X&metric=price` | `metric.52WeekHigh`, `metric.52WeekLow`, `...HighDate`, `...LowDate` | 52-week band |

## Rate limiting

Finnhub free tier: **60 calls/min**. We spend **2 calls/ticker**, so a full refresh of N
tickers = 2N calls.

- Pace all calls through a shared limiter that guarantees <= 60 calls/min with margin
  (target ~50/min → one call every ~1.2s). Simple sleep-based spacer keyed on a monotonic
  clock; no threads.
- On HTTP 429: respect `Retry-After` header if present, else exponential backoff
  (1s, 2s, 4s, cap 30s), max 3 retries, then record the ticker as an error and continue.
- Per-ticker failures never abort the whole run — collect into an errors list, report at end.
- ~30 tickers/min throughput. Fine for a portfolio-sized universe; if the tracked set grows
  past ~200 the full refresh takes a few minutes, which is acceptable for a daily pull.

## Code layout

- `src/minerva/prices.py` — pure logic, no Typer:
  - `PriceRow` dataclass (ticker, as_of, current, wk52_low, wk52_high, low_date, high_date)
  - `range_pct(row) -> float | None` — the formula, single source of truth
  - `RateLimiter` — monotonic spacer, `min_interval` configurable
  - `fetch_price(ticker, *, api_key, session, limiter) -> PriceRow` — the 2 Finnhub calls +
    429 handling. Network isolated here.
  - `upsert_prices(db_path, rows)` / `read_positions(db_path, *, tickers=None)` — sqlite3 CLI-free,
    use stdlib `sqlite3`.
  - `refresh_prices(db_path, tickers, *, api_key, fetcher=fetch_price, limiter=...)` —
    orchestration. `fetcher` is injectable so tests pass a fake (no requests mocking).
- `src/harness/commands/portfolio.py` — thin `prices` subcommand: parse args, resolve
  universe from DB when `--refresh`, call into `minerva.prices`, format output envelope.

## Tests (short, useful, no heavy mocking)

`tests/test_minerva/test_prices.py` (stdlib `unittest`, real temp sqlite DB):

1. `range_pct` math: low/mid/high positions, and high==low → None (no crash).
2. Upsert idempotency: two pulls same (ticker, day) → one row, latest wins.
3. `read_positions` ordering: rows come back sorted by range_pct; view computes it correctly.
4. `refresh_prices` with an injected fake fetcher (no network): given 3 fake tickers,
   3 rows land in DB with correct range_pct. One fetcher raising → recorded as error,
   others still persist.
5. `RateLimiter` spacing: two back-to-back acquisitions are >= min_interval apart
   (use a tiny interval so the test is fast, assert monotonic delta).

No mocking of `requests`. Network isolated behind the injectable `fetcher`; the real
`fetch_price` is exercised manually / left to a live smoke check, not the unit suite.

## Out of scope (for now)

- Automatic daily cron into the morning brief (easy follow-up once this is stable).
- Historical charting of range_pct over time (the table supports it; UI is later).

## TDD order

1. schema.sql additions + a schema-apply test (table + view exist).
2. `range_pct` + tests.
3. `upsert_prices` / `read_positions` + tests (temp DB).
4. `RateLimiter` + test.
5. `refresh_prices` with injectable fetcher + tests.
6. Real `fetch_price` (Finnhub) — thin, covered by a live smoke check.
7. Wire `portfolio prices` subcommand + dispatch.
8. Live smoke: `minerva portfolio prices AAPL` against real Finnhub.
