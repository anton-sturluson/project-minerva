# 0001. Direct original-source research with agents

## Status

Accepted

## Context

The weekly ideas workflow found verified originals for only a small share of newsletter leads. Fixed search strings and narrow archive traversal spent the search allowance on irrelevant pages. Valid originals were also rejected when a letter used both a full company name and a shorter name. Increasing the allowance alone would preserve these weaknesses.

The newsletter supplies leads, while published claims must remain grounded in original manager commentary. Existing Postgres state, filesystem evidence and durable publication receipts already support that requirement.

## Decision

Let a Sol coordinator direct parallel Luna research agents, grouped by manager and reporting period. Agents choose searches and follow source links through narrow Python tools. Python owns collection, attribution checks and persisted state. Luna extracts claims from archived originals; a separate Sol call reviews their support. Retain the existing three database tables and filesystem archive, and disclose unresolved coverage in every digest.

Use a feature-local Responses tool loop rather than introducing a general agent framework or changing the OpenClaw session runtime. This keeps tool permissions explicit and lets the scheduled command wait for worker results before publication.

## Consequences

- Researchers can change search strategy, reuse letters and act on rejection feedback.
- Every published claim still needs archived source evidence and support review.
- Research costs and completion times vary; a shared deadline leaves unfinished work resumable.
- Browser access and model judgment remain fallible. Coverage counts describe verified work, not all available investment ideas.
- Agent/tool traces increase local artifact volume, but no new database entities are required.

## Related ADRs

```text
[ADR-0001: Direct original-source research with agents]
      +--> None.
```
