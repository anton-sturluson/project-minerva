# Investor Platform review handoff — 2026-10-04

## Snapshot

There are **29 open functional PRs** in one dependent stack, starting with #121 against `main` and ending with #162. Every functional PR has passing `verify` and repository privacy `scan` checks at this snapshot. The linked PRs in the inventory below are the sources of truth for current state; green CI is evidence of automated verification, not review approval.

The functional tip is `codex/investor-daily-prices`, commit `2ad755e495c5b9ed1389379d09fc8547394e7fdc`. The private preview was updated through that tip, including migration `0013` and enabled daily collection. Deployment does not mean these changes have merged into `main`. This handoff's documentation PR is additional to the 29 functional PRs. ([Stack tip #162](https://github.com/anton-sturluson/project-minerva/pull/162))

## How to review the stack

1. Read the final behavior notes below, then review each PR against its stated parent in inventory order. A child PR depends on the preceding row; do not treat it as an independent change against `main`.
2. Give the accounting and market-data changes the closest scrutiny. Check numerical examples and invariants, not just screenshots. Keep failure/ownership tests that protect money calculations and privacy; remove redundant tests only when equivalent coverage remains.
3. Validate the assembled tip using a **separate synthetic database/portfolio**. Exercise account switching, holdings, both return scopes, exclusions, annual comparisons, Post-mortem measures, hypothetical statistics, provider failure/recovery and narrow-screen layout. Use the existing [verification procedure](operations.md#verification).
4. Record findings against the PR that owns the behavior. If a finding spans the stack, identify both the introducing PR and the final affected behavior. This document does not authorize merging.

Review the final interface as well as incremental diffs: the allocation chart introduced in #122 is intentionally removed by #155; the recent-period controls evolve into YTD/one-year in #156. Do not restore superseded UI merely to make an older PR's screenshot match the tip. ([#122](https://github.com/anton-sturluson/project-minerva/pull/122), [#155](https://github.com/anton-sturluson/project-minerva/pull/155), [#156](https://github.com/anton-sturluson/project-minerva/pull/156))

## Review priorities and final behavior

| Area | What the reviewer should verify | Main references |
| --- | --- | --- |
| Measurement boundary | Default is estimated **stocks-only** time-weighted return. Whole-account returns retain cash/income/funding checks. These are different measurements; neither the benchmark difference nor stock-only return should be described as risk-adjusted alpha or a certified fund track record. | [Performance methodology](performance.md); #148, #150–154 |
| Transactions and income | Independent accounts; no phantom opening shares; recorded fees and net proceeds; dated deposits; dividend ex-date accrual without counting payment twice; corrections preserve audit history. | [Cash reconciliation](cash-reconciliation.md), [Transaction import](transaction-import.md); #132, #141–146, #150–152 |
| Historical and foreign prices | Delisted holdings still need prices while held. Current holdings should work independently of closed-position history. Validate listing identity, actual share units, dated FX and missing-price safeguards; never substitute zero for an unavailable price. | [Performance methodology](performance.md), [Operations](operations.md#historical-data-fallback); #135, #137, #139, #143–144, #153 |
| Attribution and trade statistics | Full-history Post-mortem ranks **dollar gains/losses** by default; individual years default to linked percentage-point contributions. Rankings, signs and totals must follow the selected measure. Win rate, benchmark hit rate, payoff ratio and hypothetical closes remain distinct. | [Post-mortem](post-mortem.md), [Decision hit rate](hit-rate.md), [Portfolio guide](portfolio.md); #138, #159–160 |
| Cache correctness | Persist validated provider prices, not stale ledger-derived balances. Confirm workspace and validation-option isolation, decimal precision, range slicing, concurrent requests, expiry, failed replacement and immediate reflection of ledger edits. Private API responses stay `no-store`. | [Operations](operations.md#historical-data-fallback); #161 |
| Daily collection | 17:00 **America/New_York**, DST-aware; durable run status, duplicate prevention, startup catch-up, bounded retries, per-account failure isolation and delayed same-date FX handling. Today's chart data is permitted only after the cutoff. | [Daily prices](daily-prices.md); #162 |

These are review priorities, not claims that an independent review has already found defects.

## Validation and deployment handoff

At the functional tip, the completed checks were **200 backend tests**, Python lint/format, frontend formatting/build, and **66 desktop/mobile browser workflows**. CI and privacy scans passed. A separate live-provider synthetic portfolio was also exercised through holdings, performance and Post-mortem on desktop and mobile. The deployed collector completed a refresh without reported account failures. These are completed verification results from the implementation session and [#162's CI](https://github.com/anton-sturluson/project-minerva/pull/162/checks).

Direct control of the user's current browser tab was unavailable while the host was locked; do not describe the synthetic browser verification as a fresh visual inspection of that tab. Provider publication at exactly 5 p.m. has not been guaranteed: the scheduler's DST, retries and restart behavior were tested with controlled inputs, and actual collection was exercised separately. ([Daily prices](daily-prices.md))

Operational boundaries to retain:

- The deployment remains private and single-owner; multiple portfolios are separate accounts within that workspace, not public multi-user authentication. ([Private access](tailscale.md))
- Apply migrations through `0013` to the deliberately selected database. Keep credentials, database exports, provider keys and deployment-specific addresses in ignored private configuration/storage. Never copy them into this handoff or a PR. ([Operations](operations.md), [Privacy](privacy.md))
- `INVESTOR_DAILY_PRICES=1` enables the worker only in Tailscale mode. Keep the host awake, API, PostgreSQL and network running. OS reboot auto-start is **not configured by this change**. ([Daily prices](daily-prices.md))
- Inspect collection with `uv run --frozen investor-refresh-prices --status` from the backend directory, using the deployment's selected `DATABASE_URL`. `--force` requests a real provider refresh. An already-open page does not poll; reload after collection. ([Daily prices](daily-prices.md#status-and-manual-retry))

## Merge considerations for the eventual integrator

When merge approval is given, integrate bottom-up and recheck each child's base and diff. Preserve parent ancestry with merge commits where repository policy permits. If using squash/rebase merges, restack children onto the updated parent/main before proceeding so already-integrated changes do not reappear in later diffs. Keep needed parent branches until their children have been retargeted/restacked. Rerun relevant checks after conflict resolution or material base changes; do not equate a green pre-merge check with validation of a changed result.

After integration, confirm the assembled application still matches the reviewed tip, apply migrations to the chosen deployment database, rebuild the web assets, and verify the price worker's status. Use the [operations guide](operations.md) rather than copying private runtime configuration from a running process.

## References

### Open functional PRs, in dependency order

Each link supplies the incremental diff, discussion and current checks. All rows were open with passing `verify` and `scan` checks on 2026-10-04.

| PR | Parent | Scope / review focus |
| --- | --- | --- |
| [#121](https://github.com/anton-sturluson/project-minerva/pull/121) | `main` | Separate Portfolio, Activity and Research pages; move explanatory copy into documentation. |
| [#122](https://github.com/anton-sturluson/project-minerva/pull/122) | #121 | Lead with scorecard and a single holdings overview; allocation chart is superseded later. |
| [#125](https://github.com/anton-sturluson/project-minerva/pull/125) | #122 | Stock-exclusion scenarios and CAGR; preserve actual records and clarify hypothetical cash treatment. |
| [#126](https://github.com/anton-sturluson/project-minerva/pull/126) | #125 | Compare market-value and cost-basis allocations; UI polish. |
| [#132](https://github.com/anton-sturluson/project-minerva/pull/132) | #126 | Import reported USD totals without confusing settlement amounts with native quote currency. |
| [#135](https://github.com/anton-sturluson/project-minerva/pull/135) | #132 | Independent current holdings valuation; closed-history failures must not blank open holdings. |
| [#137](https://github.com/anton-sturluson/project-minerva/pull/137) | #135 | International USD valuation and explicit listing metadata. |
| [#138](https://github.com/anton-sturluson/project-minerva/pull/138) | #137 | Hypothetical close-all scorecard; no saved trade mutation. |
| [#139](https://github.com/anton-sturluson/project-minerva/pull/139) | #138 | Recent comparisons using recorded starting balances and explicit limitations. |
| [#141](https://github.com/anton-sturluson/project-minerva/pull/141) | #139 | Select and isolate multiple portfolios within the workspace. |
| [#142](https://github.com/anton-sturluson/project-minerva/pull/142) | #141 | Import separate transaction groups into separate accounts. |
| [#143](https://github.com/anton-sturluson/project-minerva/pull/143) | #142 | Date boundaries and useful historical-comparison diagnostics. |
| [#144](https://github.com/anton-sturluson/project-minerva/pull/144) | #143 | Tiingo historical fallback, listing review and provider caching. |
| [#145](https://github.com/anton-sturluson/project-minerva/pull/145) | #144 | Dated share receipts without phantom initial positions. |
| [#146](https://github.com/anton-sturluson/project-minerva/pull/146) | #145 | Cash fees and taxes as investment expenses. |
| [#148](https://github.com/anton-sturluson/project-minerva/pull/148) | #146 | Withhold whole-account returns while inferred funding is unreconciled. |
| [#150](https://github.com/anton-sturluson/project-minerva/pull/150) | #148 | Separate dividend accrual dates from cash payment dates. |
| [#151](https://github.com/anton-sturluson/project-minerva/pull/151) | #150 | Reconcile dated cash histories and deposit-day capital. |
| [#152](https://github.com/anton-sturluson/project-minerva/pull/152) | #151 | Link stock-specific income to its security. |
| [#153](https://github.com/anton-sturluson/project-minerva/pull/153) | #152 | Warsaw listings and dated PLN conversion. |
| [#154](https://github.com/anton-sturluson/project-minerva/pull/154) | #153 | Default stock-only performance independently of brokerage cash. |
| [#155](https://github.com/anton-sturluson/project-minerva/pull/155) | #154 | Compact holdings/totals, remove allocation chart, keep navigation visible. |
| [#156](https://github.com/anton-sturluson/project-minerva/pull/156) | #155 | Searchable exclusions and Full history / YTD / one-year controls. |
| [#157](https://github.com/anton-sturluson/project-minerva/pull/157) | #156 | Annual returns, benchmark comparisons and signed percentage-point differences. |
| [#158](https://github.com/anton-sturluson/project-minerva/pull/158) | #157 | More chart dates, one-decimal holdings and combined P&L/percentage display. |
| [#159](https://github.com/anton-sturluson/project-minerva/pull/159) | #158 | Annual/full-history stock attribution, linked contributions and reconciliation. |
| [#160](https://github.com/anton-sturluson/project-minerva/pull/160) | #159 | Dollar-first full-history Post-mortem with explicit alternate time-weighted measure. |
| [#161](https://github.com/anton-sturluson/project-minerva/pull/161) | #160 | Shared private market-history cache and immutable hashed frontend assets. |
| [#162](https://github.com/anton-sturluson/project-minerva/pull/162) | #161 | Daily 5 p.m. Eastern collection, status/migration, retries and same-day cutoff. |

### Code and operating references

- [Documentation index](README.md) — entry point for the methodology, import, privacy and operational guides cited above.
- [Performance methodology](performance.md) — stock/whole-account scope, cash-flow timing and limitations.
- [Post-mortem methodology](post-mortem.md) — dollar gain versus linked percentage-point contribution.
- [Decision hit rate](hit-rate.md) and [Portfolio guide](portfolio.md) — metric definitions and user workflows.
- [Cash reconciliation](cash-reconciliation.md) and [Transaction import](transaction-import.md) — data changes and audit boundaries.
- [Operations](operations.md), [Daily prices](daily-prices.md), [Private access](tailscale.md) and [Privacy](privacy.md) — deployment, collection, verification and sensitive-data boundaries.
- [Investor CI workflow](../../.github/workflows/investor-platform-ci.yml) — automated checks.
- [Functional tip CI](https://github.com/anton-sturluson/project-minerva/pull/162/checks) — check results for the reviewed snapshot.

### Separate open work

[#101 — HF weekly-ideas CLI](https://github.com/anton-sturluson/project-minerva/pull/101) is also open against `main`, but is unrelated to this stack. No status checks were listed at this snapshot. Review it separately; do not include it in the investor-platform merge sequence.
