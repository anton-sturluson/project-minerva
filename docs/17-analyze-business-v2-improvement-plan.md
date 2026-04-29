# analyze-business v2 — Improvement Plan

**Date:** April 29, 2026
**Based on:** Oracle deep-dive v1 session trace (`docs/analysis/03-oracle-deep-dive-v1-session-trace.md`)
**Skill file:** `~/.openclaw/workspace/skills/analyze-business/SKILL.md`
**Checklist:** `~/.openclaw/workspace/skills/analyze-business/references/deep-dive-checklist.md`

---

## Problem statement

The Oracle deep dive v1 was produced in a single-pass pipeline: read skill → read evidence → think → write 35K chars → post. No iteration, no plan artifact, no brainstorm against the analysis, and no inline citations. The skill's principles described an iterative, brainstorm-checked, evidence-cited workflow, but the execution protocol was too loose to enforce it. The agent satisfied the letter of each principle with the minimum viable interpretation and moved on.

---

## Issues and proposed fixes

### 1. Non-iterative workflow

**What happened:** The agent read all 17 evidence files sequentially, formed a judgment in one `think` call, and wrote the entire 35,838-char report in a single `write` call. No draft-review-revise cycle. No section-level quality checks. No going back to fill gaps after writing.

**Root cause:** The skill's Planning section says "orient" but doesn't prescribe any iteration after writing begins. There's no checkpoint between "I have enough evidence" and "here is the finished report."

**Fix — describe a natural workflow with iteration, not a rigid pipeline:**

The skill should describe the work as three natural stages — plan, draft, strengthen — where brainstorm is used iteratively throughout rather than as a one-shot gate. The agent decides when to move between stages based on judgment, not a rigid checklist of gates.

The key shift: writing the report is the middle of the work, not the end. After a draft exists, the agent uses `brainstorm` to challenge it, revises, and loops until it's satisfied with the quality. Brainstorm can also be used to verify that all checklist items have been adequately addressed before finalizing.

Guard against rigidity: the phases are a natural rhythm, not a state machine. If the agent realizes during drafting that a section needs more evidence, it goes and gets it. If brainstorm raises a point that requires restructuring, the agent restructures. The skill should encourage this fluidity rather than prescribing exact steps.

### 2. Brainstorm misuse — conflated evidence brainstorm with analysis brainstorm

**What happened:** The agent found a prior brainstorm summary from evidence collection and concluded: "brainstorm was used at least once — this condition was met." It ran zero brainstorm calls during the deep dive itself.

**Root cause:** The skill says "brainstorm was used at least once to challenge the thesis" but doesn't distinguish between an evidence-phase brainstorm and an analysis-phase brainstorm. The agent conflated the two.

**Fix — make brainstorm role explicit and iterative during analysis:**

The skill should specify:

- Prior brainstorms from evidence collection do not satisfy the analysis brainstorm requirement. They are different tools for different stages.
- The analysis-phase brainstorm must be run after a draft or key judgments exist — its input is the analysis itself, not the evidence inventory.
- Brainstorm is iterative: run it, assess the feedback, revise, and run again if the revisions raise new questions or the agent isn't confident the analysis is strong enough. Loop until satisfied.
- Use brainstorm as the final checklist verification too — send the near-final draft to brainstorm and ask whether the checklist items have been adequately addressed and where the analysis is still thin.
- The `brainstorm` skill handles its own execution mechanics (subagent spawning, model selection, synthesis). The analyze-business skill just describes when and why to invoke it.

### 3. Report standard and completion standard are redundant

**What happened:** Both sections say "every checklist item must be addressed." The report standard is about writing quality; the completion standard is about acceptance criteria. But the overlap muddled the signal, and the agent treated them as a single requirement.

**Fix — merge into a single Completion section with two clear sub-parts:**

Combine "Report standard" and "Completion standard" into one section called "Completion" with a quality bar (prose/style expectations) and acceptance gates (binary requirements that must all be true before the work is done).

### 4. No plan artifact — planning was ephemeral

**What happened:** All planning happened inside `think` blocks — ephemeral, non-reviewable, non-auditable. The agent jumped from a mental assessment straight to writing 35K chars.

**Fix — require a plan file before writing begins:**

The skill should require writing a plan to `plans/{NN}-plan-{company}-deep-dive.md` inside the company's evidence tree. The plan maps evidence to checklist sections, names gaps and how they'll be handled, and outlines the intended analysis structure. The agent writes the plan and continues autonomously — no pause for human review. The plan's value is as a forcing function for deliberate thinking before committing to the full draft, and as an auditable artifact after the fact.

### 5. Missing inline citations

**What happened:** The 35,838-char report contained no inline citations to specific evidence sources. The skill's Principle 5 says "Claims that drive the recommendation must trace back to specific zettels" but the agent didn't link claims to sources.

**Root cause:** Citation instructions were abstract ("trace back to specific zettels"). No concrete format, no examples, no enforcement.

**Fix — prescribe citation format as filename hyperlinks:**

