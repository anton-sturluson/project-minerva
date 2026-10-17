# 0011. Group code by feature and share calculation rules

## Status

Proposed

## Context

Route modules also owned calculations, input types and serialization used by other features. Funding imports formed a circular dependency, while two financial-report paths independently implemented common arithmetic and validation. Broad names such as Tracker and CashLedger obscured the interface's actual ownership. This made defects harder to locate and encouraged changes in several places for one rule.

## Decision

Group backend and frontend code by the feature it owns. Keep shared accounting, position analysis, request identities, financial arithmetic and API transport in focused modules with explicit names. HTTP routes and UI composition consume these functions and contracts. Preserve the annual-bundle and reviewed-release admission policies, and each benchmark's funding convention. Bind new reviewed-release admission to a successful review of the exact admitted records and source packets; keep existing immutable releases readable.

## Consequences

A reader can find related code together, and common rules have one implementation. Incremental and full ledger replay use the same entry application. The two financial contracts remain explicit because their period, currency and comparison policies differ. Moving modules changes internal import paths and requires matching test/documentation updates, even though HTTP, JSON, database and CLI interfaces remain stable. New release imports with legacy receipts require independent re-review; existing stored records are unchanged.

## Related ADRs

```text
[ADR-0011: Group code by feature and share calculation rules]
      |
      +-- Relates to --> [ADR-0008: Store annual financial observations] - Preserve the annual observation contract.
      +-- Relates to --> [ADR-0009: Bind reviewed financial history to account snapshots] - Strengthen new release admission without changing saved records.
      +-- Relates to --> [ADR-0010: Fund purchases and link whole-account returns] - Preserve distinct funding and benchmark conventions.
```
