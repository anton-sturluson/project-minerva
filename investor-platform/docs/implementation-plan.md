# Investor Platform delivery plan

Updated: 2026-10-02. One ticket per PR; stack dependent PRs and live-test every increment with synthetic data. PostgreSQL owns records; spreadsheet migration is optional later work. ([Project instructions](../AGENTS.md))

## Implemented

The app has a local/private shell, one account, immutable cash and equity records, FIFO positions, investment income, a win/payoff scorecard, benchmark-relative decision hit rate, and dated SPY/QQQ comparisons. Tailscale provides private access for the local owner. The transaction import CLI creates a separate testing copy; provisional comparisons and reviewed ledger corrections are available. Research remains a placeholder. ([Current capabilities and limits](portfolio.md))

## Next small increments

1. **Verified backup/restore (IP-007):** export and restore into a separate database, then verify records and calculated balances. Do this before relying on the app for real data.
2. **Portfolio reconciliation:** verify opening cash/shares/basis, missing flows, distributions and excluded transaction rows. The one-time testing import already exists; verification remains separate.
3. **Research notebook:** one stock/topic with cited links and notes. Add news collection only after the basic save/read workflow is reliable.
4. **Public hosting:** managed authentication and per-user ownership, deployment configuration, and data-provider usage rights before serving outside users.

These are proposed tickets, not scaffolding requirements. Complete one user-visible workflow at a time; keep useful accounting, authorization and recovery checks with the code they protect. ([Architecture](architecture.md))

## References

### Project decisions and implementation

- User direction in the Minerva investor-platform conversation, 1–2 October 2026: local first, native SQL ownership, small hardened features, stacked PRs and live browser testing.
- [Project instructions](../AGENTS.md): delivery and verification requirements.
- [Portfolio guide](portfolio.md): shipped functionality and current limitations.
- [Architecture](architecture.md): implemented boundaries.
