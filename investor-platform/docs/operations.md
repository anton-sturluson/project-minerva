# Operations

## Configuration and lifecycle

The `investor-api` entry point loads `backend/.env` when started from the backend directory; existing shell variables take precedence. Alembic and other commands still read `DATABASE_URL` from the shell. Run Alembic migrations after pulling changes. The default database is local PostgreSQL on port 55432; backend and frontend development ports are 8010 and 5173. Both bind to loopback, and port collisions fail rather than selecting another port. Optional frontend proxy configuration lives in `web/.env.example`.

The Compose volume persists records. Stop the database without deleting the volume:

```sh
docker compose -f investor-platform/compose.yml stop
```

Restart with the README's `up -d --wait` command. Stop app processes with Ctrl+C. Do not remove the database volume to restart the app. Verified backup/restore remains a separate feature; preserve a database backup before migrations or relying on imported records.

A seeded local owner is resolved at one API boundary. Every account route checks workspace ownership. `INVESTOR_MODE=tailscale` enables identity-checked private access; unknown modes refuse startup. See [Tailscale setup](tailscale.md) for the runner, access rules and troubleshooting. Public hosting and multi-user authentication are not implemented.

Account and ledger failures offer a manual retry. After an uncertain save, retry the unchanged form or inspect Activity before submitting again; reloading the page loses its in-memory retry key.

## Daily collection

Daily collection is opt-in: set `INVESTOR_DAILY_PRICES=1` in the ignored backend `.env` or exported environment; exported values take precedence. See [Daily prices](daily-prices.md) to enable the built-in 5 p.m. Eastern worker and inspect or retry runs. Migration 0013 persists collection status. The worker runs inside the API process; the Tailscale launcher does not configure operating-system auto-start or prevent host sleep.

The Portfolio and Post-mortem views show daily collection status, including worker liveness, last complete success, next due time and safe per-symbol failures. The authenticated `GET /api/market-data/status` endpoint reads this state without provider downloads. The launcher sets `INVESTOR_RELEASE` to the Git revision; both this status endpoint and `/api/health` report the loaded release. Restart a deployed API to load merged changes.

See [Economics collection](economics.md) for the separate opt-in Research collector, publisher frequencies, initial imports and source evidence storage. It uses the same API lifecycle pattern with source-specific due state; it does not change the daily price schedule.

## Verification

With PostgreSQL running, from `investor-platform/backend`:

```sh
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
```

From `investor-platform/web`:

```sh
pnpm format:check
pnpm build
pnpm exec playwright install chromium
pnpm test
```

Backend tests create and remove isolated `test_*` schemas in `TEST_DATABASE_URL` (defaults to the local database); they never reset portfolio tables. Browser tests use the configured application database: use a dedicated empty database for test runs because they create a synthetic “Browser test account”. Migrate it first.

Browser tests start both servers if needed, or reuse local servers on the documented ports. Keep those servers running during the automated suite; perform the manual stop/restart check separately. CI starts its own servers and runs desktop/mobile Chromium tests. `pnpm preview` serves the built frontend on the same local port after stopping the dev server; keep the API running.

## Project layout

- `web/`: interface, styles and desktop/mobile browser tests.
- `backend/`: independent uv/hatchling API project and accounting tests.
- `backend/migrations/`: reviewed PostgreSQL schema history.
- `.github/workflows/investor-platform-ci.yml`: build and test checks on pull requests and main.

## Privacy

Keep exports, PostgreSQL dumps, screenshots, credentials and account-specific configuration outside Git. Use synthetic fixtures for testing. See [privacy guidance](privacy.md).

## Historical data fallback

Set `TIINGO_API_KEY` in the ignored backend `.env` to enable Tiingo for unavailable US stock histories and dated FX. The key is sent only in an authorization header. Missing Yahoo quote currency or sessions can use this fallback; genuine currency, instrument or exchange mismatches still block the request. Foreign stock prices and benchmark total returns continue to use Yahoo.

Migration 0008 adds a workspace-scoped PostgreSQL provider cache shared by Yahoo and Tiingo, including holdings and hypothetical scorecards. Normal price reads reuse validated stored history that covers their requested dates, even after 24 hours. Uncovered ranges require a bounded provider fetch; narrower requests are sliced without later prices. Per-symbol locks prevent duplicate concurrent downloads. The daily collector and manual collection command require data collected after the attempt starts. A failed collection preserves accepted stored history and records the failure. Reload data rereads accepted prices and collection status; it does not force a provider download. See [Daily prices](daily-prices.md#data-and-freshness) for collection and session rules.

Provider validation options and workspace identity are part of the cache key. Every read retains listing, session, dated FX and split safeguards. Reports use current ledger records and accepted price revisions, so trade and cash edits require no manual cache invalidation. No credentials enter the cache. Only prices within a recorded holding window enter historical reports; Yahoo can read later splits to restore as-traded share units.

Provider listing metadata can describe a later exchange move. Such mismatches require an explicit `Security.market_identity["tiingo"]` review containing `symbol`, `exchange`, `from`, `through` and a source URL; it only applies within that date range. There are no ticker-specific exceptions in code. Cached histories retain provider listing identity, as-traded and adjusted closes, dividends and split events; Tiingo payloads also retain original provider metadata. Source names remain in the performance API. `fetched_at` on a report is its calculation time. `prices_fetched_at` is the oldest contributing provider collection time, or null when that provenance is unavailable. Neither calculation time nor a requested end date proves that a new close has arrived.

Only hashed JS/CSS build assets receive private immutable browser caching. HTML, errors and portfolio API responses remain `no-store` behind the existing access boundary.

When configured Tiingo FX is unavailable because of a transport/provider error, the same-date Yahoo FX path is tried. Provider identity and invalid-price errors still block the request; missing FX dates remain missing after fallback. Successful reports retain the provider actually used. ([Provider selection](../backend/src/investor_platform/market_data/history.py))

Tiingo's `close` is already in as-traded share units; unlike Yahoo's split-adjusted close, it must not be multiplied by subsequent split factors. FX uses the provider's date label and same-date daily close; inverse pairs are reciprocated, and missing FX dates remain missing. [Tiingo EOD fields](https://www.tiingo.com/documentation/end-of-day), [FX fields](https://www.tiingo.com/documentation/forex).

## References

- [Provider selection](../backend/src/investor_platform/market_data/history.py) — preferred FX and transport-failure fallback validation.

- [Quick start](../README.md) — local launch commands.
- [Application boundary](../backend/src/investor_platform/app.py) — local and Tailscale behavior.
- [CI workflow](../../.github/workflows/investor-platform-ci.yml) — required checks.
