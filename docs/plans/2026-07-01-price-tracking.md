# Plan: 52-Week Price Position Tracking

## Goal

Track current price against the 52-week range for every company in the DB and sort by
where each sits in its band (`0` = on 52w low, `1` = on 52w high). Source is Yahoo Finance,
which covers US and international listings with one keyless call per ticker.

## Command surface

```
minerva portfolio prices              # read stored table, sorted by range_pct; zero network
minerva portfolio prices AAPL         # fetch + persist one ticker
minerva portfolio prices AAPL MSFT    # fetch + persist several
minerva portfolio prices --refresh    # fetch every company in the DB
```

Naming tickers (or `--refresh`) fetches live and upserts; naming nothing is a read-only view.

## Data source: Yahoo Finance chart endpoint

`GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d`
(header `User-Agent: Mozilla/5.0`). One call returns both current price and 52-week
high/low from `chart.result[0].meta`: `regularMarketPrice`, `fiftyTwoWeekLow`,
`fiftyTwoWeekHigh`, `currency`.

Unofficial endpoint: treat any non-2xx, empty `result`, or missing price as a per-ticker
failure (collected, never fatal). Prices are stored in native currency; `range_pct` is a
within-currency ratio so currency never affects it.

## Symbols and exchange

Yahoo needs exchange-suffixed symbols for non-US listings (`TOI` alone hits a different US
security; `TOI.V` is Topicus). Fix at the data layer:

- Add `exchange TEXT` to `companies` (human-readable market code, e.g. `TSX`, `ASX`, `LSE`,
  `TSE`, `TSXV`, `ETR`, `EPA`, `AMS`, `SWX`, `STO`, `BME`; NULL/empty ⇒ US).
- The Yahoo symbol is **derived**, not stored: `yahoo_symbol(ticker, exchange)` appends the
  suffix for the exchange (US ⇒ bare ticker; symbols already carrying a `.` pass through).
- Backfill `exchange` for the ~27 non-US names (validated against Yahoo). Fortnox (`FNOX`) is
  delisted (taken private 2025) — leaves it unresolvable by design.

## Data model (invest.db)

```sql
CREATE TABLE prices (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL, as_of TEXT NOT NULL,          -- as_of = ISO pull date (UTC)
    current REAL, wk52_low REAL, wk52_high REAL,
    currency TEXT, source TEXT NOT NULL DEFAULT 'yahoo',
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ticker, as_of)                              -- same-day re-pull upserts
);
CREATE VIEW price_position AS
SELECT ticker, as_of, current, wk52_low, wk52_high, currency,
       ROUND((current - wk52_low) / NULLIF(wk52_high - wk52_low, 0), 4) AS range_pct
FROM prices;
```

`range_pct` is computed on read, never stored, so a corrected input can't leave a stale
value. `NULLIF` guards the high == low divide-by-zero.

## Code

- `src/minerva/prices.py`:
  - `PriceRow`, `range_pct`, `ensure_schema`, `upsert_prices`, `read_positions` — schema/model
    and persistence. `read_positions` LEFT JOINs `companies` for the exchange label.
  - `yahoo_symbol(ticker, exchange)` — pure suffix derivation.
  - `tracked_companies(db)` — returns `(ticker, exchange)` for every non-empty ticker.
  - `fetch_price(ticker, *, exchange, session, limiter)` — one Yahoo call → `PriceRow`;
    retries transient empty responses, raises on genuine 404 (delisted).
  - `refresh_prices(db, companies, *, fetcher=fetch_price, limiter)` — orchestration; fetcher
    injectable so tests need no HTTP mock. `RateLimiter` at ~0.3s spacing (Yahoo tolerant;
    politeness only).
  - Float coercion reuses `minerva.formatting.to_float` (shared, not a local helper).
- `src/harness/commands/portfolio.py`: thin `prices` subcommand + dispatch. No API key.

## Tests (`tests/test_minerva/test_prices.py`, real temp DB, injectable fetcher)

`range_pct` math incl. high == low → None; upsert idempotency; `read_positions` sort order;
`yahoo_symbol` (US bare, TSX→`.TO`, TSXV→`.V`, ASX→`.AX`, already-suffixed passthrough);
`tracked_companies` returns ticker+exchange; `refresh_prices` persists all via fake fetcher
and isolates a raising ticker into `errors`; `RateLimiter` spacing.

## Out of scope

Currency/FX normalization for cross-listing price comparison; daily cron into the morning
brief; stale-listing cleanup in `companies` (e.g. delisted Fortnox).
