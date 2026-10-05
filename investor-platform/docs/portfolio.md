# Portfolio guide

## Multiple portfolios

Use the Portfolio selector to switch among your portfolios, or New portfolio to create another. Each has independent cash, trades, corrections, holdings and performance. The selected portfolio is remembered on this browser when local storage is available. Switching unmounts the previous portfolio view and clears unsaved drafts so data cannot leak into another portfolio. Names are unique within your workspace; currencies remain fixed.

## Cash ledger rules

- Entered cash amounts are decimal strings, with at most 16 integer and 8 fractional digits. Browser displays retain exact stored values; no floating-point arithmetic is used for balances.
- Opening cash is the first entry and defines the start of tracking. Later entries cannot precede it. Starting with a deposit is also supported; an opening balance cannot be added afterwards.
- Dates are posting dates in New York, not settlement accounting. No future-dated entries. Same-day order is the original database sequence, shown in activity order. Replacements retain the original entry’s place in that sequence.
- Every write locks the account, checks its complete dated history, and commits atomically. Cash cannot be negative at the end of any recorded date. Same-day funding may be recorded after a trade; a later date cannot fund an earlier one. Concurrent withdrawals obey the same rule.
- A client-generated request key identifies a write. Retries with the same payload return the original entry; changed content with that key is rejected. Each form retains its key after an uncertain response and its draft after validation errors. Before reloading a page after an uncertain write, retry the unchanged form or inspect activity; request keys are held in the current form, not a persistent offline queue.
- Records include creation time and owner identity. Use **Correct** in Activity to preview a replacement or void, supply a reason, and confirm. Original entries are retained in Correction history with their replacements, reasons, timestamps and owner identity. Backup/restore remains separate work.

## Positions and trades

Open **Record a position or trade** below Holdings. Enter an exchange-qualified ticker and select opening position, buy, or sell. Securities must be equities denominated in the account currency; there is no symbol lookup or currency conversion. The same ticker on another exchange is a different security. Names are normalized to uppercase.

- An opening position records shares already owned without a cash trade. Its optional **total** cost basis includes any historical acquisition fees. Blank means unknown; zero is an explicit known zero. Record opening cash first if you need it, then opening positions before trades in each security.
- Buys debit quantity × price + fees. Sells credit quantity × price − fees; fees exceeding proceeds are unsupported. Quantity and price allow up to 12 integer and 8 fractional digits. Products and cash effects retain up to 16 decimal places without currency-cent rounding; figures represent entered records, not broker settlement calculations.
- Sales consume the oldest shares first (FIFO), ordered by effective date then saved sequence. Buy fees are included in lot basis and sell fees reduce proceeds. A partial lot's allocated basis rounds half-even at 16 decimal places; its final sale consumes the exact remaining basis so residuals reconcile.
- Unknown opening basis stays unknown. A sale that consumes any unknown-basis shares has no reported realized gain. Remaining holdings show unknown basis until those shares are exhausted. Sale details include FIFO realized P&L only when all consumed basis is known.
- Cash and shares must stay nonnegative throughout the full history, including after backdated writes. All cash and trade writers use the same account lock. A rejected write also rolls back any newly created security.
- Holdings and cash are derived from immutable entries. No editable balances, splits, shorts, margin, options, or foreign-currency trades. Investment income is entered through the cash form; valuation and return rules are below. Corrections revalidate the entire active history atomically; backup/restore remains IP-007.

The forms record activity only; they never place orders. The development demo uses a separate synthetic database. Imported testing copies remain provisional until reconciled.

## Received shares

Choose **Receive shares** to record an in-kind contribution on its actual receipt date, including after earlier trades in that security. Enter shares and optional original total cost basis; unknown basis stays unknown. A receipt does not move cash or invent a purchase. Corrections can replace an inferred opening holding with a dated receipt while retaining the original audit entry.

Performance treats the receipt's market value as an external contribution, so the receipt itself is not investment profit. Exclusion scenarios retain its contributed value as cash. Decision hit rate excludes episodes with received shares because original purchase dates are not established. A split before a receipt does not apply to those later-received shares; genuine positions spanning an unrecorded split still block a report.

Imported minimum opening holdings remain provisional. When receipt evidence becomes available, reconcile their date and basis through the correction workflow; do not disable corporate-action checks or silently adjust quantities to force a result.

## Transaction reconstruction

The [transaction import CLI](transaction-import.md) downloads or reads a source export, previews the reconstruction and writes a separate testing database. It preserves fractional shares, raw evidence, exclusions and inferred balances. Incomplete imports retain inferred balances and withhold returns until funding and distributions reconcile.

## Portfolio tracker

The win/payoff scorecard loads from saved records and needs no market feed. It groups each security's flat-to-flat position into one closed trade; partial sales stay in that episode. It shows win rate, average dollar win/loss, payoff ratio, and excluded open/unknown-basis positions. FIFO P&L includes transaction fees and excludes dividends.

Open **[ Performance ]** for an automatic comparison from the first recorded date through yesterday. Choose **From / Through**, then **Compare performance** for a shorter period or fresh quotes; **Retry comparison** recovers from a data outage. The result includes portfolio value, cash, holdings weights, unrealized P&L, a daily return chart/table, and excess return against SPY and QQQ total-return proxies. The period ends before today in New York; actual baseline/end dates are shown. Editing dates clears the old report; saving ledger records reloads the full recorded period. Market requests do not alter ledger records. Tiingo responses are privately cached; calculated reports are not immutable audit snapshots.

