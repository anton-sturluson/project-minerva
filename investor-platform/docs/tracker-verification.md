# Tracker increment verification

## Trade scorecard

The scorecard was extracted as an independently runnable increment. Backend: 52 tests and Ruff checks pass. Frontend: formatting and production build pass; all 12 desktop/mobile browser workflows pass (the two new scorecard workflows were rerun after narrowing a table locator). The browser test creates a synthetic closed trade, checks its P&L, and exercises failed-load recovery.

The separate `minerva_tracker_demo` portfolio was also inspected in the live browser: 50% win rate, 2.91 payoff ratio, one winner, one loser, and one open position. The 390px layout had no page overflow. All trades are synthetic; no real portfolio records were changed. Benchmark comparisons and investment income are later increments.

## References

- [Scorecard accounting fixture](../backend/tests/test_statistics.py) — fees, partial exits, unknown basis and breakevens.
- [Scorecard browser workflow](../web/tests/scorecard.spec.ts) — synthetic closed trade and load recovery.

## Investment income

Income was tested before adding the market comparison: 53 backend tests, migration upgrade/metadata checks, formatting/build, and all 12 desktop/mobile browser workflows pass. The existing synthetic cash workflow now records income, verifies the exact cash increase and persistence, and still exercises failure/recovery. A focused database test covers positive amounts, unchanged-payload retry, changed-payload rejection and rollback. No real portfolio was used.

## Valuations and benchmark comparison

The final stacked increment passes 64 backend tests, Ruff, migration metadata checks, frontend formatting/build, and 14 desktop/mobile browser workflows. It retains the independent scorecard and income checks. Comparison tests use fixed market responses and exercise failed refresh/recovery; the adapter and numerical fixtures are tested separately. The same synthetic AAPL demo used before splitting verifies the public AAPL/SPY/QQQ feed in the live app.

Production source and migrations match the previously tested complete tracker. The split changes delivery boundaries, adds focused earlier-increment checks, and clarifies synthetic-data instructions. It does not migrate real holdings or change financial behavior. Limits and primary sources remain in [performance.md](performance.md).
