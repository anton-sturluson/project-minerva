# Investor Platform architecture

Updated: 2026-10-02. This describes the implemented application.

## Runtime

The platform is an independent project inside Minerva: a React/TypeScript frontend built with Vite, a Python 3.12 FastAPI backend packaged with uv/hatchling, and PostgreSQL with SQLAlchemy/Alembic migrations. Dependencies and lockfiles stay scoped to `web/` and `backend/`. Development uses Vite's API proxy; private access serves the built frontend from FastAPI. ([Setup](../README.md), [application factory](../backend/src/investor_platform/app.py))

## Boundaries

- `web/src/`: account and ledger forms, trade statistics, hit rate, and dated performance reports. Native controls and SVG charts follow [Homepage Club](../design/README.md).
- `backend/src/investor_platform/`: API endpoints, ownership checks, immutable records, accounting calculations, and public market-history access. Calculations accept records and market data rather than calling providers themselves.
- `backend/migrations/`: reviewed database history. Cash and trades share an account lock and transaction; balances and FIFO positions are derived from entries.
- `.github/workflows/investor-platform-ci.yml`: backend lint/tests and frontend formatting/build/browser checks using PostgreSQL and synthetic data.

These boundaries are implemented in the [backend](../backend/src/investor_platform/), [frontend](../web/src/), [migrations](../backend/migrations/) and [CI workflow](../../.github/workflows/investor-platform-ci.yml).

## Identity and data

A local owner/workspace is seeded by migrations. Every account route verifies ownership. Default mode accepts loopback access; private Tailscale mode verifies the configured identity, host and origin. Public hosting and multi-user login are not implemented. ([Identity boundary](../backend/src/investor_platform/db.py), [Tailscale setup](tailscale.md))

PostgreSQL owns portfolio state. There is no spreadsheet sync or runtime dependency on legacy Minerva packages. A future import is a deliberate migration into the ledger. Public Yahoo history receives only symbols and dates; financial reports are computed on demand and are not persisted snapshots. Missing or unsupported data stays explicit. ([Ledger rules](../README.md#cash-ledger-rules), [performance methodology](performance.md), [hit-rate methodology](hit-rate.md))

## Future work

Add boundaries when their feature needs them. Research storage, background jobs, hosted login, generated API clients and cloud infrastructure are not scaffolded. The [implementation plan](implementation-plan.md) tracks the small remaining increments.

## References

### Implementation

- [Setup and domain rules](../README.md): runtime commands, record ownership, supported workflows and limitations.
- [Backend](../backend/src/investor_platform/) and [frontend](../web/src/): implemented modules and request boundaries.
- [Migrations](../backend/migrations/): schema history and local owner initialization.
- [CI](../../.github/workflows/investor-platform-ci.yml): automated checks.
- [Tailscale](tailscale.md): private deployment configuration.
- [Performance](performance.md) and [hit rate](hit-rate.md): calculations and market-data constraints.
- [Homepage Club](../design/README.md): approved design.
