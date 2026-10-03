# ADR 0001: Keep methods in documentation and separate viewing from recording

Status: accepted · 2026-10-03

## Context

The portfolio page mixed analysis, import explanations and editing forms. The user requested a concise overview, separate Activity and Research pages, and a durable record of assumptions.

## Decision

Use small, numbered ADRs for lasting product or architecture choices: context, decision and consequences. Update living methodology documents when calculation rules change; record the reason in the same PR. Do not create an ADR for every implementation detail.

Portfolio is the overview. Activity contains collapsible trade entry, cash entry and transaction history. Research has its own view. Hash navigation works with the existing local/static deployment and browser back/forward, without another routing dependency. Keep drafts mounted during navigation so changing views does not discard an uncertain save's retry key.

Move methodological prose to [performance](../performance.md), [hit rate](../hit-rate.md) and [data assumptions](../data-assumptions.md). The app retains provisional labels, unavailable states and actionable reconciliation errors. These qualify the numbers at the point of use.

## Consequences

Docs and behavior must change together in each PR. Public GitHub holds only general rules and synthetic examples. Account-specific import counts, holdings, source exports and reconciliation evidence stay in the private database or ignored local files. Removing explanations from the interface does not remove their audit evidence.

## References

- User request in the investor-platform design conversation, 3 October 2026 — concise pages and documented decisions.
- [Privacy rules](../privacy.md) — public repository boundaries.
