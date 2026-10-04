# Data assumptions

This is the living register of reconstruction assumptions. Change it with the implementation; use [ADRs](decisions/0001-documentation-and-pages.md) when the underlying choice changes. Account-specific evidence belongs in private storage, never in a public issue or PR.

| Assumption | Consequence / resolution |
| --- | --- |
| Transaction history is incomplete. Opening shares and minimum balancing cash are inferred. | Portfolio return, CAGR, excess returns and exclusion scenarios are withheld until dated funding and broker balances are reconciled. Current holdings and benchmark series remain available. |
| Unrecorded trades and deposits/withdrawals are absent from the model. | Missing records can materially change returns. Add dated records and regenerate the comparison. |
| Explicit USD totals establish settlement currency, not listing identity. | Imported exchanges may remain unconfirmed until issuer and listing evidence are reconciled. Keep native quote currency separate from USD cash. |
| Original rows and discrepancies are retained privately. | Use import provenance and correction history for reconciliation. |
| Missing gross distributions are estimated on ex-dates and held in cash. | Same-date recorded income offsets the model; payment-date income can double count distributions. |
| Unrecorded fees and taxes are absent. | Estimates are not after-tax returns. |
| Recent comparisons use recorded opening cash and share quantities. | Missing pre-period income and corporate actions are not reconstructed; verify opening balances. Full history retains its stricter data requirements. |
| Market prices come from one provider. | Values are not independently verified and may be revised. |

See [transaction import](transaction-import.md) for ingestion rules, [performance](performance.md) for calculation conventions and [hit rate](hit-rate.md) for exclusions. The UI retains provisional status and errors that prevent a valid calculation; import details are available from the private account metadata/API.

## References

- [Importer](../backend/src/investor_platform/import_transactions.py) — reconstruction and provenance.
- [Performance calculation](../backend/src/investor_platform/performance.py) — provisional distribution model and validation.


## Missing historical prices

Transaction prices and amounts establish trade cash flows and realized profit, but do not establish daily market value between trades. A complete chart requires closing-price coverage for every held security on each valuation date, plus distribution and split information. The app lists every symbol whose provider history is unavailable in one response; it never silently removes those positions or fills missing prices with transaction prices.

Closed positions can therefore block a full-history chart while current holdings and trade statistics still work. Delisted-price recovery needs a verified source with the correct listing, currency, share units and corporate actions. Sparse monthly charts or successor-company prices cannot substitute for daily history. A manually selected later period or Last 90 days uses recorded starting balances explicitly; it is not a repaired full-history result. Keep account-specific gaps and downloaded evidence in ignored local storage, not in this public document.
