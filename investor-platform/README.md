# Investor Platform

A local investor workspace inside Minerva. The app will own its PostgreSQL data; any migration from existing portfolio records is a one-time operation, not an application dependency.

IP-001 provides the React/TypeScript shell, Python API health check, live connection/recovery UI, and CI. Portfolio persistence and management begin in IP-002. The Portfolio and Research cards are explicitly marked as planned.

## Run locally

Prerequisites: uv 0.10.10, Node 22.23.2 (see `web/.node-version`), and pnpm 11.19.0. Python 3.12 is selected by `backend/.python-version` and can be installed by uv. No database, Docker, account, API key, or spreadsheet is needed for IP-001.

From the repository root, start the API in one terminal:

```sh
cd investor-platform/backend
uv sync --frozen
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

## Verify

From `investor-platform/backend`:

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

Browser tests start both servers if needed, or reuse local servers on the documented ports. Keep those servers running during the automated suite; perform the manual stop/restart check separately. CI starts its own servers and runs desktop/mobile Chromium tests. `pnpm preview` serves the built frontend on the same local port after stopping the dev server; keep the API running.

## Project boundaries

- `web/`: frontend, responsive styles, and browser tests.
- `backend/`: independent uv/hatchling project and API tests.
- `.github/workflows/investor-platform-ci.yml` at the repository root: checks on pull requests and pushes to main.
- [Implementation plan](docs/implementation-plan.md): one ticket per PR; SQL ownership and incremental portfolio features.
- [Architecture](docs/architecture.md): stack rationale and future boundaries, not a list of dependencies to install now.
- [IP-001 verification](docs/ip-001-verification.md): manual browser checks and automated coverage.

No imports from the legacy harness, sheet adapters, financial data, or mock portfolio values are included. Hosted authentication and deployment are separate later work; the current launch command is local-only.
