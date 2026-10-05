# Transaction reconstruction for testing

Use `investor-import` in the backend uv project to preview a transaction export and import it into a separate, empty PostgreSQL database. It never replaces an existing account. The app remains SQL-owned; this is an explicit import command, not ongoing sheet sync.

```sh
uv run --frozen investor-import --source /path/transactions.gviz --listings /path/listings.json
# After inspecting the preview, migrate a separate testing database and apply:
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/TEST_DB uv run --frozen alembic upgrade head
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/TEST_DB uv run --frozen investor-import --source /path/transactions.gviz --listings /path/listings.json --apply
```

`--source` accepts a local CSV, an unformatted Google visualization export, or its HTTPS URL. For an existing Google `/gviz/tq` export, use `tqx=out:json` to retain underlying numeric cell values. CSV display values can round fractional shares to zero. The importer reads numeric `v` values rather than formatted `f` values in the unformatted export. Run with no `--apply` for a preview without database writes.

The source accepts two layouts:

- `Date, Type, Symbol, Shares, Price (USD), Total (USD)`: one unit-price and reported-cash column for both buys and sales. The positive total is authoritative for cash, cost basis and realized P&L, including any embedded charges. Preserve the quoted unit price separately; do not invent itemized fees. Both CSV and unformatted Google exports use this rule. Empty/invalid totals are excluded, never inferred from unit price.
- Legacy `Date, Type, Symbol, Shares, Cost, Price`: Cost is the buy unit price and Price is the sale unit price. Optional Total Cost and Market Value columns supply cash totals for formatted CSV imports; legacy unformatted exports retain their prior unit-price convention.

Dates use ISO or US month/day/year; Type is Buy or Sell. Invalid rows remain in source evidence and are explicitly excluded. USD column labels establish cash denomination, not the exchange or identity of a security. Keep unverified listings marked as such; foreign/delisted instruments are not silently substituted with US tickers.

The listing map makes identity and the **recorded amounts' currency** explicit:

```json
{
  "DEMO": {"exchange": "NASDAQ", "currency": "USD"},
  "UNCERTAIN": {"note": "Currency or listing needs confirmation"}
}
```

Only confirmed USD rows are imported. An omitted exchange becomes `UNVERIFIED`; it cannot be used for market quotes. Do not map an ambiguous foreign ticker to a similarly named US listing. There is no external ticker lookup in this command.

## Reconstruction rules

- USD-total exports normalize cash to eight decimal places (removing spreadsheet floating-point noise), while preserving the untouched source payload. Reported cash can differ from shares × rounded unit price. A subsequent correction uses the standard quantity/price/fees model; inspect its cash delta before confirming.
- Unformatted exports retain underlying shares and unit prices, rounded to the ledger's eight-decimal precision. CSV imports prefer source cash totals divided by recorded shares; original displayed prices and any discrepancy remain in the evidence. Fees are not separately inferred.
- Sort by date, preserving source order within each date. Duplicate-looking rows remain separate source rows; the importer does not guess that they are duplicates.
- Infer the minimum opening shares needed to avoid a short position. Their acquisition dates and cost bases remain unknown. Infer the minimum starting cash needed to replay the history, rounded up to cents. Neither is a verified broker balance.
- Preserve every original source row, the original payload, its SHA-256 fingerprint, listing choices, exclusions and assumptions in the account's PostgreSQL reconstruction field. The account API exposes only the summary, not the raw payload.
- Create the account and ledger in one transaction and replay its accounting before commit. Identical source/listing inputs are a no-op on retry; different inputs require a new empty testing database. Existing records are never overwritten.
- The interface labels holdings, cash and trade statistics as provisional. Portfolio comparisons are explicitly provisional: they assume no missing flows or trades, use provider USD listings for imported US tickers, and model missing gross distributions on their ex-dates without changing the ledger. Recorded income offsets modeled income only on the same ex-date; payment-date income can double count it. Missing prices and positions spanning splits still block results. Restoring a complete source does not automatically remove the provisional flag; verified reconciliation is separate work.

Keep actual exports, listing maps and import reports outside Git. Automated checks use synthetic fixtures. The original demo database can be retained while the private preview points at the reconstruction database.

## Refreshing a testing portfolio

Download a new timestamped source snapshot into ignored local storage, review the preview and listing map, then migrate and import into a new empty testing database. Verify imported row count, recorded totals and source fingerprint before pointing the private app's `DATABASE_URL` at the new database. Retain the prior database for rollback. This is a deliberate replacement of the displayed test dataset, not an incremental sync or an overwrite of existing records.

A longer import does not remove market-data limits. The current comparison supports at most 48 securities across recorded history; unsupported listings, missing/delisted prices and splits while held can also block comparisons. All imported activity, independently priced current holdings and the trade scorecard remain available when historical market performance cannot be calculated. ASX/TSXV positions require those explicit exchange identities in the local listing map for native-currency quotes and USD conversion. See [performance](performance.md).
