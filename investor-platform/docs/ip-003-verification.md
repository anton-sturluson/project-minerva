# IP-003 verification

Verified 2026-10-01 (local date), with synthetic data and PostgreSQL 17.

- 26 backend tests passed. Cash coverage includes exact decimal fixtures, audit fields, canonical idempotent retries, key conflicts, unsupported/invalid/future entries, full-history backdating checks, atomic rejection, cross-workspace access, concurrent withdrawals, and concurrent duplicate requests.
- 16 desktop/mobile browser checks passed. The cash flows cover deposits, rejected overdrafts with retained drafts, successful correction of the draft, reload persistence, and a response lost after the server committed followed by a safe retry.
- Live in-app browser: entered 10,000 opening cash, deposited 250, rejected a 20,000 withdrawal, then withdrew 50. The resulting 10,200 balance and three entries survived reload. Inspected the 390px form/activity layout; page width matched the viewport.
- Python lint/format and frontend formatting/typecheck/build passed.

Browser workflows run sequentially because they share a single synthetic account. Concurrency correctness is exercised independently against PostgreSQL in the backend suite. No real portfolio data was imported. Corrections and backup/restore remain later tickets.
