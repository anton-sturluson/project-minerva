# ADR 0005: Recent comparisons from recorded balances

Status: accepted.

## Problem

An old, fully closed security can lose provider coverage after delisting. Fetching every historical listing then blocks even a recent comparison whose holdings all have prices. A return must not silently omit a held position or invent its missing prices.

## Decision

Offer two explicit baselines. `history` retains the original inception replay and historical reconciliation. `recorded` starts with cash and share quantities from the saved ledger at the selected period boundary and fetches only securities carried into, or traded during, that period. The entire ledger still participates in accounting: past sales remain in cash and FIFO lots retain their original ordering and basis.

All accounts default to full history, including reconstructed accounts. The last-90-days recorded-balance estimate is an explicit optional view. Buttons expose both choices; dates remain editable. No prices are substituted and no requested dates are silently changed after a failure. Full history can still be unavailable until missing prices or corporate actions are supplied. The duplicated generic error suffix is removed.

Only income within the chosen period is reconciled or modeled. Earlier missing distributions are not reconstructed; opening cash/share quantities are trusted as recorded, including their limitations. Splits within the selected period and missing prices/FX still block affected comparisons. This does not certify the opening balance or past split accounting.

Exclusions in recorded mode apply within the selected period. Prior trades remain unchanged; excluded opening shares are notionally sold at the first comparison close and retained as cash, while subsequent excluded trades disappear. Existing distributions or funding limits can still prevent a scenario. Full-history exclusions keep their original lifetime semantics. Neither mode writes records or changes holdings or the all-history scorecard.

## References

- [Performance implementation](../../backend/src/investor_platform/performance.py) — security selection, full ledger replay and period scenarios.
- [Performance conventions](../performance.md) — cash flows, income, unknown prices and CAGR.
- [ADR 0002](0002-stock-exclusion-scenarios.md) — full-history exclusion semantics.

A manually selected start after inception also uses recorded balances at that date, with the same visible disclosure. Returning to Full history restores inception validation. Posting dates and report boundaries use New York calendar dates, including before UTC midnight and across daylight-saving changes.
