# Research-Evidence Skill Rebuild Plan

**Date:** 2026-04-23  
**Rebuilt:** 2026-04-27  
**Revised after feedback:** 2026-04-28 (second pass)  
**Origin:** Oracle deep-dive session — Anton's feedback on research gaps exposed structural weaknesses in the evidence-collection skill.  
**Scope:** rebuild the `collect-evidence` skill into a stronger `research-evidence` skill and one supporting reference file.

## Why this exists

During the Oracle research build, the evidence base initially looked active but was thin where judgment depended on outside evidence. It started with 38 sources, almost entirely Oracle's own SEC filings, and needed later parallel research to cover competitive landscape, customer/counterparty risk, external coverage, credit context, and structured datasets.

The lesson is not "add more workflow steps." The lesson is that the skill should make the agent ask a better evidence question:

> What evidence would make this company analysis grounded, independently checkable, and hard to fool with management narrative?

The rebuilt skill should behave like a skilled business analyst with strong principles: opinionated about source quality and management-framing risk, deliberate about planning, willing to challenge its own evidence base, and honest in its handoff.

## Alignment with `analyze-business`

The `analyze-business` checklist is the analysis spine: it defines what the final deep dive must answer.

The `research-evidence` dimensions are the evidence lens: they help the agent notice whether the evidence base can support the later analysis.

The relationship stays loose:

```text
analysis questions → relevant evidence dimensions → source plan and audit
```

Do not copy the full analysis checklist into this skill. Do not make the dimensions mandatory steps. Some dimensions matter intensely for one company and barely matter for another.

## What changes from the prior draft

- Collapse all Minerva CLI rows in the tool menu into one row. The Minerva help functions are sufficient guidance.
- Remove obvious built-in tools (`web_search`, `web_fetch`, PDF analysis) from the menu.
- Remove the working-loop section entirely.
- Add an explicit **Primitives** section that names the three core moves the skill exists to encourage: plan from research dimensions, brainstorm with subagents, and iterate.
- Strengthen the principles to reflect how a skilled analyst actually works: triangulation, system-wide investigation, and treating absence of evidence as evidence.
- Reformat research dimensions as a numbered list with a short evidence question and a "look for" line.
- Keep dimension grading guidance only in the reference file.

## Design principle

The skill should answer four questions:

1. What principles define good evidence behavior?
2. What are the core primitives — the three moves the skill must encourage?
3. Which non-obvious tools or orchestration primitives should the agent reach for?
4. What should the handoff/audit make clear?

It should not prescribe a full research recipe. The agent can choose the right path from the evidence state, company complexity, and user request.

## Target files

Create the new canonical skill folder:

```text
/Users/charlie-buffet/.openclaw/workspace/skills/research-evidence/
├── SKILL.md
└── references/
    └── research-dimensions.md
```

Do not create `README.md`, `CHANGELOG.md`, examples, scripts, or assets.

Do not copy the old `references/deep-dive-checklist.md` into the new skill. Its useful evidence-side content reduces into `research-dimensions.md`; the analysis-checklist framing should not come along for the ride.

## Proposed `SKILL.md` structure

`SKILL.md` should contain:

1. frontmatter
2. short purpose statement
3. principles
4. primitives (plan from dimensions, brainstorm with subagents, iterate)
5. compact tool menu
6. handoff/audit expectation

It should not contain:

- a working loop
- a research-moves taxonomy
- the full research-dimension list
- repeated grading language that already lives in the reference
- per-subcommand Minerva rows in the tool menu

## Exact file creation commands

Use this as the implementation spec.

````bash
mkdir -p /Users/charlie-buffet/.openclaw/workspace/skills/research-evidence/references

cat > /Users/charlie-buffet/.openclaw/workspace/skills/research-evidence/SKILL.md <<'EOF'
---
name: research-evidence
description: Build, plan, collect, and audit durable company evidence bases before business analysis. Use when initializing or reusing a company evidence tree, collecting SEC and external sources, planning evidence work from relevant research dimensions, saving or registering evidence, running brainstorm with subagents to challenge the evidence base, building source-grounded datasets, or filling research gaps before synthesis.
---

# research-evidence

Build the evidence base for serious company analysis.

The job is durable, verifiable evidence: saved sources, clear provenance, useful structured data when needed, and an honest audit of what is strong, thin, missing, low-quality, or blocked.

## Principles

### 1. Work backward from the analysis question

