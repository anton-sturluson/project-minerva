# Operations

## Configuration and lifecycle

The API reads `DATABASE_URL` from the shell; `backend/.env.example` documents it but is not loaded automatically. Run Alembic migrations after pulling changes. The default database is local PostgreSQL on port 55432; backend and frontend development ports are 8010 and 5173. Both bind to loopback, and port collisions fail rather than selecting another port. Optional frontend proxy configuration lives in `web/.env.example`.

The Compose volume persists records. Stop the database without deleting the volume:

```sh
docker compose -f investor-platform/compose.yml stop
```

Restart with the README's `up -d --wait` command. Stop app processes with Ctrl+C. Do not remove the database volume to restart the app. Verified backup/restore remains a separate feature; preserve a database backup before migrations or relying on imported records.

A seeded local owner is resolved at one API boundary. Every account route checks workspace ownership. `INVESTOR_MODE=tailscale` enables identity-checked private access; unknown modes refuse startup. See [Tailscale setup](tailscale.md) for the runner, access rules and troubleshooting. Public hosting and multi-user authentication are not implemented.

Account and ledger failures offer a manual retry. After an uncertain save, retry the unchanged form or inspect Activity before submitting again; reloading the page loses its in-memory retry key.

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

## References

- [Quick start](../README.md) — local launch commands.
- [Application boundary](../backend/src/investor_platform/app.py) — local and Tailscale behavior.
- [CI workflow](../../.github/workflows/investor-platform-ci.yml) — required checks.
