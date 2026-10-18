# Investor Platform documentation

| Document | Description |
| --- | --- |
| [Review handoff — 2026-10-04](review-handoff-2026-10-04.md) | Open PR inventory, dependency order, review priorities and deployment handoff through #162. |
| [Data assumptions](data-assumptions.md) | Living register of data limits, reconstruction assumptions and reconciliation needs. |
| [ADR 0001](decisions/0001-documentation-and-pages.md) | Documentation policy and separate Portfolio, Activity and Research views. |
| [ADR 0002](decisions/0002-stock-exclusion-scenarios.md) | Stock exclusions, retained cash and scenario limitations. |
| [ADR 0003](decisions/0003-independent-holdings.md) | Independent current holdings valuation and same-date USD FX. |
| [ADR 0004](decisions/0004-international-market-data.md) | International listing identity, dated USD conversion and exchange holidays. |
| [ADR 0005](decisions/0005-recorded-period-baselines.md) | Recent comparisons from recorded balances when old market history is unavailable. |
| [ADR 0006](decisions/0006-dividend-accrual.md) | Dividend attribution, receivables and payment-date cash. |
| [ADR 0007](decisions/0007-stock-performance-scope.md) | Stock-only performance scope, estimated distributions and separate account reconciliation. |
| [ADR 0008](decisions/0008-store-annual-financial-observations.md) | Proposed annual financial store with immutable source evidence. |
| [ADR 0011](decisions/0011-group-code-by-feature-and-share-calculation-rules.md) | Feature ownership, shared calculations and exact reviewed-release admission. |
| [ADR 0012](decisions/0012-store-economic-observations-under-research.md) | Minimal economic observations, source collection state and an Economics subsection under Research. |
| [Annual financial contract](annual-financial-contract.md) | Financial statement inputs, calculation definitions and pilot bundle schema. |
| [Annual financial tickets](annual-financial-tickets.md) | Approved three-step pilot: contract, parallel collection and weighted report. |
| [Weighted financial report](weighted-financial-report.md) | Annual metric weights, separate coverage and reproducible cited reports. |
| [Daily prices](daily-prices.md) | Daily 5 p.m. Eastern collection, retries, cache freshness and operational status. |
| [Operations](operations.md) | Configuration, start/stop, migrations, testing and project layout. |
| [Portfolio guide](portfolio.md) | Accounts, cash, positions, trade entry, corrections and tracker usage. |
| [Research](research.md) | Manager directory, SEC history imports and quarterly position changes. |
| [Cash reconciliation](cash-reconciliation.md) | Reviewed dated cash replacement, checkpoint validation and immutable audit. |
| [Transaction import](transaction-import.md) | Preview and import a testing portfolio; source evidence, exclusions and inferred balances. |
| [Post-mortem](post-mortem.md) | Annual and full-history stock contributions, linking formula and interpretation. |
| [Performance](performance.md) | Portfolio returns, SPY/QQQ benchmarks, valuation conventions and data limits. |
| [Decision hit rate](hit-rate.md) | Matched-capital comparisons, decision grouping and exclusions. |
| [Private Tailscale access](tailscale.md) | Private setup, identity boundary, restart and connection troubleshooting. |
| [Privacy](privacy.md) | Sensitive-data exclusions, local scans and historical exposure handling. |
| [Architecture](architecture.md) | Runtime, module boundaries, ownership and shared domain types. |
| [Implementation plan](implementation-plan.md) | Implemented capabilities and remaining work. |
| [Design guide](../design/README.md) | Homepage Club styling, theme behavior and interface conventions. |

## Verification records

These describe earlier increments; [Operations](operations.md#verification) contains the current checks.

| Record | Description |
| --- | --- |
| [IP-001](ip-001-verification.md) | App shell and navigation. |
| [IP-002](ip-002-verification.md) | Account persistence. |
| [IP-003](ip-003-verification.md) | Cash ledger, validation and recovery. |
| [IP-004](ip-004-verification.md) | Trades, FIFO accounting and holdings. |
| [Tracker](tracker-verification.md) | Scorecard and benchmark comparison verification. |

[Project overview and quick start](../README.md)
