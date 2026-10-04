# Investor Platform architecture

Updated: 2026-10-04. This describes the implemented application.

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

PostgreSQL owns portfolio state. There is no spreadsheet sync or runtime dependency on legacy Minerva packages. The transaction CLI imports a separate testing copy with retained source evidence; reconciliation remains explicit. Public Yahoo history receives only symbols and dates; financial reports are computed on demand and are not persisted snapshots. Missing or unsupported data stays explicit. ([Ledger rules](portfolio.md#cash-ledger-rules), [performance methodology](performance.md), [hit-rate methodology](hit-rate.md))

## Domain values and shared calculations

[Domain definitions](../backend/src/investor_platform/domain.py) define the stable `EntryKind` and `Currency` string enums and exact-arithmetic precision. API values and existing VARCHAR storage remain unchanged; historical SQL migrations retain their original literals. Provider limits and supported listings live in the market adapter. Imports and HTTP writes share trade construction, and correction previews reuse the active ledger view without rebuilding audit history. Frontend entry types and form choices derive from the same local [label and kind definitions](../web/src/records.ts). See the [ledger view](../backend/src/investor_platform/ledger.py) and [trade builder](../backend/src/investor_platform/trades.py).

## Market data and daily collection

Validated Yahoo and optional Tiingo inputs are cached privately by workspace; ledger values are recalculated for every report. The opt-in Tailscale worker collects daily at 17:00 America/New_York, with durable run status and bounded retries. ([Cache](../backend/src/investor_platform/market_cache.py), [collector](../backend/src/investor_platform/price_refresh.py), [daily prices](daily-prices.md))

## Future work

Add boundaries when their feature needs them. Research storage, hosted login, generated API clients and cloud infrastructure are not scaffolded. The [implementation plan](implementation-plan.md) tracks the small remaining increments.

## Portfolio boundary

`GET /api/accounts` lists only the authenticated owner’s workspace portfolios; `POST /api/accounts` creates or idempotently returns a matching named portfolio. Every ledger, correction and metric route includes an account UUID and checks ownership. Instruments are shared within a workspace, while lots, cash and request keys are scoped to their portfolio. The UI remounts the ledger subtree on selection changes and validates a saved selection against the owner-scoped list. The old singular account endpoint has been removed.

## References

### Implementation

- [Cache](../backend/src/investor_platform/market_cache.py), [collector](../backend/src/investor_platform/price_refresh.py) and [daily prices](daily-prices.md): implemented market-data lifecycle.

- [Operations](operations.md) and [portfolio guide](portfolio.md): runtime commands, ownership, workflows and limitations.
- [Backend](../backend/src/investor_platform/) and [frontend](../web/src/): implemented modules and request boundaries.
- [Migrations](../backend/migrations/): schema history and local owner initialization.
- [CI](../../.github/workflows/investor-platform-ci.yml): automated checks.
- [Tailscale](tailscale.md): private deployment configuration.
- [Performance](performance.md) and [hit rate](hit-rate.md): calculations and market-data constraints.
- [Homepage Club](../design/README.md): approved design.
