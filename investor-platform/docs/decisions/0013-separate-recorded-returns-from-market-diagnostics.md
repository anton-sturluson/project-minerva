# ADR 0013: Separate recorded returns from market diagnostics

## Status

Accepted

## Context

[ADR 0006](0006-dividend-accrual.md) correctly separates dividend accrual from payment, but also lets a provider amount disagreement veto the account return. [ADR 0010](0010-fund-purchases-and-link-account-returns.md) retains that veto even for an explicitly provisional reconstruction. The calculation already uses recorded cash and receivables; the provider comparison does not determine those amounts.

Generic dividend feeds can contain rounded rates, preliminary currency conversions or incomplete events. A difference therefore does not establish that recorded broker cash is wrong. Per-event overrides would repair known comparisons while adding a second source collection to maintain. A wider tolerance would assume a precision contract the feeds do not provide. Neither removes the authority error.

## Decision

Measure whole-account performance from the recorded transactions and stated reconstruction assumptions. Keep generic dividend comparisons as visible source diagnostics, separate from the conditions needed to calculate that measurement. A provider amount disagreement or missing provider corroboration does not withhold a result when the recorded event, accrual date and prior holdings are coherent. Do not replace actual cash with an estimate or certify the records as complete.

Withhold results when the chosen method lacks a required input or coherent recorded event: unresolved required funding, unknown income classification, absent prior holdings, or missing income under the strict completeness policy. Explicit zero-income assumptions remain explicit; a zero-cent estimated settlement does not require a zero cash entry. Required valuation, FX, corporate-action, session and return-factor checks remain. Analytical stock returns, modeled funding comparisons and trade-only hit rates keep their distinct measurement boundaries.

## Consequences

Rounded or revised provider events no longer repeatedly erase a recorded-history return or require manual rate exceptions. The interface distinguishes unavailable calculations from calculated results accompanied by source discrepancies and provisional assumptions.

A numeric return is not certification of complete brokerage income or transactions. A material discrepancy can remain unresolved while the recorded-history return is available; the user must still review it against source records. This is a deliberate limitation of the measurement, not a reconciliation conclusion. Missing required-input and structural checks continue to protect calculations whose inputs cannot support the selected method.

## Related ADRs

- **Supersedes** [ADR 0006](0006-dividend-accrual.md) — only the provider-discrepancy veto; dividend accrual, payment and attribution rules remain accepted.
- **Supersedes** [ADR 0010](0010-fund-purchases-and-link-account-returns.md) — only the inherited provider-discrepancy veto; inferred funding and daily return conventions remain accepted.
- **Relates to** [ADR 0007](0007-stock-performance-scope.md) — preserves the analytical stock sleeve as a different measurement from recorded account cash.

## References

- [Income reconciliation](../../backend/src/investor_platform/performance/income.py) — recorded receivables and separate calculation blockers/source diagnostics.
- [Return calculation](../../backend/src/investor_platform/performance/returns.py) — source of account values and method-specific readiness.
- [Performance methodology](../performance.md) — current measurement, assumptions and visible limitations.
