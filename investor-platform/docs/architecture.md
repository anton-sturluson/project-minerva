# Investor Platform: architecture proposal

Date: 2026-10-01
Status: draft for discussion; recommendations are not implemented.
Confirmed direction: a new project folder within Minerva; local app first, hosting later; portfolio tracking and research are the first two features.

Updated direction, 2026-10-01: portfolio management moves into the app. Spreadsheet import is optional migration work, not the first feature or a continuing dependency. Start with small, hardened native workflows. The [PR-by-PR implementation plan](implementation-plan.md) governs delivery order and supersedes the broader initial milestones below; the full layout is a future boundary map, not a scaffolding checklist.

## Recommendation

Build one modular Python backend, one React frontend, and one PostgreSQL database. Keep the product in `investor-platform/`, with explicit adapters to existing Minerva code and data. Run everything locally initially. Add managed identity and hosted infrastructure when remote access is needed.

This is an engineering recommendation based on the requested product and the repository inspection below. The official FastAPI full-stack template uses the same broad combination of Python, React, TypeScript, Vite, and PostgreSQL, providing a useful reference rather than a template we must adopt wholesale. ([FastAPI template](https://fastapi.tiangolo.com/project-generation/))

## What already exists

The root project uses Python 3.12+, uv, hatchling, Pydantic, pandas, and pytest. FastAPI is already a JobWatch dependency. These are useful existing conventions, although the new product should have its own dependency set. ([Root project configuration](../../pyproject.toml))

- `minerva portfolio sync` accepts local holdings/transaction sources and Google Sheet identifiers. The implementation stores normalized JSON, sync history, watchlists, and thesis cards. ([CLI](../../src/harness/commands/portfolio.py), [portfolio state](../../src/harness/portfolio_state.py))
- The existing transaction normalizer captures security, date, action, quantity, price, and notes. It has no explicit account, currency, fee, or external-cash-flow model. Rows without a security identifier are skipped. It cannot serve unchanged as a complete performance ledger. ([Normalizer](../../src/harness/portfolio_state.py))
- News ingestion and duplicate detection are importable Python code but use SQLite persistence. Price tracking currently focuses on current price and 52-week ranges, with an unofficial Yahoo endpoint; it is not a historical total-return data service. ([News](../../src/harness/news.py), [price design](../../docs/plans/2026-07-01-price-tracking.md))
- No checked-in GitHub Actions workflows were found. The root `.gitignore` ignores `uv.lock`; the platform needs an explicit exception for its own committed lockfile. ([Ignore rules](../../.gitignore); repository inspection, 2026-10-01)

The original research checked the prescribed knowledge location before drafting this proposal.

## Stack and alternatives

These choices are recommendations; links substantiate the capabilities used in making them.

| Layer | Proposed choice | Reason and tradeoff |
| --- | --- | --- |
| Frontend | React + TypeScript; React Router framework mode with Vite, initially SPA mode | Fits an interactive portfolio/research application. Gives us routing conventions without a runtime Node server. SPA deployments must route application URLs to the frontend entry page. ([SPA documentation](https://reactrouter.com/how-to/spa)) |
| Backend | Python 3.12 + FastAPI + Pydantic; uv + hatchling | Fits existing code and keeps calculations in Python. OpenAPI supplies the contract; defer generated TypeScript client tooling until the API warrants it. ([FastAPI features](https://fastapi.tiangolo.com/features/)) |
| Persistence | PostgreSQL; SQLAlchemy + Alembic | Use the same database family locally and when hosted, with reviewed schema migrations. Alembic provides migrations for SQLAlchemy. ([Alembic](https://alembic.sqlalchemy.org/en/latest/)) |
| UI components | A small shared component layer; choose table/chart packages in the UI milestone | Keep portfolio and research screens visually consistent without selecting every UI dependency before requirements are concrete. |
| Files | Local private directory behind a storage interface | Store file metadata in PostgreSQL; move file bytes to private object storage when hosting. This is a proposed application boundary. |
| Identity | Seeded local user and workspace; managed login later | Build ownership and authorization into the application now. Supabase Auth is the initial hosted candidate, with password, magic-link, and social login support. ([Auth documentation](https://supabase.com/docs/guides/auth)) |
| Background work | Python commands initially; a separate worker from the same backend package when durable jobs are needed | Imports and collection must have run records and idempotency. Add a queue when asynchronous, retryable work becomes a product requirement. |
| CI / later hosting | GitHub Actions; Docker image; Render as the initial hosting candidate | GitHub supports PostgreSQL service containers for tests. Render supports monorepo deployment and deployment after CI passes. ([GitHub](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers), [Render monorepos](https://render.com/docs/monorepo-support), [Render deployments](https://render.com/docs/deploys)) |

**Why not Next.js first?** Its server/client component model is useful when server-rendered public pages are central. Here, the first product is a local interactive app with a Python backend. My judgment is that a SPA gives us fewer runtime responsibilities. Reconsider if public, search-indexed research becomes a core feature. ([Next.js model](https://nextjs.org/docs/app/getting-started/server-and-client-components))

**Why not Django first?** Django's ORM, migrations, and generated admin make it a credible alternative, particularly for an administration-heavy product. I favor FastAPI for this API-oriented research application and its existing Python workflows. Django would also work; this is a fit decision, not a scalability limitation. ([Django overview](https://docs.djangoproject.com/en/stable/intro/overview/))

**Why PostgreSQL on a laptop?** It adds a local database service, but avoids making database migration part of the later launch. Docker Compose can make startup repeatable. SQLite would reduce setup, but my recommendation prioritizes parity with the intended hosted product.

## Proposed repository layout

This is the target layout, not a claim that these files already exist.

```text
project-minerva/
├── src/                         # existing Minerva libraries and CLI
├── dashboard/                   # existing JobWatch application
├── investor-platform/
│   ├── README.md
│   ├── web/
│   │   ├── package.json
│   │   ├── pnpm-lock.yaml
│   │   ├── app/
│   │   │   ├── routes/
│   │   │   ├── features/
│   │   │   │   ├── portfolio/
│   │   │   │   └── research/
│   │   │   ├── components/
│   │   │   └── api/             # generated client + transport
│   │   └── tests/
│   ├── backend/
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── src/investor_platform/
│   │   │   ├── app.py
│   │   │   ├── core/            # settings, DB, identity, storage
│   │   │   ├── identity/
│   │   │   ├── securities/      # companies, listings, stable IDs
│   │   │   ├── portfolio/       # ledger, positions, performance
│   │   │   ├── research/        # topics, sources, notes, theses
│   │   │   ├── integrations/    # Minerva, sheet, prices, news
│   │   │   └── jobs/
│   │   ├── migrations/
│   │   └── tests/
│   ├── contracts/              # generated OpenAPI schema
│   ├── infra/                  # Dockerfile; hosting config later
│   ├── compose.yaml
│   ├── .env.example
│   └── docs/
│       ├── architecture.md
│       └── research/
└── .github/workflows/
    └── investor-platform-ci.yml
```

Each substantial backend feature owns its routes, input/output schemas, services, persistence, and tests. HTTP handlers delegate to services. Financial calculations are pure Python functions that do not import FastAPI or depend on a database.

Use an independent backend uv project initially, with a committed lockfile and Python 3.12. Use pnpm only for the frontend. A uv workspace shares a lockfile; we can adopt one later if coordinated releases across Minerva become useful. ([uv workspace documentation](https://docs.astral.sh/uv/concepts/projects/workspaces/))

Start with native portfolio entry. Add read-only legacy import adapters only when needed for migration. When a Minerva function is worth reusing directly, declare a proper package dependency instead of editing `sys.path`. A dependency on the root package brings its dependency footprint; extract smaller shared packages only when there is demonstrated reuse. If builds depend on root code, use the repository root as Docker build context and include those paths in CI/deploy triggers.

The platform owns its PostgreSQL data. Existing CLI JSON/SQLite remains a legacy input until a deliberate migration; avoid two systems independently writing the same logical records.

## Feature boundaries and data model

All of the following are proposed product rules.

**Shared foundation:** users, workspaces, memberships, securities/listings, imports, source provenance. Use stable internal security IDs; ticker plus exchange is a mapping, not a permanent identity. Every private portfolio, research note, import, and file has workspace ownership.

**Portfolio:** accounts, transactions, cash movements, corporate actions, price/FX history, benchmarks, and derived valuations. Use decimal amounts and quantities with explicit currencies. Preserve imported rows and identifiers; stage and validate imports, show errors, deduplicate repeated imports, then accept corrections through an audit trail. Holdings and performance are derived from accepted events. An opening position can support current holdings without pretending to reconstruct missing historical returns.

**Research:** stocks and topics, saved sources, news items, notes, thesis versions, and citations. Allow one source to relate to several stocks/topics. Record URL, publisher, publication time, retrieval time, content hash, and permitted retained content. Separate source material, human interpretation, and generated summaries. Start with search and tags; add semantic search only when retrieval quality justifies it.

The initial research UI should have a source inbox and stock/topic pages with news, notes, theses, and open questions. Collections can be manual first and scheduled later. For project research artifacts, keep sources with their report and convert downloaded XML to YAML, following the repository rules. ([Project instructions](../../CLAUDE.md))

## Performance definitions before dashboards

Define native transaction entry first. If spreadsheet migration is requested later, audit the original headers and representative rows before choosing mappings. Preserve the source and current CLI output. Missing action/price fields must become explicit import errors or unresolved data, not invented values. Spreadsheet cleanup is not a prerequisite for building the app.

| Metric | Proposed definition / requirement |
| --- | --- |
| Portfolio value and allocation | Position quantities × timestamped prices, plus cash, translated to a chosen base currency; show stale or missing prices. |
| Time-weighted return | Measure investment performance while accounting for external cash flows, geometrically linking valuation subperiod returns. Accurate implementation needs valuations around flows. |
| Money-weighted return / XIRR | Measure the investor's experience using dated external cash flows and ending value. Report cases with no valid or unique solution. |
| Benchmark excess return | Portfolio total return minus benchmark total return over the same period and currency; label it “excess return.” |
| Risk-adjusted alpha | Later, explicitly identify the model, sampling period, benchmark, and risk-free series. Do not silently label simple benchmark outperformance as risk-adjusted alpha. |
| Win rate | Proposed default: profitable fully closed position episodes / all fully closed episodes, after fees. An episode runs from zero holdings back to zero. Breakevens stay in the denominator and are reported separately. |
| Payoff ratio | Proposed default: average positive net episode P&L / absolute average negative net episode P&L, in base currency. Label this dollar-based version; position sizing affects it. Return unavailable if either group is empty. |
| Profit factor / drawdown | Add after the ledger is verified; distinguish aggregate winning/losing P&L from the ratio of average wins/losses. |

TWR and MWR measure different effects of cash-flow timing; the GIPS methodology is the reference for return calculations, without claiming GIPS compliance. QuantConnect documents win rate and average-win/average-loss statistics; the episode and breakeven conventions above are our proposed choices, not universal definitions. ([GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/), [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary))

Start with long-only cash equities unless the source audit shows options, shorts, or margin are essential. Reconcile splits, dividends, fees, deposits, withdrawals, transfers, and FX. Explicitly distinguish raw prices plus dividend events from adjusted-return series so dividends/splits are not counted twice. Show data coverage and calculation methodology alongside metrics.

## Local identity and hosted migration

Local development seeds one real user/workspace record. Every request resolves an actor through a single identity boundary. Local mode must bind to loopback, enforce allowed hosts/origins, and reject unintended cross-origin writes; hosted configuration must refuse to start with local authentication enabled.

When hosting, replace the local identity provider with managed login, map the external subject to the existing internal user, and retain workspace membership checks on every resource. Sign-in alone does not isolate user data. Include automated cross-workspace access tests from the first protected feature.

Supabase is a candidate for managed PostgreSQL, identity, and storage, not a requirement for local development. Keep domain data access behind FastAPI. If using Supabase later, keep application tables out of exposed schemas or explicitly restrict grants and configure RLS. Direct SQL connections do not automatically inherit a browser user's JWT context; backend authorization and database role design remain necessary. ([Supabase Auth](https://supabase.com/docs/guides/auth), [RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security))

Move local files to private object storage through the storage interface. Run API and worker from the same versioned image. Provider credentials remain server-side. Before public rollout, resolve data redistribution permissions, backup restoration, rate limits, and account lifecycle behavior. These are launch tasks, not a reason to add billing or organization-management UI now.

## Minimal CI/CD

Grow CI with each implemented feature; the following is the target once those features exist:
1. Frozen backend/frontend installs; Python lint and focused pytest; TypeScript checking and frontend build.
2. PostgreSQL service for migration and persistence tests, including upgrades from the previous schema when migrations change.
3. Financial fixtures with known results, repeated-import tests, and workspace-isolation tests.
4. Verify the generated API schema/client is current once generation is introduced.
5. One browser flow covering the first useful feature, using synthetic data.

Use an always-reporting workflow gate with conditional jobs to avoid required checks becoming stuck when path filters skip a run. Include shared Minerva paths whenever an adapter depends on them. Keep secrets and personal portfolio data out of CI. GitHub Actions supports isolated PostgreSQL services for this setup. ([GitHub service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers))

For the local phase, CI and a reproducible local release are sufficient. Add image publishing and hosted CD with the deployment milestone. Once hosting is configured, deploy tested commits to staging and promote a selected version to production. Run migrations once per release, favor backward-compatible schema changes, and roll back application images without assuming destructive migrations can be reversed. Render can wait for CI checks before deployment and filter monorepo changes. ([Render deployments](https://render.com/docs/deploys), [Render monorepos](https://render.com/docs/monorepo-support))

## Implementation milestones

1. **Foundation:** local React shell + FastAPI with CI; then PostgreSQL persistence, migrations, and one local owner/account. Separate PRs keep each change reviewable.
2. **Native portfolio management:** cash entry, opening positions, buys/sells, derived holdings, and audited corrections. The app is the source of truth for records entered here.
3. **Usable local release:** manual dated valuations, explicit unknown cost basis, and verified backup/restore. Use the app before widening scope.
4. **Research workspace:** manually saved stock/topic sources and notes first. Imports and automated news collection follow demonstrated need.
5. **Performance and migration:** optional one-time import; historical prices and corporate actions; then independently scoped return and trade-statistic PRs.
6. **Hosted access:** managed login, managed database/storage, staging deployment, backups, isolation validation, and release procedure.

The first implementation should finish a usable local foundation rather than build empty scaffolding for every future feature. One account with an explicit base currency and long-only cash equities is the proposed initial scope. Benchmark, broader trading conventions, historical coverage, and market-data provider remain later decisions. No hosting subscriptions or provider pricing assumptions are required to begin.

## References

### Existing Minerva code and local evidence
- [Project configuration](../../pyproject.toml) — runtime, dependencies, packaging.
- [Project instructions](../../CLAUDE.md) — source handling and repository conventions.
- [Ignore rules](../../.gitignore) — current lockfile exclusion.
- [Portfolio CLI](../../src/harness/commands/portfolio.py) and [state implementation](../../src/harness/portfolio_state.py) — sync inputs, normalization, persistence.
- [News domain](../../src/harness/news.py) and [price plan](../../docs/plans/2026-07-01-price-tracking.md) — reusable ingestion and limits of current pricing.

### Frameworks and persistence
- [FastAPI template](https://fastapi.tiangolo.com/project-generation/) — reference full-stack combination.
- [FastAPI features](https://fastapi.tiangolo.com/features/) — validation and OpenAPI.
- [React Router SPA mode](https://reactrouter.com/how-to/spa) — static frontend and routing behavior.
- [Next.js server/client model](https://nextjs.org/docs/app/getting-started/server-and-client-components) — alternative frontend architecture.
- [Django overview](https://docs.djangoproject.com/en/stable/intro/overview/) — ORM, migrations, and admin alternative.
- [Alembic](https://alembic.sqlalchemy.org/en/latest/) — database migrations.
- [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/) — shared-lockfile workspace behavior.

### Identity and delivery
- [Supabase Auth](https://supabase.com/docs/guides/auth) — managed identity methods.
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security) — grants and row policies.
- [GitHub PostgreSQL services](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers) — database integration tests.
- [Render monorepos](https://render.com/docs/monorepo-support) and [deployments](https://render.com/docs/deploys) — later hosting and CI integration.

### Performance methodology
- [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/) — cash-flow-aware return measurement.
- [QuantConnect glossary](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/glossary) — trade-statistic definitions.
