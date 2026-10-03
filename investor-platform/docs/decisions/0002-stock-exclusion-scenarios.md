# ADR 0002: Exclude stocks by replaying a cash alternative

Status: accepted · 2026-10-03

## Context

The user wants to compare performance as if selected stocks had never been held. Simply hiding their current value would retain past gains, trading cash flows and dividends, and change the comparison's capital base unpredictably.

## Decision

A selection identifies a security by its account history ID (ticker plus exchange in the UI), including already-sold stocks. Replay the entire history through the report end, excluding that security's buys, sales and fees. Preserve deposits, withdrawals and other securities' trades. Unused money stays in cash; it is not redistributed. Selection is transient and never changes SQL records.

Replace excluded opening positions with a cash contribution at their first available benchmark session's closing value, including openings before the selected reporting window. This preserves contributed capital without fabricating an original purchase price. Unknown opening cost basis is not a zero market value. Provisional scenarios remain provisional.

Recalculate missing gross distributions from remaining positions only. For now, any explicitly recorded income prevents a scenario because income is account-level and cannot be attributed to the excluded stock. Do not guess. Likewise reject a scenario if the remaining transactions would require borrowing. Return the original comparison with a short scenario error in either case.

Use the same fetched market snapshot, daily sessions and SPY/QQQ comparisons for the original and scenario. Keep original holdings and the all-history scorecard unchanged. Overlay the scenario only on performance, alongside original cumulative and annualized returns.

## Consequences

This is a historical hypothetical, not a forecast or a substitute for reconciled account returns. It assumes other trading decisions and external flows would have stayed the same. Missing valuations and corporate-action safeguards still apply. Security-linked income is a future prerequisite for scenarios with recorded dividends.

## References

- User request in the investor-platform conversation, 3 October 2026 — exclude selected stocks and recalculate performance.
- [Calculation implementation](../../backend/src/investor_platform/performance.py) — cash replay and validation.
- [Data assumptions](../data-assumptions.md) — provisional reconstruction limits.
