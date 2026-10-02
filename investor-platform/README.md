# Investor Platform

A local investor workspace inside Minerva. The app will own its PostgreSQL data; any migration from existing portfolio records is a one-time operation, not an application dependency.

Accounts, cash, equity trades, investment income and FIFO cost tracking live in PostgreSQL. The tracker adds dated market valuations, SPY/QQQ comparisons and closed-position statistics. Cash and positions commit together; account records survive restarts.

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

Account and ledger failures display an error with a manual retry; there is no background health polling.

The backend reads `DATABASE_URL` from the shell; see `backend/.env.example` (not loaded automatically). Run migrations after pulling changes. A seeded local owner is resolved at a single API boundary; all account access checks workspace ownership. `INVESTOR_MODE=tailscale` enables identity-checked private access; other non-local modes refuse startup. See [Tailscale setup and usage](docs/tailscale.md). Account currency is immutable through this API, including before ledger entries exist. Supported currencies are explicitly listed in the form.

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
- [Architecture](docs/architecture.md): implemented runtime and feature boundaries.
- Verification: [IP-001 shell](docs/ip-001-verification.md), [IP-002 account](docs/ip-002-verification.md), [IP-003 cash](docs/ip-003-verification.md), and [IP-004 trades](docs/ip-004-verification.md).

No imports from the legacy harness, sheet adapters, or seeded portfolio values are included. The optional comparison fetches public daily history from Yahoo Finance. Public hosting and multi-user authentication are separate later work. The default launch command is local-only; [Tailscale mode](docs/tailscale.md) provides private access for the same owner.

## Cash ledger rules

- Entered cash amounts are decimal strings, with at most 16 integer and 8 fractional digits. Browser displays retain exact stored values; no floating-point arithmetic is used for balances.
- Opening cash is the first entry and defines the start of tracking. Later entries cannot precede it. Starting with a deposit is also supported; an opening balance cannot be added afterwards.
- Dates are posting dates in UTC, not settlement accounting. No future-dated entries. Same-day order is the original database sequence, shown in activity order. Replacements retain the original entry’s place in that sequence.
- Every write locks the account, checks its complete dated history, and commits atomically. Cash cannot become negative at any point. Concurrent withdrawals obey the same rule.
- A client-generated request key identifies a write. Retries with the same payload return the original entry; changed content with that key is rejected. Each form retains its key after an uncertain response and its draft after validation errors. Before reloading a page after an uncertain write, retry the unchanged form or inspect activity; request keys are held in the current form, not a persistent offline queue.
- Records include creation time and owner identity. Use **Correct** in Activity to preview a replacement or void, supply a reason, and confirm. Original entries are retained in Correction history with their replacements, reasons, timestamps and owner identity. Backup/restore remains separate work.

## Positions and trades

Open **Record a position or trade** below Holdings. Enter an exchange-qualified ticker and select opening position, buy, or sell. Securities must be equities denominated in the account currency; there is no symbol lookup or currency conversion. The same ticker on another exchange is a different security. Names are normalized to uppercase.

- An opening position records shares already owned without a cash trade. Its optional **total** cost basis includes any historical acquisition fees. Blank means unknown; zero is an explicit known zero. Record opening cash first if you need it, then opening positions before trades in each security.
- Buys debit quantity × price + fees. Sells credit quantity × price − fees; fees exceeding proceeds are unsupported. Quantity and price allow up to 12 integer and 8 fractional digits. Products and cash effects retain up to 16 decimal places without currency-cent rounding; figures represent entered records, not broker settlement calculations.
- Sales consume the oldest shares first (FIFO), ordered by effective date then saved sequence. Buy fees are included in lot basis and sell fees reduce proceeds. A partial lot's allocated basis rounds half-even at 16 decimal places; its final sale consumes the exact remaining basis so residuals reconcile.
- Unknown opening basis stays unknown. A sale that consumes any unknown-basis shares has no reported realized gain. Remaining holdings show unknown basis until those shares are exhausted. Sale details include FIFO realized P&L only when all consumed basis is known.
- Cash and shares must stay nonnegative throughout the full history, including after backdated writes. All cash and trade writers use the same account lock. A rejected write also rolls back any newly created security.
- Holdings and cash are derived from immutable entries. No editable balances, splits, shorts, margin, options, or foreign-currency trades. Investment income is entered through the cash form; valuation and return rules are below. Corrections revalidate the entire active history atomically; backup/restore remains IP-007.

