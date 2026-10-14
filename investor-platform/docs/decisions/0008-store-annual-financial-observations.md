# ADR 0008: Store annual financial observations with immutable evidence

## Status

Proposed · 2026-10-14

## Context

The annual financial profile needs comparable company statement facts, traceable sources and reproducible revisions. The initial issuers are GOOGL, OSCR and ACFN for fiscal years 2023–2025. The platform already keeps securities and ledger records in PostgreSQL. A separate report-shaped statement model would duplicate company facts; overwriting values would erase the evidence needed to reproduce earlier reports.

The prior migration effort has been retired. This decision establishes a clean annual contract without reviving that implementation. Owner earnings, TTM and collection infrastructure are outside the initial scope.

## Decision

Use one bounded company/period/metric/source model in the existing PostgreSQL service. Accept immutable annual observation bundles with per-fact evidence and explicit missing/applicability states. Preserve subsequent restatements as new versions. Map existing securities to confirmed issuers instead of joining on ticker. Derive ratios in application code from exact accepted inputs, with explicit accounting, capex and share-denominator definitions.

Keep the candidate interchange and financial definitions in the [annual financial contract](../annual-financial-contract.md). This ADR proposes the architecture; it does not authorize a deployment or implement a migration.

## Consequences

Both agent-assisted and later deterministic collection can use the same input contract. A report can retain the exact evidence behind its numbers. Existing ledger and listing identities remain authoritative for holdings.

Immutable versions require more storage and a clear publication-selection rule. A bounded catalog needs deliberate extension when new measures become necessary. JSON Schema validates structure but cannot verify a filing, share rights or accounting interpretation; acceptance needs separate evidence checks. Insurer applicability can reduce metric coverage even when statement facts are available.

## Related ADRs

```text
[ADR-0008: Store annual financial observations with immutable evidence]
      |
      +-- Relates to --> [ADR-0003: Price current holdings independently of historical performance]
                         - Existing securities and valuation remain the holdings boundary.
```

## References

- [Annual financial contract](../annual-financial-contract.md) — scope, input semantics, evidence and acceptance boundaries.
- [ADR 0003](0003-independent-holdings.md) — independent holdings valuation.
- [Backend models](../../backend/src/investor_platform/models.py) — existing PostgreSQL ledger and securities.
