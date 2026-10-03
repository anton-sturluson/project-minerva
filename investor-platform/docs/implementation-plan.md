# Investor Platform: one ticket, one PR

Date: 2026-10-01
Status: IP-001 through IP-004 implemented on feature branches; later tickets remain specifications. No GitHub issues have been created.

## Product direction

Build the smallest reliable local portfolio manager, then expand it. The application owns its records. Existing portfolio data can be migrated into SQL once. The application must not depend on spreadsheet structure, adapters, or ongoing sync. This follows the user's direction in this conversation on 2026-10-01.

The first useful workflow is: create an account, enter starting cash and positions, record a buy/sell, see the resulting holdings, correct a mistake, and recover the data from backup. Start with one account, one explicitly selected currency, long-only cash equities, and manual entry. A starting position need not contain a reconstructed trade history. Unknown cost basis remains unknown.

Keep the previously proposed React/TypeScript, FastAPI/Python, and PostgreSQL stack. Add its pieces only when a ticket needs them. The architecture document supplies the rationale; this plan supplies the narrower implementation sequence. ([Architecture proposal](architecture.md))

## Delivery rules

- Each ticket has one branch and one PR with the ticket ID, outcome, acceptance evidence, and relevant limitations. Proposed IDs below are not GitHub issue numbers.
- Implement in order. For the authorized IP-002 through IP-004 batch, stack each PR on its predecessor while the foundation remains open; merge in dependency order after review. Use `worktrees/investor-platform-<ticket>/` if a worktree is needed, following repository instructions. ([Project instructions](../../CLAUDE.md))
- The first PR can carry these planning documents. Do not spend a separate PR solely on creating empty folders.
- Each feature PR includes the UI/API/data changes necessary for its outcome and the tests protecting its behavior. Correctness and validation are part of the feature, not a final hardening phase.
- CI starts in the first PR, then grows alongside persistence and financial behavior. Only synthetic fixtures enter the repository and CI.
- Keep unrelated Minerva edits out of these PRs. Reuse existing code only where the current ticket needs it; no broad extraction or refactor up front.
- Open PRs for review when implemented. This plan does not authorize automatic merging or production deployment.

## First milestone: dependable native portfolio management

### IP-001 — Boot the local app and establish CI

**Outcome:** a fresh checkout can start a browser page that successfully calls the Python API.

**Scope:** minimal `web/` and `backend/` projects, pinned runtimes and committed lockfiles, an API health route, simple connected/disconnected UI, environment example, and documented local startup. Preserve uv/hatchling and Python 3.12 for the backend. Add a GitHub Actions workflow for backend checks and frontend type checking/build. Bind local services to loopback and restrict allowed hosts/origins from the outset.

**Acceptance:** documented commands work from a clean checkout; the page reports a stopped API accurately; CI passes with no personal credentials; lockfiles are tracked despite root ignore rules. A small integration smoke check covers the browser-to-API path. No placeholder feature packages, cloud services, or generated SDK tooling yet.

**Depends on:** none. **PR title:** `IP-001: Bootstrap local investor app and CI`.

### IP-002 — Persist one account with local ownership

**Outcome:** create and view an investment account that survives restarts.

**Scope:** local PostgreSQL in Compose, SQLAlchemy/Alembic, initial migration, seeded local owner/workspace, one account with a required base currency, and create/read UI/API. Resolve the actor at one boundary; account queries enforce ownership. Local identity is only valid in local mode. Do not implement login, invitations, roles UI, or a generalized permissions engine.

**Acceptance:** migrations create a fresh database; restart preserves the account; invalid currency and cross-workspace reads/writes fail; server mode refuses local identity. CI uses PostgreSQL for persistence tests. Repeated initialization does not duplicate the owner or account. Currency cannot change once ledger entries exist.

**Depends on:** IP-001. **PR title:** `IP-002: Persist a locally owned investment account`.

### IP-003 — Record cash with reliable writes

**Outcome:** enter opening cash, deposits, and withdrawals, and see a dated activity list and derived cash balance.

**Scope:** typed ledger records with decimal amounts, effective date plus deterministic ordering, account currency, creation time, and audit identity. Opening cash is a starting balance at the tracking date, not an invented past deposit. API validation, database constraints, atomic writes, and an idempotency key protect each mutation. Only supported events are accepted.

**Acceptance:** deposit/withdrawal fixtures produce exact expected balances; invalid amounts and future-dated posted entries are rejected; retrying the same request does not duplicate it; reusing its key with different content fails; concurrent writes cannot violate the cash-only balance rule. Validate the full affected chronology when backdating. UI validation errors preserve the draft for correction.

**Depends on:** IP-002. **PR title:** `IP-003: Add an auditable cash ledger`.

### IP-004 — Manage positions and trades inside the app

**Outcome:** enter opening positions, buy and sell shares, and see holdings and cash update together.

**Scope:** minimal security identity with ticker/exchange/currency, opening-position entry, buy/sell forms with decimal quantity, price and fees, activity detail, and derived holdings. Opening positions affect holdings without a fictional cash trade; their optional cost basis is explicitly identified. Use one documented FIFO convention for lots. Support securities in the account currency only. No market-data lookup is required.

**Acceptance:** a hand-calculated opening/buy/partial-sell/full-close fixture reconciles shares, cash, fees, and known cost basis. A trade and its cash effect commit atomically. Duplicate retries, concurrent oversells, negative cash, currency mismatches, and invalid backdated trades are rejected. Holdings are derived, not independently editable. Unknown opening basis cannot become a fabricated realized gain. Unsupported events are rejected rather than approximated.