This first feed supports USD equities/ETFs on NYSE, NASDAQ, NYSEARCA/ARCA, AMEX and BATS (plus XNYS/XNAS/ARCX aliases), with matching provider listing metadata. It supports at most 128 portfolio securities and ten years of ledger history. Yahoo is the default stock source. An optional Tiingo API key enables unavailable US histories and dated FX; see [setup](operations.md#historical-data-fallback). Only public symbols and date ranges go to providers; account names, quantities and transactions stay local. A provider outage leaves record entry and the scorecard usable.

Returns treat cash deposits as available at the beginning of the session, and withdrawals and close-valued share receipts at its end. Missing prices, positions spanning splits, unsupported listings/currencies, and undefined zero-balance periods block comparisons. Missing gross distributions withhold portfolio return; record dividend income with a security, ex-date and actual cash payment date, then reconcile against broker history. The performance report recognizes unpaid recorded dividends as receivables; the cash balance changes only on payment. These checks do not establish complete corporate-action coverage. Quotes are provider-sourced and revisable. This is local exploratory tracking, not an audited return or a data-redistribution service.

See [calculation definitions and sources](performance.md). Split accounting, verified backup/restore and reconciliation of real portfolio records remain separate work.

## Decision hit rate

Alongside payoff ratio and win rate, **Calculate hit rate** measures how many fully closed investment decisions beat SPY and QQQ over matching holding periods. A profitable decision can underperform the market. Partial exits count as one decision; unavailable comparisons are explicitly excluded. The report fetches market data on demand, while the original payoff scorecard remains available without it. See [definitions, matched-capital calculations and exclusions](hit-rate.md).

## Ledger corrections

Choose **Correct** beside an active entry in Activity. Replace its date, type, amount, security, shares, price, fees, opening basis or note; or choose **Void entry** to exclude it from active calculations. Supply a reason, preview resulting cash and holdings, then confirm. Cancel leaves the ledger unchanged. Changing the draft requires another preview. If another write occurs after preview, confirmation is rejected until the correction is reviewed again.

Corrections append a record and optional replacement; they do not delete or rewrite original entries or import evidence. A replacement retains the original same-day position through repeated corrections, preserving cash and FIFO ordering. All balances, holdings, payoff statistics and market calculations read the active history. Corrections and ordinary writes share the account lock, and any negative cash/shares or invalid opening history rejects the whole change. Identical confirmation retries apply only once. A voided entry remains in the audit history and can be re-entered through the normal entry form if needed.

Migration `0006` adds the audit table and replaces opening-entry database indexes with validation under the account lock. It does not alter existing ledger values. Downgrading after corrections would revive superseded entries, so this migration refuses downgrade; restore a pre-correction database backup instead. Corrections do not automatically mark a reconstructed portfolio verified.

## Allocation comparison

Market % is each position’s closing market value divided by portfolio value, including cash. Cost % is remaining position basis divided by total remaining basis plus the same cash balance. Cash participates in both denominators. These are allocation measures, not a gain/loss percentage or original lifetime capital allocation. The chart compares the five largest positions by market value and groups smaller holdings as Other. All cost weights are unavailable when any open position has unknown basis or the cost denominator is zero; known subsets are never normalized as a complete portfolio. Recorded quantities and basis remain available during quote outages.

## Current holdings valuation

Current holdings fetch only open securities and remain available if the historical performance report fails. A missing quote keeps the affected row unpriced while other rows retain their prices; aggregate value and market weights are withheld until complete. ASX/TSXV quotes use verified listing identity and same-date AUD/USD or CAD/USD closes. Prices must be no more than four calendar days old. Cash is the recorded balance, without modeled distributions. Use Refresh prices to retry. See [ADR 0003](decisions/0003-independent-holdings.md).

## Investment income

Choose **Dividend · gross**, **Interest**, or **Other investment income** under Activity → Record cash. Dividends require a security already present in the account records and an ex-dividend date no later than the effective cash payment date. Record taxes as **Fee or tax**. Corrections retain and preview the income classification, security and ex-date. Interest remains in exclusion scenarios; dividends for excluded stocks are removed. Unclassified/other income blocks scenarios because its stock attribution is unknown.

## References

- [Ledger implementation](../backend/src/investor_platform/ledger.py) — active records and cash writes.
- [Accounting](../backend/src/investor_platform/accounting.py) — cash validation and FIFO calculations.
- [Corrections](../backend/src/investor_platform/corrections.py) — preview, replacement, void and audit behavior.
- [Performance methodology](performance.md) and [hit-rate methodology](hit-rate.md) — benchmark comparisons.

## Overview and pages

Portfolio shows the trade scorecard, one holdings table with allocation bars, then performance. Allocation uses recent completed closes and current recorded shares and cash, independently of the selected performance period. Cash is included in the denominator. The five largest securities are shown separately, with smaller positions grouped as Other holdings. Without quotes, recorded shares and basis remain available; market values and allocation stay unavailable. Activity contains collapsible cash/trade forms and transaction history. Research is a separate placeholder view.

Cash **Fee or tax** entries reduce both cash and investment return. Use **Withdrawal** only for money leaving the investment portfolio, not brokerage fees, debit interest or withholding tax. Do not record a fee separately if a trade already includes it.