Evidence collection serves the analysis that follows. Use `references/research-dimensions.md` as a lens for deciding what evidence matters, not as a checklist to march through.

### 2. Source quality beats source count

A pile of weak sources is not a strong evidence base. Prefer primary sources, official statistics, regulator data, company filings, counterparty materials, reputable industry sources, and clearly sourced expert analysis. Be especially strict on industry and market data: unsourced TAM claims, SEO pages, content farms, generic market-size snippets, and circularly cited consultant summaries are weak evidence.

### 3. Test management narrative against outside reality

Company materials are a baseline, not a conclusion. Test claims that matter against competitors, customers, suppliers, counterparties, regulators, industry structure, and independent external views.

### 4. Investigate the whole system, not just the company

A company's economics live inside a system. Map competitors by segment, ecosystem actors, customer concentration, supplier dependence, channel structure, bargaining power, and regulatory exposure where they materially affect the analysis.

### 5. Triangulate the claims that drive judgment

Single-source claims are fragile. For claims that move the conclusion, seek at least one independent corroborating or disconfirming source before relying on them.

### 6. Absence of evidence is itself evidence

What management does not disclose, what peers do not match, what no third party can verify — these are signals. Record them rather than skipping past them.

### 7. Evidence must survive the session

Important evidence should be saved, registered, or otherwise made durable. Another agent should be able to verify important claims without relying on chat history.

### 8. Weak evidence stays visibly weak

If a dimension is thin, missing, blocked, or supported only by low-quality sources, say so plainly. Do not launder weak evidence into confidence because the folder looks busy.

## Primitives

The skill exists to encourage three core moves. Use them deliberately, not as ritual.

### 1. Plan from research dimensions

Before serious collection, read `references/research-dimensions.md` and decide:

- which dimensions matter most for this company
- what evidence would actually change the analysis
- which competitors, customers, suppliers, and ecosystem actors must be mapped
- which high-quality source types are likely to close the biggest gaps
- where management framing or low-quality market data is the main risk
- what should be split across subagents

For deep dives, write the plan into the company tree before collecting. Naming the plan is half the work.

### 2. Brainstorm with subagents

Once there is enough evidence to be challenged, deploy `brainstorm` subagents to attack the evidence base, not the thesis. Subagents should read the actual evidence base, not a summary, and surface:

- missing dimensions and missing actors
- weak grounding and single-source claims
- overreliance on management framing
- untested customer, competitor, supplier, or counterparty claims
- disconfirming evidence the agent has not yet looked for
- where the evidence quietly assumes the conclusion

Treat their critique as input to the next plan, not decoration on the current one.

### 3. Iterate

The first plan is a hypothesis. The expected rhythm is:

```text
plan → collect → brainstorm → revise plan → collect again
```

Stop when remaining gaps are immaterial, repetitive, genuinely blocked, or clearly disclosed in the handoff. Do not stop because the folder looks busy. New evidence, weak grounding, or brainstorm critique should reshape the plan rather than be filed as trivia.

## Tool menu

Use the tool that fits the evidence gap. For exact subcommands and flags inside Minerva, use the command's own help (`minerva --help`, `minerva <subcommand> --help`).

| Tool | Use when |
| --- | --- |
| `minerva` | Most evidence work: company evidence trees and ledger, SEC pulls, deep web research, extraction from saved sources, file inspection. |
| Browser | Investigate dynamic, logged-in, visually complex, or hard-to-capture sources. |
| `brainstorm` | Pressure-test breadth, depth, blind spots, management-framing risk, and missing disconfirming evidence. |
| Subagents | Run independent collection, extraction, or adversarial review across dimensions, peers, or source sets in parallel. |

## Handoff

End with a compact handoff that makes the next analysis pass easier:

- active company root
- important sources or datasets added
- strongest evidence areas
- thin, missing, low-quality, or blocked areas
- brainstorm findings that changed the plan, if brainstorm was used
- weakly grounded claims that should not be overstated
- recommended next collection step, if any
- readiness judgment for serious analysis

Do not hide uncertainty behind activity. If evidence quality is weak, say so plainly.
EOF

cat > /Users/charlie-buffet/.openclaw/workspace/skills/research-evidence/references/research-dimensions.md <<'EOF'
# Research dimensions

A flexible lens for planning and auditing a company evidence base.

These are not workflow steps. They are not a promise that every company needs the same evidence. Use judgment; ignore or down-rank dimensions that are immaterial to the company or task.