Every load-bearing claim must include an inline citation as a hyperlink to the source file. Format: `([filename](relative-path))` — short filenames (evidence ledger IDs, wiki page names, SEC filing identifiers), not long titles. Minor texture, widely known facts, and clearly-labeled speculation don't require citation. The test: if a skeptical reader said "where does that come from?" the answer must be one click away.

Examples:

- `Oracle's incremental ROIC has fallen to roughly 2% on new capital ([oracle-roic-analysis.md](../data/structured/oracle-roic-analysis.md))`
- `Moody's flagged counterparty concentration risk in the $300B backlog ([oracle-credit-analysis.md](../data/references/oracle-credit-analysis.md))`
- `Management guided 20% cloud revenue growth through FY2028 ([Q3-FY2026-10Q.md](../data/sec/Q3-FY2026-10Q.md))`

---

## Exact changes to skill files

### File 1: `skills/analyze-business/SKILL.md`

Replace the entire file with the following:

---

```
---
name: analyze-business
description: Analyze a company or stock and produce a deep-dive report using the wiki as the primary evidence surface. Use when the task is to assess evidence readiness, pressure-test the work with brainstorm passes, and write a judgment-heavy report with the checklist as the core spine. Routes evidence gaps through `research-evidence` → `zettel-wiki` ingest.
---
```

# analyze-business

Turn wiki evidence into an investment judgment the reader can audit and act on.

The wiki is the primary evidence surface. When evidence has material gaps, route them to `research-evidence` and resume from the enriched wiki. When analysis produces durable insights, compound them back into the wiki through `zettel-wiki`. Use `brainstorm` to pressure-test the thesis — iteratively, until the analysis is strong enough.

## Workflow

The work moves through three natural stages. These are not rigid gates — if drafting reveals an evidence gap, go fill it; if brainstorm feedback demands restructuring, restructure. Use judgment to move between stages, not a checklist.

### Orient and plan

Read the company's wiki pages and zettels. Compare the evidence state against `references/deep-dive-checklist.md`. Understand what's strong, what's thin, and what's missing.

Write a plan to `plans/{NN}-plan-{company}-deep-dive.md` inside the company's evidence tree. The plan should include:

- Evidence assessment: what's strong, thin, or missing, mapped against checklist sections.
- Proposed report structure: which sections will carry the analysis and which evidence supports each.
- Gap handling: for each gap — fill via `research-evidence`, flag as immaterial, or disclose as unknown.
- Open questions and how to resolve them.

If material evidence gaps exist, route to `research-evidence` to collect sources, then `zettel-wiki` to ingest them into the wiki, before moving to drafting.

### Draft

Write the deep dive, section by section. Use the checklist as the spine but let the structure serve the argument — compress minor items, expand the ones that drive the judgment.

Every load-bearing claim must include an inline citation as a hyperlink to the source file: `([filename](relative-path))`. Use short filenames — evidence ledger IDs, wiki page names, SEC filing identifiers. Minor texture and widely known facts don't need citation. The test: if a skeptical reader said "where does that come from?" — the answer should be one click away.

### Strengthen

After the draft exists, use `brainstorm` to challenge the thesis, judgments, and recommendation. Brainstorm is iterative: run it, assess the feedback, revise, and run again if the revisions raise new questions or the analysis isn't strong enough yet. Loop until satisfied.

Prior brainstorms from evidence collection do not count. The analysis brainstorm challenges the analysis itself — the thesis, the reasoning, the weight given to different evidence — not the evidence inventory.

Use brainstorm as the final verification too: send the near-final draft and ask whether all checklist items are adequately addressed and where the analysis is still thin.

## Principles

These define what a great deep dive looks like. SOUL.md provides the philosophical foundation; these principles are the operational layer specific to running a deep-dive analysis.

### 1. Translate the business into plain language

Where does the money come from, who pays, who gets paid, why, and what keeps them paying. Distinct from how the company markets itself. If the business can't be explained to someone outside the industry in a few sentences, it isn't understood yet.

### 2. Find the few variables that actually drive long-term value

The job is not to summarize everything in the filings. It is to isolate the three to five things that move outcomes over years and spend the analysis's attention proportionally on those. Everything else is texture.

### 3. Use the outside view first

What do businesses with this model, growth profile, capital structure, and competitive position usually do? Start from base rates before accepting the story of why this one is different.

### 4. Take the system seriously, not just the company

Competitors, customers, suppliers, channels, regulators, bargaining power, dependencies. A company's moat is a claim about its position in this system — test it from outside the company's own framing. Cross-company patterns in the wiki are especially valuable here.

### 5. Anchor load-bearing claims in primary evidence

Filings, transcripts, regulator data, independent third-party sources. Management materials are inputs, not conclusions. Claims that drive the recommendation must trace back to specific wiki pages or evidence files — each with its own source, making the evidence chain auditable.

### 6. Resist neat narratives

