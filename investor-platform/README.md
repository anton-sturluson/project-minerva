# Investor Platform

A local investor workspace inside Minerva. The app will own its PostgreSQL data; any migration from existing portfolio records is a one-time operation, not an application dependency.

IP-003 adds an auditable cash ledger to the persistent account. Record opening cash, deposits, and withdrawals; the balance is derived from dated entries. Positions and trades arrive next.

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
- [IP-001 verification](docs/ip-001-verification.md): manual browser checks and automated coverage.

No imports from the legacy harness, sheet adapters, financial data, or mock portfolio values are included. Hosted authentication and deployment are separate later work; the current launch command is local-only.

## Cash ledger rules

- Amounts are decimal strings, with at most 16 integer and 8 fractional digits. Browser displays retain exact stored values; no floating-point arithmetic is used for balances.
- Opening cash is the first entry and defines the start of tracking. Later entries cannot precede it. Starting with a deposit is also supported; an opening balance cannot be added afterwards.
- Dates are posting dates in UTC, not settlement accounting. No future-dated entries. Same-day order is the immutable database sequence, shown in activity order.
- Every write locks the account, checks its complete dated history, and commits atomically. Cash cannot become negative at any point. Concurrent withdrawals obey the same rule.
- A client-generated request key identifies a write. Retries with the same payload return the original entry; changed content with that key is rejected. The form retains its key after an uncertain response and its draft after validation errors.
- Records include creation time and owner identity. Entries cannot yet be edited or deleted; corrections are IP-005. Use synthetic records until that increment and backup/restore are ready.
