# Reconcile an imported cash history

Use the local `investor-reconcile-cash` CLI after matching broker cash events to the selected portfolio. Portfolio assignment on trade rows does not identify deposits or withdrawals. Match transfers within the portfolio boundary once; preserve unpaired or ambiguous events for review. Keep broker exports, mapping decisions and plans in ignored private storage. Never fabricate dates to make an ending balance fit.

The plan replaces **all active cash records** in one imported portfolio, including inferred opening cash and manual balancing adjustments. It preserves trades, shares and cost basis. Removed cash entries remain in correction history, and the plan/evidence reference is retained in private account metadata. Each cash row follows the ordinary API validation, including dividend security ownership and ex-date/payment-date attribution.

## Preview and apply

Obtain the account ID and active cash entry IDs from its ledger. Create a private JSON plan with a fresh UUID for the plan and each cash row; preserve these keys when retrying the same plan. For example, using synthetic data:

```json
{
  "request_key": "00000000-0000-4000-8000-000000000010",
  "source_reference": "Reviewed synthetic cash statement and account mapping",
  "as_of": "2026-01-06",
  "reported_cash": "0.00",
  "remove_entry_ids": [1],
  "confirm_complete_funding": true,
  "entries": [
    {"request_key": "00000000-0000-4000-8000-000000000011", "kind": "deposit", "currency": "USD", "effective_date": "2026-01-02", "amount": "10"},
    {"request_key": "00000000-0000-4000-8000-000000000012", "kind": "deposit", "currency": "USD", "effective_date": "2026-01-05", "amount": "20"}
  ]
}
```

Run from the backend project with the intended private `DATABASE_URL`:

```sh
uv run investor-reconcile-cash --account ACCOUNT_UUID --plan private-plan.json
```

Preview performs the complete replacement and validation inside a rolled-back transaction. Review its balances, replaced/added record counts, intended cash method and funding status, and source evidence. Copy its `revision` into the plan's `expected_revision`, then back up the database before applying:

```sh
uv run investor-reconcile-cash --account ACCOUNT_UUID --plan private-plan.json --apply
```

Retries return the original receipt without changing account policy. If an older reconciliation retained `cash_method: purchase_shortfall`, apply a fresh reviewed plan with a new request key to enter recorded-cash mode; this fix does not rewrite historical receipts or account metadata automatically.

The account lock, revision check, unique retry keys and transaction prevent partial imports, concurrent stale writes and duplicate retries. Closing cash must match the reported checkpoint to cents, and the checkpoint must cover all existing records. Cash is validated at each date's end because source timestamps are unavailable; funding from a later date cannot rescue an earlier deficit. Original same-day trade ordering remains intact for FIFO.

Applying the plan changes the cash method to `recorded`, for both incomplete and complete reviews. This stops automatic purchase-shortfall deposits while keeping whole-account performance and the two index choices. Later cash changes and trades must be funded by the recorded cash history; no inferred deposits are added. Reload the account after applying a plan to update its cash labels.

`confirm_complete_funding` is an explicit evidence-review assertion, not a conclusion inferred from a matching cash total. Leave it false when dated external flows or portfolio allocation remain incomplete. False keeps the whole-account return and CAGR withheld. True clears only the funding gate; prices, corporate actions and other calculation failures still withhold returns. The separate explicit zero-unrecorded-dividend policy is preserved when present. Without that policy, missing dividends still withhold returns; recorded income mismatches remain blocking in either case. The CLI does not download statements, guess cash dates, map private accounts automatically or certify completeness.

## References

- [Reconciliation implementation](../backend/src/investor_platform/ledger/reconcile_cash.py) — atomic preview/apply and retained evidence.
- [Accounting](../backend/src/investor_platform/ledger/accounting.py) — dated cash validation and FIFO preservation.
- [Performance methodology](performance.md) — flow timing, dividend validation and benchmark calculations.
