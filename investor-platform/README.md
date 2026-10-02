# Investor Platform

A local investor workspace inside Minerva. The app will own its PostgreSQL data; any migration from existing portfolio records is a one-time operation, not an application dependency.

IP-004 adds opening positions, buys, sells, FIFO cost tracking, and a derived holdings table. Cash and positions commit together; account records survive restarts.

The interface uses the approved Homepage Club direction: warm paper, a serif masthead, bracket links, double rules, and small early-web badges. The [design reference and project skill](https://github.com/anton-sturluson/project-minerva/pull/103) are maintained separately from this app foundation.

## Run locally

Prerequisites: uv 0.10.10, Node 22.23.2 (see `web/.node-version`), and pnpm 11.19.0. Python 3.12 is selected by `backend/.python-version` and can be installed by uv. PostgreSQL 17 is required. Docker Compose is the documented setup; an existing local PostgreSQL installation works with `DATABASE_URL`. No API key or spreadsheet is required.

Start the database from the repository root:

```sh
docker compose -f investor-platform/compose.yml up -d --wait
```

This creates a persistent volume and binds PostgreSQL to `127.0.0.1:55432`. The example database password is for local development only. Use `docker compose -f investor-platform/compose.yml stop` to stop it without deleting records. Do not remove the volume to restart the app.

Then migrate and start the API:

```sh
cd investor-platform/backend
uv sync --frozen
uv run --frozen alembic upgrade head
uv run --frozen investor-api
```

In a second terminal, also starting from the repository root:

```sh
cd investor-platform/web
pnpm install --frozen-lockfile
pnpm dev
```

Open **http://127.0.0.1:5173/**. Both services bind to loopback. The frontend proxies `/api` to `http://127.0.0.1:8010`; optional `web/.env` configuration is documented in `web/.env.example`. Port collisions fail instead of silently changing the URL. Stop either process with Ctrl+C.

The page checks the service every five seconds, times out requests after three seconds, and allows manual retry. To verify recovery, stop the API, check for “Disconnected,” restart it, and check for “Connected.” This indicator verifies API connectivity only, not database readiness.

The backend reads `DATABASE_URL` from the shell; see `backend/.env.example` (not loaded automatically). Run migrations after pulling changes. A seeded local owner is resolved at a single API boundary; all account access checks workspace ownership. `INVESTOR_MODE` values other than `local` refuse startup until hosted authentication exists. Account currency is immutable through this API, including before ledger entries exist. Supported currencies are explicitly listed in the form.

## Verify

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

## Project boundaries

- `web/`: frontend, responsive styles, and browser tests.
- `backend/`: independent uv/hatchling project and API tests.
- `.github/workflows/investor-platform-ci.yml` at the repository root: checks on pull requests and pushes to main.
- [Implementation plan](docs/implementation-plan.md): one ticket per PR; SQL ownership and incremental portfolio features.
- [Architecture](docs/architecture.md): stack rationale and future boundaries, not a list of dependencies to install now.
- Verification: [IP-001 shell](docs/ip-001-verification.md), [IP-002 account](docs/ip-002-verification.md), [IP-003 cash](docs/ip-003-verification.md), and [IP-004 trades](docs/ip-004-verification.md).

No imports from the legacy harness, sheet adapters, live financial feeds, or seeded portfolio values are included. Hosted authentication and deployment are separate later work; the current launch command is local-only.

## Cash ledger rules

- Entered cash amounts are decimal strings, with at most 16 integer and 8 fractional digits. Browser displays retain exact stored values; no floating-point arithmetic is used for balances.
- Opening cash is the first entry and defines the start of tracking. Later entries cannot precede it. Starting with a deposit is also supported; an opening balance cannot be added afterwards.
- Dates are posting dates in UTC, not settlement accounting. No future-dated entries. Same-day order is the immutable database sequence, shown in activity order.
- Every write locks the account, checks its complete dated history, and commits atomically. Cash cannot become negative at any point. Concurrent withdrawals obey the same rule.
- A client-generated request key identifies a write. Retries with the same payload return the original entry; changed content with that key is rejected. Each form retains its key after an uncertain response and its draft after validation errors. Before reloading a page after an uncertain write, retry the unchanged form or inspect activity; request keys are held in the current form, not a persistent offline queue.
- Records include creation time and owner identity. Entries cannot yet be edited or deleted; corrections are IP-005. Use synthetic records until that increment and backup/restore are ready.

## Positions and trades

Open **Record a position or trade** below Holdings. Enter an exchange-qualified ticker and select opening position, buy, or sell. Securities must be equities denominated in the account currency; there is no symbol lookup or currency conversion. The same ticker on another exchange is a different security. Names are normalized to uppercase.

- An opening position records shares already owned without a cash trade. Its optional **total** cost basis includes any historical acquisition fees. Blank means unknown; zero is an explicit known zero. Record opening cash first if you need it, then opening positions before trades in each security.
- Buys debit quantity × price + fees. Sells credit quantity × price − fees; fees exceeding proceeds are unsupported. Quantity and price allow up to 12 integer and 8 fractional digits. Products and cash effects retain up to 16 decimal places without currency-cent rounding; figures represent entered records, not broker settlement calculations.
- Sales consume the oldest shares first (FIFO), ordered by effective date then saved sequence. Buy fees are included in lot basis and sell fees reduce proceeds. A partial lot's allocated basis rounds half-even at 16 decimal places; its final sale consumes the exact remaining basis so residuals reconcile.
- Unknown opening basis stays unknown. A sale that consumes any unknown-basis shares has no reported realized gain. Remaining holdings show unknown basis until those shares are exhausted. Sale details include FIFO realized P&L only when all consumed basis is known.
- Cash and shares must stay nonnegative throughout the full history, including after backdated writes. All cash and trade writers use the same account lock. A rejected write also rolls back any newly created security.
- Holdings and cash are derived from immutable entries. No editable balances, market valuations, returns, dividends, splits, shorts, margin, options, or foreign-currency trades in this increment. Corrections remain IP-005; backup/restore remains IP-007.

The forms record activity only; they never place orders. The development demo uses a separate synthetic database. Portfolio migration and real-data onboarding remain separate tasks.
