# ADR 0004: International listings and USD history

Status: accepted.

## Decision

The ledger retains USD settlement amounts. Quote currency is separate: an Australian listing can have AUD quotes while its recorded purchase cost is already USD. Never convert those recorded amounts a second time.

Use an exchange-to-provider mapping for ASX (AUD), TSX/TSXV (CAD), and Stockholm main/First North markets (SEK). US listings and USD OTC quotes retain their own provider exchange checks. Reconstructed accounts may resolve an unknown US listing provisionally, but a confirmed exchange must always match the provider, including in provisional reports.

Convert historical closes and distributions using dated currency-to-USD quotes. SPY/QQQ sessions remain the reporting calendar. When a foreign exchange is closed, carry its most recent local close for at most four calendar days and apply the valuation day's FX. Never look ahead, carry FX, cross an unpriced split, or value missing data at zero. Current holdings retain the stricter matching-quote-date FX convention from ADR 0003.

History requests support 128 securities with at most six concurrent fetches. Each listing and currency pair is fetched once per request. A public symbol is included in unavailable-history errors so missing delisted data can be investigated without leaking provider payloads.

## Metadata maintenance

Exchange corrections update security identity in PostgreSQL, not the original export. Verify the issuer name and native currency as well as the ticker; bare symbols can name unrelated issuers in different countries. An exchange field identifies the primary quote listing, not the execution venue of each historical trade. Keep evidence, before/after receipts and backups in ignored local storage; keep original import provenance unchanged. Do not embed portfolio-specific mappings in application code.

For an imported account, retain a dated verification receipt in its reconstruction metadata. Compare ledger amounts, shares, IDs, cash and scorecard before and after the transaction. Reject identity collisions instead of combining positions automatically. A provider listing match does not independently verify prices, historical corporate actions, or all earlier exchange changes.

## Limits

FX support does not repair missing purchase records, delisted histories or unrecorded splits. These still withhold affected comparisons. Closed-position P&L and the scorecard remain based on recorded USD cash, without FX repricing. The closed-position table explicitly distinguishes unknown basis from an unconfirmed exchange.

## References

- [Market adapter](../../backend/src/investor_platform/market.py) — listing mapping, history validation and FX conversion.
- [Performance methodology](../performance.md) — linked returns, dividends and split safeguards.
- [ADR 0003](0003-independent-holdings.md) — current holdings and matching-date FX.