Real businesses contain ugly truths, contradictions, and friction. If every fact aligns and every flywheel reinforces every other, the work hasn't pressed hard enough. Use `brainstorm` to inject adversarial thinking — early, after the first substantive pass, and before the conclusion.

### 7. End with a monitorable judgment

Thesis in one paragraph. The few variables to watch. The conditions that would disconfirm it. An explicit recommendation. Without these, it isn't analysis — it's description.

## Completion

### Quality bar

The final report must be a well-written, concise, readable investment memo. Not a checklist dump, not a wall of bullets, not a template with blanks filled in. The checklist is the skeleton; the report is the body. Compress minor items, expand the ones that drive the judgment, and let the structure serve the argument rather than the other way around.

### Acceptance gates

The deep dive is not complete until:

- Every checklist item is answered directly, compressed because minor, explicitly marked immaterial with a short reason, or explicitly marked unknown/thin with the evidence gap named.
- The wiki (or evidence tree) was the primary evidence surface, not bypassed for raw bundles or general knowledge.
- Brainstorm was run against the analysis itself (not just evidence collection) and its output was addressed in the revision.
- Load-bearing claims have inline citations as hyperlinks to source files.
- The recommendation is explicit and falsifiable.
- A plan file was written before drafting began.

---

### File 2: `skills/analyze-business/references/deep-dive-checklist.md`

Replace the entire file with the following:

# Deep-Dive Checklist

This checklist defines what the final deep dive must cover. It is not a report template. The report should embody these questions as readable prose.

Every item must be: answered directly, compressed because minor, explicitly marked immaterial, or explicitly marked unknown/thin with the evidence gap named.

## 1. Evidence readiness

- [ ] What evidence exists and what are the strongest and weakest areas?
- [ ] What does the wiki cover: structure notes, zettels, freshness, cross-company patterns?
- [ ] Were material gaps routed to `research-evidence` or explicitly disclosed?

## 2. Business and revenue model

- [ ] What does the company do in plain language?
- [ ] How does it make money: revenue streams, pricing, unit economics?
- [ ] What are the main demand drivers and customer value proposition?
- [ ] What is the real business, distinct from the marketed story?

## 3. Key value drivers

- [ ] What are the 3–5 variables that actually drive long-term value?
- [ ] Is the analysis spending its attention proportionally on those variables?

## 4. Industry, competition, and ecosystem

- [ ] Who are the relevant competitors by business line?
- [ ] What substitutes, adjacent threats, and ecosystem actors matter?
- [ ] What is durable edge versus management framing?
- [ ] What are the bargaining power, dependency, and supply-chain dynamics?
- [ ] Which cross-company wiki patterns apply?

## 5. Outside view and base rates

- [ ] What do businesses with this model and profile usually do?
- [ ] Where does the company claim to be the exception — is that supported?

## 6. Management, incentives, and capital allocation

- [ ] How candid and aligned is management?
- [ ] What is the capital allocation record?
- [ ] What do compensation, insider activity, dilution, and governance imply?

## 7. Financial quality

- [ ] What are the key financials, reconciled from primary sources?
- [ ] How does accounting presentation differ from economic reality?
- [ ] Which important claims are single-source?

## 8. Risk and fragility

- [ ] What are the main drivers of permanent capital loss?
- [ ] Where are leverage, concentration, cyclicality, dependency, and hidden fragility?
- [ ] What breaks the thesis?

## 9. Change and optionality

- [ ] What is core growth versus promotional story?
- [ ] What is real optionality versus narrative excess?

## 10. Valuation and expectations

- [ ] What does the current price likely imply?
- [ ] What are reasonable base, bear, and bull outcomes?
- [ ] Where do business quality and investment quality diverge?

## 11. Recommendation and monitorable judgment

- [ ] What is the thesis in one paragraph?
- [ ] What is the explicit recommendation?
- [ ] What are the top variables to monitor?
- [ ] What evidence would disconfirm the thesis?

## 12. Adversarial checks

- [ ] Did brainstorm challenge the analysis (not just the evidence base)?
- [ ] Was brainstorm used iteratively until the agent was satisfied?
- [ ] Is the narrative too neat — where are the ugly truths?
- [ ] What would an informed skeptic say is missing?

---

## Summary of changes

| File | What changes |
|---|---|
| `skills/analyze-business/SKILL.md` | Replace "Planning" section with three-stage "Workflow" (orient/plan → draft → strengthen). Add iterative brainstorm requirement. Add inline citation format with hyperlink examples. Merge "Report standard" + "Completion standard" into single "Completion" section with quality bar and acceptance gates. Remove redundant completion standard. Add plan-file requirement. Citations and plan-file gates live in acceptance gates only, not the checklist. |
| `skills/analyze-business/references/deep-dive-checklist.md` | Rewrite section 12 "Adversarial checks" to distinguish analysis brainstorm from evidence brainstorm and require iterative use. Remove old sections 13 and 14 (citations, plan) — those are process gates, not deep-dive content, and live in the SKILL.md acceptance gates. |
