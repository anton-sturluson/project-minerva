# ADR 0007: Measure stock transactions independently of brokerage cash

Status: accepted

## Decision

Default the performance view to an explicitly labelled stock-only daily return. Keep the whole-account calculation available, with its existing reconciliation guard. Historical cash records must not be fabricated or certified to unlock the stock comparison.

Stock purchases contribute their execution cost, sales remove their net proceeds, and in-kind receipts contribute their closing value. Provider-estimated gross dividends are paid out of this analytical sleeve on the ex-date. This is a read-only calculation: none of these analytical cash flows are stored. Cash interest, lending, tax, account fees and native cash FX are outside the selected boundary. Full details and methodological references are in [Performance](../performance.md).

## Consequences

Stock selection can be assessed without completing brokerage cash reconciliation. Its result must not be presented as the whole-account return. Actual trading fees are included only when present in recorded trade amounts. Market-price, identity and split checks remain; incomplete trade histories still produce provisional results. Exclusions remove the selected stocks and their invested capital rather than preserving unused cash. Whole-account statistics continue to require reconciled funding and distributions.