When a deep dive or thin evidence base needs an explicit audit, grade only the relevant dimensions:

```text
strong / adequate / thin / missing / blocked
```

Grades reflect source quality, decision relevance, and remaining uncertainty — not source count.

## The dimensions

1. **Evidence readiness and provenance.** Can important claims be verified from durable sources? Look for: evidence ledger, saved files, URL-only and blocked records, source dates, source-quality notes, prior audits.

2. **Business model, revenue, and demand.** Do we understand what the company does, how it makes money, and why customers buy? Look for: filings, revenue disclosures, segment data, pricing pages, product docs, customer materials, earnings transcripts, demand indicators.

3. **Industry, competition, and ecosystem.** Is the company understood inside its real competitive and ecosystem context? Look for: competitor mapping by segment, peer filings, market share, positioning, pricing, substitutes, channel structure, bargaining power, ecosystem actors.

4. **Management, incentives, and capital allocation.** Are incentives, governance, and capital allocation grounded in evidence? Look for: proxies, compensation design, insider ownership and trades, board structure, dilution, M&A, buybacks, dividends, reinvestment record.

5. **Financial quality.** Are the key financial claims reconciled and economically meaningful? Look for: financial statements, segment economics, margins, cash generation, working capital, returns, balance-sheet resilience, structured tables.

6. **Risk and fragility.** Do we have evidence for the main permanent-loss and thesis-break risks? Look for: leverage, concentration, cyclicality, customer/counterparty exposure, supplier dependence, regulation, litigation, geopolitics, operational risks, historical failure cases.

7. **Change and optionality.** Are growth, change, and optionality grounded rather than promotional? Look for: adoption data, product evidence, mix shift, operating leverage, strategic changes, real-options evidence.

8. **Valuation and expectations inputs.** Do we have the inputs needed to reason about expectations, scenarios, and opportunity cost? Look for: peer comps, historical multiples, consensus estimates, scenario drivers, unit economics, margin and FCF trajectories, discount-rate context.

9. **Recommendation evidence and monitorables.** Can the later recommendation be explicit, falsifiable, and monitorable? Look for: thesis evidence, disconfirming evidence, falsification conditions, leading indicators, key variables to monitor, single-source claims needing caution.

10. **Adversarial breadth check.** Has anyone challenged the evidence base before analysis hardens into a neat story? Look for: brainstorm outputs, alternative frames, bear cases, missing-evidence lists, management-framing warnings, unresolved tensions.

## Source quality bar for industry and market data

Keep this bar high. Prefer official statistics, regulator data, trade associations with disclosed methodology, reputable industry research, company and competitor disclosures, and well-sourced expert work. Treat unsourced TAM claims, SEO summaries, content farms, and circularly cited consultant snippets as weak evidence. If only low-quality market data exists, say so rather than upgrading the dimension by source count.
EOF
````

## Migration plan

1. Create the new `research-evidence` folder and files exactly as above.
2. Confirm OpenClaw loads the new skill.
3. Update local references from `collect-evidence` to `research-evidence` only after the new skill loads correctly.
4. Keep the old `collect-evidence` skill until the new one passes a small smoke test.
5. Archive or remove the old folder only with explicit approval.

Smoke test:

- Pick an existing company evidence tree.
- Use the new skill to plan from the research dimensions before collecting.
- Run `brainstorm` with subagents against the existing evidence base and use the critique to revise the plan.
- Collect or inspect enough evidence to improve at least one weak area.
- Confirm the handoff distinguishes strong evidence from thin, missing, blocked, and low-quality evidence.

## Acceptance criteria

The rebuild is good enough if:

- `SKILL.md` reads like a strong analyst's working principles, not a procedural manual.
- The principles include source quality, management-framing risk, system-wide investigation, triangulation, and absence-as-evidence.
- The Primitives section names exactly three moves: plan from research dimensions, brainstorm with subagents, and iterate.
- The tool menu has exactly one Minerva row plus browser, brainstorm, and subagents.
- Obvious built-in tools are not in the tool menu.
- There is no working-loop section.
- Research-dimension grading guidance appears only in `research-dimensions.md`.
- `research-dimensions.md` presents the dimensions as a numbered list with an evidence question and a "look for" line each.
- Industry/market data has an explicit high-quality-source standard.
- The handoff emphasizes evidence quality, brainstorm findings where relevant, and remaining uncertainty — not source counts.
