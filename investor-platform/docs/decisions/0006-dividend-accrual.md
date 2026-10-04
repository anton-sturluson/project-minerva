# ADR 0006: Dividend accrual and cash payment

Status: accepted.

## Decision

Keep dividend recognition separate from cash payment. Income records may identify a dividend security and ex-date; their effective date remains the cash payment date. Recognize the recorded gross amount as a receivable from ex-date until payment. Payment exchanges that receivable for cash without creating another investment gain. Distinguish dividends from interest and other income with a string enum. Interest and other investment income may also identify their security, without an ex-dividend date; this supports stock-lending payments without treating them as dividends. The API, correction workflow and database all validate attribution and dates; security ownership is checked within the authenticated workspace.

Compare each security/ex-date amount against market distribution evidence. Withhold returns for missing, mismatched or unclassified income rather than filling missing cash with an estimate. Provider events alone do not establish a cash payment. For historical reports, retain later recorded payments when their receivable arose within the report. Exclusion scenarios remove security-linked income while preserving account-level interest; a recorded-period exclusion keeps income earned at or before the period's opening close.

## Why

A payment-date income entry plus estimated ex-date cash counts the same dividend twice. Interest can also accidentally mask a missing dividend when reconciliation aggregates all income by date. Ex-date accrual better represents when dividend income is earned. This follows the GIPS recommendation for dividend accrual without claiming GIPS compliance. ([GIPS handbook, provision 2.B.3](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/))

## Limits

No future cash entries are posted. An unrecorded or unpaid entitlement lacking a recorded payment remains a reconciliation gap. Income denominated in USD is not proof that a foreign-currency receivable or cash balance has been correctly valued each day. Provider revisions, special distributions and taxes require source review. Current holdings display cash and stock positions; the historical performance report separately includes receivables.

## References

- [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/) — ex-date dividend accrual recommendation.
- [Income reconciliation](../../backend/src/investor_platform/income.py) — security-specific validation and recorded receivables.
- [Cash entry](../../backend/src/investor_platform/ledger.py) — input and ownership validation.
