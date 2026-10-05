# Data assumptions

This is the living register of reconstruction assumptions. Change it with the implementation; use [ADRs](decisions/0001-documentation-and-pages.md) when the underlying choice changes. Account-specific evidence belongs in private storage, never in a public issue or PR.

| Assumption | Consequence / resolution |
| --- | --- |
| Transaction history is incomplete. Opening shares and minimum balancing cash are inferred. | Results remain provisional until broker balances and external flows are reconciled. |
| Unrecorded trades and deposits/withdrawals are absent from the model. | Missing records can materially change returns. Add dated records and regenerate the comparison. |
| Explicit USD totals establish settlement currency, not listing identity. | Imported exchanges may remain unconfirmed until issuer and listing evidence are reconciled. Keep native quote currency separate from USD cash. |
| Original rows and discrepancies are retained privately. | Use import provenance and correction history for reconciliation. |
| Missing gross distributions are estimated on ex-dates and held in cash. | Same-date recorded income offsets the model; payment-date income can double count distributions. |
| Unrecorded fees and taxes are absent. | Estimates are not after-tax returns. |
| Market prices come from one provider. | Values are not independently verified and may be revised. |

See [transaction import](transaction-import.md) for ingestion rules, [performance](performance.md) for calculation conventions and [hit rate](hit-rate.md) for exclusions. The UI retains provisional status and errors that prevent a valid calculation; import details are available from the private account metadata/API.

## References

- [Importer](../backend/src/investor_platform/import_transactions.py) — reconstruction and provenance.
- [Performance calculation](../backend/src/investor_platform/performance.py) — provisional distribution model and validation.
