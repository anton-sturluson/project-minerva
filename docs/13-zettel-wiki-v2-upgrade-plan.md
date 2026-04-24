# Zettel-Wiki v2 — Upgrade Plan

**Date:** 2026-04-21
**Context:** Post-mortem from v1 test run (see `hard-disk/reports/00-companies/00-ai-media/wiki/TRACE-ANALYSIS.md`)
**Skill location:** `~/.openclaw/skills/zettel-wiki/`

---

## Problems identified in v1

1. **Agent over-indexed on "testing."** Read 4 synthesized notes (823 lines) and ignored ~292 raw source files.
2. **No subagents used.** Entire wiki built in a single sequential session.
3. **Source priority inverted.** Ingested notes (already distilled) instead of raw evidence.
4. **Links pre-planned, never verified.** All links designed in a think step, never read back to check.
5. **No coverage accounting.** No report of what was read vs. skipped.

---

## Config changes

### Subagent limits

| Setting | Current | Proposed | Schema bounds |
|---|---|---|---|
| `maxConcurrent` | 8 | 20 | positive integer, no upper bound |
| `maxChildrenPerAgent` | 5 (default) | 10 | 1–20 |
| `maxSpawnDepth` | 1 (default) | 1 (keep for now) | 1–5 |

`maxSpawnDepth` controls nesting: at 1, subagents cannot spawn their own subagents. At 2, you get the orchestrator pattern (main → orchestrator → workers). Keeping at 1 for now since the main agent can orchestrate waves directly.

Commands:
```
openclaw config set agents.defaults.subagents.maxConcurrent 20
openclaw config set agents.defaults.subagents.maxChildrenPerAgent 10
```

Update the constraint table in `shared/AGENTS.md` to reflect new values.

---

## Skill changes — guiding principles

The v1 skill was too procedural in places. The revision should:
- **Lead with principles, not procedures.** The agent is smart enough to figure out execution. Tell it *what matters*, not *how many files triggers a subagent*.
- **Let the agent decide when and how to use subagents.** No rigid thresholds. The agent assesses scope and chooses its approach.
- **Avoid redundant instructions.** Say things once, in the right place.
- **Keep responsibilities crisp.** Ingest creates (including cross-links). Audit verifies. Maintain evolves. Query reads.

---

## File-by-file changes

### 1. `SKILL.md` — top-level router

**Changes:**
- Four workflows: Ingest → Audit → Query → Maintain
- New principle: *Raw sources first.* Build knowledge from raw evidence. Notes and memos orient; they're not primary sources.
- Model guidance per workflow (Ingest/Query on Opus 4.6, Audit/Maintain on GPT-5.4)
- Audit description:

> Verify ingestion quality: source coverage, link soundness, evidence
> grounding. Runs during and after ingest as a quality gate. Can also
> be triggered manually.

### 2. `references/ingest.md`

**Changes:**

a. *Source priority* — add to "Read and extract":
> Prefer raw evidence over synthesized notes. Raw sources (filings,
> transcripts, product docs, case studies) are primary. Notes and
> memos help orient but build zettels from underlying evidence.

b. *Coverage principle* — replace the rigid "Scale assessment" step with a principle:
> After surveying sources, account for coverage. The goal is to
> process the corpus thoroughly, not selectively. If the scope is
> large, use subagents. State what was processed, what was skipped,
> and why. Unexplained gaps in coverage are a failure mode.

This is a principle, not a workflow step. The agent decides *how* to handle scale — inline, subagents, batches, whatever makes sense. The principle just says: coverage matters, account for it.

c. *Cross-linking is ingest's job* — clarify in Step 5 (Link bidirectionally):
> Cross-linking is the ingest agent's responsibility, including
> connections between zettels created by different subagents. When
> using parallel subagents, the main agent wires cross-batch links
> after subagents complete. The audit agent verifies link quality
> but does not create links.

d. *Coverage report* — add to quality checklist:
> - [ ] Coverage: files surveyed vs. processed vs. skipped (with reasons)

### 3. `references/audit.md` — NEW

Simplified role: **verify, don't create.**

```
# Audit Agent — Zettel-Wiki

You are the audit agent. Your job: verify ingestion quality.
You check, flag, and recommend — you don't create or fix.

## Checks

### 1. Coverage
Were the right sources processed? Flag high-value files that
were skipped without justification.

### 2. Link soundness
Are connections between zettels and pages well-formed?
- Do bidirectional links actually exist in both directions?
- Does every connection include context explaining why?
- Are there obvious missing connections between related zettels?
Flag gaps for the ingest agent to address.

### 3. Evidence grounding
Does every zettel trace back to a raw source?
- Flag zettels citing synthesized notes instead of raw evidence
- Flag unsupported claims (assertions with no source reference)
- Spot-check uncertain claims against cited sources

## Output
Summary with: coverage stats, link issues found, grounding
flags, recommended actions.

## Boundary with Maintain
Audit checks recent ingest quality. Maintain handles wiki-wide
structural health (orphans, staleness, page splits, restructuring).
If you find structural issues, note them but don't fix — that's
Maintain's job.
```

### 4. `references/maintain.md`

**Changes:**
- Add boundary note: *"Audit verifies recent ingest quality. Maintain operates on the whole wiki over time."*
- Scope the "missing cross-domain connections" check to legacy content that pre-dates the audit workflow. For recent ingests, the ingest agent owns cross-linking and audit verifies it.

---

## Responsibility model

```
Ingest: Create zettels from raw sources, build all links
   ↓
Audit: Verify coverage, link soundness, evidence grounding
   ↓ (periodically)
Maintain: Wiki-wide structural health and evolution
   ↓ (on question)
Query: Answer from wiki knowledge
```

**Ingest** creates and links. **Audit** verifies. **Maintain** evolves. **Query** reads.

---

## Files to create/modify

| File | Action |
|---|---|
| `SKILL.md` | Add Audit workflow, raw-sources-first principle |
| `references/ingest.md` | Source priority, coverage principle, cross-link ownership |
| `references/audit.md` | New — verify-only audit agent |
| `references/maintain.md` | Boundary clarification, scope cross-link check |
| `shared/AGENTS.md` | Update subagent constraint table |

---

## Decisions (resolved)

1. **Wiki root:** Fixed — keep hardcoded at the default location.
2. **Model assignments by workflow:**

| Workflow | Model | Rationale |
|---|---|---|
| Ingest | `anthropic/claude-opus-4-6` | Deep extraction needs strong reasoning |
| Audit | `openai/gpt-5.4` | Verification is analytical but less creative |
| Maintain | `openai/gpt-5.4` | Structural checks, same profile as audit |
| Query | `anthropic/claude-opus-4-6` | Synthesis and narrative need strong reasoning |

3. **Config:** Approved. Set `maxConcurrent: 20`, `maxChildrenPerAgent: 10`.

---

## Status

- [x] Plan reviewed and approved by Anton (2026-04-21)
- [x] Config changes applied (`maxConcurrent: 20`, `maxChildrenPerAgent: 10`)
- [x] `SKILL.md` updated (4 workflows, model assignments, raw-sources-first principle)
- [x] `references/ingest.md` updated (source priority, cross-link ownership, coverage checklist)
- [x] `references/audit.md` created (verify-only: coverage, link soundness, grounding)
- [x] `references/maintain.md` updated (boundary clarification, scoped cross-link check)
- [x] `shared/AGENTS.md` constraint table updated (synced to both workspaces)
- [ ] Gateway restart (needed for config to take effect)
- [ ] v2 test run executed
