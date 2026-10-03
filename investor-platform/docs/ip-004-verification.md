# IP-004 verification

Verified 2026-10-01 (local date), using PostgreSQL 17 and synthetic records.

## Automated checks

- 51 backend tests passed. Trade coverage includes an opening/buy/partial-sell/full-close FIFO fixture, fee treatment, unknown basis, atomic cash/share rejection, security rollback, invalid backdating, opening-position ordering, currency/ownership restrictions, retries, concurrent oversells, concurrent cash/trade spending, and fractional/large-number precision.
- 18 desktop/mobile Chromium checks passed. The trade flow opens unknown-basis shares, buys additional shares, loses a committed response then safely retries, rejects an oversell while retaining the draft, partially sells, inspects unknown realized basis, closes the position, and reloads.
- Fresh migrations run twice per database test. `alembic check` found no ORM/schema drift after upgrading an existing cash-ledger database.
- Python lint/format, frontend formatting/typecheck, and production build passed.

## Live browser checks

- Opened 10 synthetic DEMO shares with 800 total basis; cash remained 10,200.
- Bought 5 at 100 with 2 fees: 15 shares, 1,302 basis, 9,698 cash.
- Rejected a 99-share sale without changing the account; the draft remained editable.
- Sold 12 at 120 with 3 fees: 3 shares, 301.20 remaining basis, 11,135 cash. Sale details showed 436.20 FIFO realized P&L.
- Added 2 NOTE opening shares without basis; Holdings showed “Unknown” and cash stayed unchanged.
- Restarted the API and reloaded: the same holdings, basis, activity, and cash were restored from PostgreSQL.
- Inspected desktop and 390px layouts, including the expanded trade form and holdings. Tables scroll within their containers; document width stayed at 390px.

## Limits

Only manual, long-only equities in the account currency. No broker orders, prices, migration of real portfolio data, corrections, or backup/restore in this ticket. Request keys survive retries within the current form; there is no persistent offline queue. The running demo database is separate from the browser-test database.

## References

- [Trade tests](../backend/tests/test_trades.py): reconciliation, precision, atomicity, concurrency, and validation.
- [Browser flow](../web/tests/trades.spec.ts): real UI/API integration, failure recovery, and mobile checks.
- [Accounting rules](portfolio.md#positions-and-trades): precision and FIFO conventions.
