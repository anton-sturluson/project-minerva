# Transaction reconstruction for testing

Use `investor-import` in the backend uv project to preview a transaction export and import it into a separate, empty PostgreSQL database. It never replaces an existing account. The app remains SQL-owned; this is an explicit import command, not ongoing sheet sync.

```sh
uv run --frozen investor-import --source /path/transactions.gviz --listings /path/listings.json
# After inspecting the preview, migrate a separate testing database and apply:
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/TEST_DB uv run --frozen alembic upgrade head
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/TEST_DB uv run --frozen investor-import --source /path/transactions.gviz --listings /path/listings.json --apply
```

`--source` accepts a local CSV, an unformatted Google visualization export, or its HTTPS URL. For an existing Google `/gviz/tq` export, use `tqx=out:json` to retain underlying numeric cell values. CSV display values can round fractional shares to zero. The importer reads numeric `v` values rather than formatted `f` values in the unformatted export. Run with no `--apply` for a preview without database writes.

The source needs Date, Type, Symbol, Shares, Cost and Price columns. Optional Total Cost and Market Value columns supply cash totals for formatted CSV imports. Dates use ISO or US month/day/year. Type is Buy or Sell; Cost is the buy unit price, Price is the sale unit price. Rows with invalid values are retained as evidence and explicitly excluded from the ledger.

The listing map makes identity and the **recorded amounts' currency** explicit:

```json
{
  "DEMO": {"exchange": "NASDAQ", "currency": "USD"},
  "UNCERTAIN": {"note": "Currency or listing needs confirmation"}
}
```

Only confirmed USD rows are imported. An omitted exchange becomes `UNVERIFIED`; it cannot be used for market quotes. Do not map an ambiguous foreign ticker to a similarly named US listing. There is no external ticker lookup in this command.

## Reconstruction rules

- Unformatted exports retain underlying shares and unit prices, rounded to the ledger's eight-decimal precision. CSV imports prefer source cash totals divided by recorded shares; original displayed prices and any discrepancy remain in the evidence. Fees are not separately inferred.
- Sort by date, preserving source order within each date. Duplicate-looking rows remain separate source rows; the importer does not guess that they are duplicates.
- Infer the minimum opening shares needed to avoid a short position. Their acquisition dates and cost bases remain unknown. Infer the minimum starting cash needed to replay the history, rounded up to cents. Neither is a verified broker balance.
- Preserve every original source row, the original payload, its SHA-256 fingerprint, listing choices, exclusions and assumptions in the account's PostgreSQL reconstruction field. The account API exposes only the summary, not the raw payload.
- Create the account and ledger in one transaction and replay its accounting before commit. Identical source/listing inputs are a no-op on retry; different inputs require a new empty testing database. Existing records are never overwritten.
- The interface labels holdings, cash and trade statistics as provisional. Portfolio return requests are blocked because external flows and opening cash are unknown. Restoring a complete source does not automatically remove that flag; verified reconciliation is separate work.

Keep actual exports, listing maps and import reports outside Git. Automated checks use synthetic fixtures. The original demo database can be retained while the private preview points at the reconstruction database.
