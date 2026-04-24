# Collect-Evidence → Research-and-Collect Upgrade Plan

**Date:** 2026-04-23
**Origin:** Oracle deep-dive session — Anton's feedback on research gaps exposed structural weaknesses in the collect-evidence skill.

## Context

During the Oracle research build, the evidence base started at 38 sources (almost entirely Oracle's own SEC filings) and required two waves of 14 subagents across multiple rounds of feedback to reach 75 registered sources covering 10 research dimensions. The skill's instructions didn't prevent the initial thin state or guide toward comprehensive research — we had to discover the gaps through conversation.

Key problems:
1. The skill produced a "minimum-viable" evidence base that looked complete by source count but was thin on every non-SEC dimension.
2. Competitive landscape, news, customer intelligence, credit analysis, and structured data were all zero.
3. The research plan had to be built from scratch in real-time instead of being guided by the skill.
4. Multiple rounds of feedback were needed before the research was genuinely comprehensive.

## What changes

### 1. Rename: `collect-evidence` → `research-and-collect`

The name should signal that this is active investigative research, not just document retrieval. "Collect-evidence" sounds like pulling files off a shelf. What we actually do is closer to: map the competitive landscape, investigate counterparty risk, gather industry data, and build analytical datasets.

Update the skill `name` and `description` fields in frontmatter accordingly.

### 2. Add shared reference: `references/deep-dive-checklist.md`

**Already created** at `~/.openclaw/workspace/skills/collect-evidence/references/deep-dive-checklist.md`.

This file contains:
- The full deep-dive checklist (extracted from `analyze-business`)
- 10 research dimensions that map checklist sections → specific evidence collection needs
- Each dimension gets a coverage grade: strong / adequate / thin / missing

Both `collect-evidence` (renamed) and `analyze-business` should reference this shared doc. The collect side reads it to know what evidence to gather. The analyze side reads it to structure the analysis. Same checklist, two uses.

**Action for `analyze-business`:** Replace the inline checklist with a `read` directive pointing to the shared reference. Keep the analysis-specific guidance (workflow, brainstorm timing, etc.) in the analyze skill; move only the checklist definition to the shared file.

### 3. Restructure the workflow into phases

Current workflow is linear and SEC-first. New workflow should be:

```
Phase 0: Audit & plan
  - Check what exists
  - Read the deep-dive checklist
  - Map the competitive landscape (identify competitors by business line)
  - Identify key customers, suppliers, and ecosystem actors
  - Produce a research plan with all 10 dimensions

Phase 1: Deterministic baseline (broadened)
  - SEC filings for the company (10-K, 10-Q, 8-K, proxy, earnings releases)
  - SEC financials (XBRL income, balance, cash flow)
  - Earnings transcripts (all available quarters)
  - Competitor financial filings (income + balance for each competitor)
  - Institutional ownership data (if available programmatically)

Phase 2: Deep research (all dimensions in parallel)
  - Industry & market data (market share, TAM, spending surveys)
  - Customer & demand intelligence (key customer health, buyer surveys)
  - Supply chain & cost structure (supplier dynamics, input costs)
  - Financial & credit (ratings, debt structure, analyst consensus, comps)
  - Management & governance (compensation, insider activity, board)
  - External coverage (news, analyst research, bear/bull theses)
  - Risk-specific evidence (regulatory, counterparty, operational)

  Use browser for thorough search alongside web_search/web_fetch.
  Use minerva research for deep discovery.
  Use subagents for parallel collection across dimensions.

Phase 3: Build structured datasets
  - Key financials summary table
  - Competitive comparison tables
  - Segment/revenue breakdown time series
  - Ratio trends and derived metrics
  - Any other analytical tables the analysis will need

Phase 4: Verify & grade
  - Run inventory
  - Grade each of the 10 research dimensions
  - Any dimension graded "missing" blocks completion
  - Any dimension graded "thin" gets one more targeted pass
  - Produce the handoff report
```

### 4. Add the Research Dimension Framework to SKILL.md

The 10 research dimensions (already in the reference doc) should also appear in SKILL.md as a mandatory checklist the agent works through. The skill should instruct:

- Before starting collection, read `references/deep-dive-checklist.md` to load the full dimension framework
- After collection, grade each dimension explicitly
- Do not declare the evidence base ready if any critical dimension is "missing"

### 5. Add competitive mapping as an explicit early step

The single biggest gap was: we never mapped who the competitors were. The skill should require:

- Early in Phase 0, identify all competitors by business line
- For multi-segment companies, map competitors separately per segment
- Pull financial filings for each competitor in Phase 1
- This is deterministic work that should happen automatically, not as an afterthought

### 6. Add browser-based research emphasis

The current skill mentions browser in passing. The new skill should emphasize:

- Always consider browser-based research for news, paywalled content, and interactive sources
- Browser searches often surface content that `web_search` API misses
- For thorough research, combine `web_search` (fast, broad) with browser (deep, interactive)

### 7. Add parallel execution guidance

The skill should guide on using subagents for parallel research:

- Research dimensions are largely independent — collect them in parallel
- Batch subagents: up to 10 concurrent (per maxChildrenPerAgent)
- Each subagent handles one dimension or a coherent sub-batch
- Verify outputs exist on disk after subagent completion (subagents may report success without saving files)

### 8. Add counterparty/customer research mandate

For any company with material customer concentration:

- Identify the top 3-5 customers or counterparties
- Assess their financial health independently
- For contractual obligations (like Oracle's RPO), verify the counterparty can pay
- This is especially critical for infrastructure/B2B companies with long-term contracts

### 9. Add structured data build as explicit step

The skill should require building derived analytical datasets, not just collecting raw sources:

- Key financials summary (income/balance/cash flow with ratios)
- Competitive comparison tables
- Segment breakdown time series
- Any metric time series the analysis will need
- Store in `data/structured/` with an INDEX.md

### 10. Strengthen completion criteria

Current criteria check source counts. New criteria should check:

- All 10 research dimensions graded
- No critical dimension is "missing"
- At least one structured analytical dataset exists
- Competitor filings collected for identified competitors
- News/external coverage is non-zero
- If counterparty concentration exists, counterparty health is assessed

## File changes summary

| File | Action | Notes |
|------|--------|-------|
| `collect-evidence/SKILL.md` | Rewrite | Rename skill, restructure workflow, add dimension framework, add browser/parallel/counterparty guidance |
| `collect-evidence/references/deep-dive-checklist.md` | Already created | Shared checklist + research dimensions |
| `analyze-business/SKILL.md` | Update | Replace inline checklist with read directive to shared reference; keep analysis workflow intact |
| Skill folder rename | `collect-evidence/` → `research-and-collect/` | Rename the directory |

## Migration notes

- The existing `collect-evidence` skill is referenced in `AGENTS.md` (both local and shared) — update references after rename
- The `analyze-business` skill references `collect-evidence` by name in its workflow — update to new name
- Minerva CLI commands don't change — only the skill instructions change
- Existing company evidence trees are unaffected — the skill operates on the same folder structure

## Open questions

1. Should the shared checklist live in the `collect-evidence` (or renamed) skill's references, or in a shared location like `~/.openclaw/skills/` that both skills can access?
2. Should the research dimension grades be persisted as a file in the evidence tree (e.g., `data/meta/dimension-grades.md`)?
3. Should `minerva evidence` CLI be extended to support dimension-level coverage checking, or is this purely an agent-side concern?