**Depends on:** IP-003. **PR title:** `IP-004: Add native positions, trades, and holdings`.

### IP-005 — Correct mistakes without losing the audit trail

**Outcome:** correct or void an erroneous entry in the UI and see a consistent rebuilt account.

**Scope:** one atomic correction operation with an immutable link to the previous entry, a reason, and a visible history. The active ledger view excludes superseded/voided records; derived holdings and balances are rebuilt deterministically. Opening cash/positions use the same correction mechanism. Do not add a generic event-sourcing framework.

**Acceptance:** correcting a buy changes dependent balances correctly; voiding it cannot silently leave a later sale without shares; invalid corrections leave the previous state intact. Concurrent edits detect conflicts. A user can trace original and replacement values. Replaying accepted ledger entries produces identical results after a restart.

**Depends on:** IP-004. **PR title:** `IP-005: Add atomic ledger corrections and audit history`.

**Checkpoint:** use this ledger with a small synthetic portfolio, then a few real entries. Fix observed workflow defects before adding dashboards. The accounting checks in IP-003/IP-004 must already pass before this checkpoint.

### IP-006 — Add a small portfolio overview with manual valuations

**Outcome:** view cash, positions, per-position value and allocation, and known gains/losses using manually entered dated prices.

**Scope:** a compact table and summary, price entry/correction with provenance, and FIFO realized/unrealized P&L where basis is known. Display fee treatment and valuation dates. Store raw price observations separately from ledger transactions. Show a clearly labeled partial valuation when prices are missing; never silently use zero. Mixed-date prices must remain visible.

**Acceptance:** totals and gains reconcile to fixed fixtures; correcting prices does not alter transactions; stale/missing prices and unknown basis have explicit states. An opening position enables tracking from its recorded starting point, not a fabricated historical return. No alpha, annualized return, charts requiring a historical series, or automated price feed in this PR.

**Depends on:** IP-005. **PR title:** `IP-006: Add dated valuations and a portfolio overview`.

### IP-007 — Make the local data recoverable

**Outcome:** back up the account and prove it can be restored.

**Scope:** a documented backup command and restore procedure targeting a fresh database, with version metadata and safe failure behavior. No file-upload or document-storage system exists yet, so recovery covers the database. Extend backup coverage in the feature that later introduces file bytes.

**Acceptance:** restore a fixture containing corrections and prices into a fresh database and reproduce its ledger, positions, cash, valuations, and audit links. Fail clearly on unsupported backup versions or a nonempty restore target. Exercise recovery without overwriting the current database. Include a focused end-to-end create/trade/correct/reload check if not already covered.

**Depends on:** IP-006. **PR title:** `IP-007: Add verified local backup and restore`.

**Release gate:** normal entry, retry, correction, restart, and restore work; numerical fixtures and ownership tests pass. This is the first small release worth using as the portfolio record keeper. It is not ready for public hosting, margin, options, multi-currency accounts, or unmodeled corporate actions. Identify those limits in the UI where they affect a real operation.

## Second milestone: one small research feature

### IP-008 — Save research against a stock or topic

**Outcome:** create a stock/topic page, save a source link, write a note, and find it again.

**Scope:** native CRUD for topics, source URLs/titles, notes, and many-to-many links to securities/topics. Include ownership and created/updated timestamps. Allow notes to cite saved links. Add basic title/text search. No scraping, attachments, background workers, model calls, or vector database.

**Acceptance:** a source can be reused across topics without duplicating it in the same workspace; note revisions are recoverable; deleting a topic does not silently delete shared source records. Cross-workspace access is blocked and backup/restore includes these records. A simple browser flow saves and retrieves a cited note.

**Depends on:** IP-007 for delivery order; shares the persistence and ownership foundation. **PR title:** `IP-008: Add stock and topic research notes`.

## Backlog to scope after using the first release

These are separate future tickets, not work bundled into the initial PRs:

- One-time portfolio migration into SQL when needed, implemented as a standalone migration task with reconciliation. Keep source-specific logic outside the application; no sheet connector or recurring sync.
- Necessary accounting events, beginning with dividends and splits, each with recalculation fixtures. These must precede any claim of complete historical performance.
- Automated current prices; separately, historical prices/FX and corporate-action reconciliation.
- Time-weighted returns and benchmark excess return once cash flows and valuations have verified coverage; then separately XIRR, closed-position statistics, and model-defined alpha. Missing history limits the displayed period. ([Performance methodology](architecture.md#performance-definitions-before-dashboards))
- News import/collection after the manual research workflow is useful; durable jobs only when collection requires them.
- Hosted login, deployment, multi-user release, and other asset classes as later milestones.

For the local phase, CI and a reproducible local release are sufficient. Add image publishing and hosted CD with the deployment ticket; do not build an unused release pipeline now. When APIs grow beyond the first few endpoints, add generated client tooling if it reduces maintenance.

## References

### Project decisions and constraints
- User instructions in this conversation, 2026-10-01 — app-owned portfolio management, small hardened increments, one PR per ticket.
- [Architecture proposal](architecture.md) — previously researched stack, alternatives, and long-term boundaries.
- [Project instructions](../../CLAUDE.md) — Python tooling and worktree location.

### Existing implementation and methodology
- [Portfolio CLI](../../src/harness/commands/portfolio.py) — optional legacy migration integration point.
- [Performance methodology](architecture.md#performance-definitions-before-dashboards) — measurement prerequisites and primary-source citations.
