# Tracker increment verification

## Trade scorecard

The scorecard was extracted as an independently runnable increment. Backend: 52 tests and Ruff checks pass. Frontend: formatting and production build pass; all 12 desktop/mobile browser workflows pass (the two new scorecard workflows were rerun after narrowing a table locator). The browser test creates a synthetic closed trade, checks its P&L, and exercises failed-load recovery.

The separate `minerva_tracker_demo` portfolio was also inspected in the live browser: 50% win rate, 2.91 payoff ratio, one winner, one loser, and one open position. The 390px layout had no page overflow. All trades are synthetic; no real portfolio records were changed. Benchmark comparisons and investment income are later increments.

## References

- [Scorecard accounting fixture](../backend/tests/test_statistics.py) — fees, partial exits, unknown basis and breakevens.
- [Scorecard browser workflow](../web/tests/scorecard.spec.ts) — synthetic closed trade and load recovery.