The forms record activity only; they never place orders. The development demo uses a separate synthetic database. Portfolio migration and real-data onboarding remain separate tasks.

## Transaction reconstruction

The [transaction import CLI](docs/transaction-import.md) downloads or reads a source export, previews the reconstruction and writes a separate testing database. It preserves fractional shares, raw evidence, exclusions and inferred balances. Incomplete imports show explicitly provisional performance with inferred balances and modeled gross distributions.

## Portfolio tracker

The win/payoff scorecard loads from saved records and needs no market feed. It groups each security's flat-to-flat position into one closed trade; partial sales stay in that episode. It shows win rate, average dollar win/loss, payoff ratio, and excluded open/unknown-basis positions. FIFO P&L includes transaction fees and excludes dividends.

Open **[ Performance ]** for an automatic comparison from the first recorded date through yesterday. Choose **From / Through**, then **Compare performance** for a shorter period or fresh quotes; **Retry comparison** recovers from a data outage. The result includes portfolio value, cash, holdings weights, unrealized P&L, a daily return chart/table, and excess return against SPY and QQQ total-return proxies. The period ends before today in New York; actual baseline/end dates are shown. Editing dates clears the old report; saving ledger records reloads the full recorded period. Market requests do not alter ledger records and are not saved as audit snapshots.

This first feed supports USD equities/ETFs on NYSE, NASDAQ, NYSEARCA/ARCA, AMEX and BATS (plus XNYS/XNAS/ARCX aliases), with matching provider listing metadata. It supports at most 48 portfolio securities and ten years of ledger history. No API key or new market-data dependency is needed. Only public tickers and date ranges go to Yahoo; account names, quantities and transactions stay local. A provider outage leaves record entry and the scorecard usable.

Returns use a documented end-of-day cash-flow convention. Missing prices, positions spanning splits, unsupported listings/currencies, and undefined zero-balance periods block comparisons. Missing gross distributions withhold portfolio return; record investment income on the ex-date and reconcile against broker history. This uses book accounting, not settled broker cash or payment-date receivables. These checks do not establish complete corporate-action coverage. Quotes are single-provider and revisable. This is local exploratory tracking, not an audited return or a data-redistribution service.

See [calculation definitions and sources](docs/performance.md). Split accounting, verified backup/restore and reconciliation of real portfolio records remain separate work.

## Decision hit rate

Alongside payoff ratio and win rate, **Calculate hit rate** measures how many fully closed investment decisions beat SPY and QQQ over matching holding periods. A profitable decision can underperform the market. Partial exits count as one decision; unavailable comparisons are explicitly excluded. The report fetches market data on demand, while the original payoff scorecard remains available without it. See [definitions, matched-capital calculations and exclusions](docs/hit-rate.md).

## Ledger corrections

Choose **Correct** beside an active entry in Activity. Replace its date, type, amount, security, shares, price, fees, opening basis or note; or choose **Void entry** to exclude it from active calculations. Supply a reason, preview resulting cash and holdings, then confirm. Cancel leaves the ledger unchanged. Changing the draft requires another preview. If another write occurs after preview, confirmation is rejected until the correction is reviewed again.

Corrections append a record and optional replacement; they do not delete or rewrite original entries or import evidence. A replacement retains the original same-day position through repeated corrections, preserving cash and FIFO ordering. All balances, holdings, payoff statistics and market calculations read the active history. Corrections and ordinary writes share the account lock, and any negative cash/shares or invalid opening history rejects the whole change. Identical confirmation retries apply only once. A voided entry remains in the audit history and can be re-entered through the normal entry form if needed.

Migration `0006` adds the audit table and replaces opening-entry database indexes with validation under the account lock. It does not alter existing ledger values. Downgrading after corrections would revive superseded entries, so this migration refuses downgrade; restore a pre-correction database backup instead. Corrections do not automatically mark a reconstructed portfolio verified.
