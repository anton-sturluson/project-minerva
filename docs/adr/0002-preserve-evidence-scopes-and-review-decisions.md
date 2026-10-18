# 0002. Preserve evidence scopes and review decisions

## Status

Accepted

## Context

The agent-directed workflow in [ADR-0001](0001-direct-original-source-research-with-agents.md) finds more original commentary, but valid sources can still fail when a discovery label names a manager, an umbrella, or several funds. The model prompt and application also apply different naming rules. Repeated assessment of unchanged evidence can produce a different answer without resolving the underlying issue.

Large originals currently fail a model-input limit before they are archived. Agents cannot inspect a bounded fund section even when the complete original contains the required evidence. A citation correction can also trigger a new assessment of an already approved, unchanged source.

These problems concern evidence integrity and source access. Existing delivered digests and receipts must remain stable.

## Decision

Apply one identity policy to model instructions, application validation and independent review. Retain discovery labels as provenance. Resolve the actual source fund through explicit original evidence of the publisher, fund and any umbrella or member relationship. Preserve specific fund, region, style and vehicle constraints; do not infer relationships through fuzzy matching or an alias registry.

Archive complete originals and preserve their source locations. Permit a bounded, contiguous commentary section with separate identity anchors. Identity anchors can establish publisher, date or fund relationships, but cannot support thesis claims. Validate the same selected evidence during attribution, extraction, review and publication.

Reuse accepted and rejected decisions when the target, source content, selected evidence, proposed claims and policy are unchanged. A different URL, model or delegation does not reopen a decision. A rejected draft can be replaced by an explicit revised claim proposal, which needs the same independent support review; it does not invalidate an accepted source. Provider and transport failures remain recoverable operational failures. Citation-only changes retain prior approval only after content equality, source-route validation and the normal evidence checks pass.

Keep the existing three database tables, file archive and Minerva CLI. Preserve legacy identity interpretation and rendering so that this change does not alter an already delivered digest.

## Consequences

- Source relationships and research gaps become easier to explain and reproduce.
- Repeated model calls cannot silently replace an unchanged rejection with an approval.
- Large originals remain available for inspection without treating the full document as one model input.
- Missing relationship proof remains unresolved, including unsupported spelling corrections.
- Selected sections require care: the enclosing fund context must remain clear, and identity anchors must not become claim evidence.
- A policy correction or new evidence may require explicit reevaluation. Stable decisions cannot automatically repair earlier mistakes.

## Related ADRs

```text
[ADR-0002: Preserve evidence scopes and review decisions]
      +-- Depends on --> [ADR-0001: Direct original-source research with agents] - Retains agent-directed discovery and Python-owned evidence and publication checks.
```
