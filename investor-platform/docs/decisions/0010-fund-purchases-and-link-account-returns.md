# ADR 0010: Fund purchases and link whole-account returns

Status: accepted

## Context

An inferred opening cash balance places future contributions at inception. A separate cash estimator then gives the same account two cash histories. Index selection must not select a different portfolio calculation. The owner has chosen to assume that cash arrives only when a purchase needs it. This changes the default measurement in [ADR 0007](0007-stock-performance-scope.md) for these reconstructed accounts; stock-only analysis remains useful for attribution and legacy accounts.

## Decision

Start reconstructed cash at zero. Use existing cash first, including retained sale proceeds and recorded income already paid. Infer a deposit only for each purchase shortfall, in preserved source order. Store and label these dated assumptions in the ledger. Recompute them when relevant records change. Replace reviewed placeholders through append-only corrections; retain original evidence and all trades.

Use the ordinary whole-account daily time-weighted return for both index choices. Include cash and recorded dividend receivables. Treat deposits as beginning-of-session flows and withdrawals as end-of-session flows; geometrically link daily factors. Date-only records require a stated timing convention, not a claim of exact intraday measurement. This follows [Portfolio Performance's daily method](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/).

Offer ordinary index buy and hold, or index purchases using the same dated contributions with no sales. These change only the benchmark. Do not invent dividend payment dates or waive missing-income checks to display a return. Inferred funding remains unverified.

## Consequences

One ledger determines account cash and performance. Sale proceeds are reused without counting them as new contributions. There is no active opening cash placeholder for these accounts. The historical funding dates remain assumptions, and source order matters for same-day purchases and sales. Missing income can withhold total return until evidence is entered. Index purchases at the close can produce a different time-weighted return from continuous index exposure because new cash is idle during that session.

## Related ADRs

- Supersedes [ADR 0007](0007-stock-performance-scope.md) for purchase-funded account defaults; preserves its analytical stock-only scope.
- Depends on [ADR 0006](0006-dividend-accrual.md) for dividend accrual and payment treatment.

## References

- [Portfolio Performance daily methodology](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/) — beginning-of-day deposits, end-of-day withdrawals and geometric linking.
