# Append reviewed income and expenses

Use `investor-import-cash` for a one-time import into an existing imported account.
It reads a broker-neutral JSON plan. It does not read or synchronize spreadsheets.

Each plan has `request_key` (a stable batch UUID), `source_reference` (a private
source document reference), and `entries` (the existing `CashInput` contract).
Each entry needs its own stable source-event UUID, `kind` (`income` or `expense`),
`effective_date` (cash posting date), `amount` (positive magnitude), `currency`,
and a short `note` with the source event context. Keep plans and receipts private.

Verified dividends also need `income_kind: "dividend"`, `income_security_id`, and
`accrual_date` (verified ex-dividend date). If attribution is not verified, omit
all three fields and retain the dividend context in the note and source reference.
Such income stays unclassified and does not establish verified dividend returns.
Record withholding tax and ADR fees separately as positive `expense` amounts.

From the backend project:

```sh
uv run investor-import-cash --account UUID --plan reviewed-cash.json
```

Preview is the default and rolls back all database changes. Review `previous_cash`,
`cash`, both inferred-deposit totals, added/skipped counts, and unresolved income.
Add the returned `revision` to the plan as `expected_revision`, then apply:

```sh
uv run investor-import-cash --account UUID --plan reviewed-cash.json --apply
```

The whole batch commits atomically under the account lock. It preserves holdings
and trades and recalculates canonical inferred funding once. Historical income can
reduce inferred deposits, so ending cash need not rise by the total imported income.
Recorded cash outflows still require sufficient funding evidence.

The same batch key and unchanged plan return the stored receipt on retry. A new
batch skips active events only when their stable keys and cash fields match exactly.
Changed values or corrected event keys require explicit ledger review. Distinct keys
are not evidence that two otherwise identical rows are different source events:
use the same source-event keys across overlapping plans. The complete plan, digest,
and result stay in the account's private `reconstruction.cash_imports` receipts.
