# ADR 0003: Price current holdings independently of historical performance

Status: accepted · 2026-10-03

## Context

A complete-history return can be unavailable because of closed securities, missing historical prices or unsupported corporate actions. Reusing that report for current holdings blanked out current prices and allocation unnecessarily.

## Decision

Value current recorded positions through a separate endpoint. Fetch only open securities, using recent completed closes. A performance date change or scenario does not change the current holdings view. Refresh quotes explicitly or after ledger changes; late responses from an older ledger are discarded.

Cash is the recorded SQL balance; this endpoint does not invent missing income. ASX and TSX Venture positions with explicitly recorded exchanges use their native quotes converted at same-date AUD/USD or CAD/USD closes. USD book amounts and quote currency are distinct. Unverified symbols never imply a foreign listing; obtain explicit listing identity first.

A failed quote affects that row only. Keep other valid prices and all recorded shares/bases visible, but withhold aggregate value and every market weight until all open positions are valued. Reject closes more than four calendar days old and missing same-date FX. Latest closes are indicative valuations, not executable or intraday prices. Provider data remains single-source and provisional records remain labeled.

## Consequences

The overview remains usable when a historical comparison fails. Current holdings need no prices for closed/delisted stocks and are not subject to the performance report's historical-symbol limit. Historical split/FX accounting and whole-history return support are separate capabilities; current FX valuation does not implement them.

## References

- [Valuation endpoint](../../backend/src/investor_platform/valuation.py) — current holdings and failure isolation.
- [Market adapter](../../backend/src/investor_platform/market.py) — quote currency and instrument checks.
- [Performance conventions](../performance.md) — independent historical return and scorecard rules.
