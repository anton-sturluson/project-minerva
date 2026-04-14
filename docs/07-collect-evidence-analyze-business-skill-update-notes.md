# Skill update notes for `collect-evidence` and `analyze-business`

Date: 2026-04-09
Status: Draft for review

## Goal

Update Charlie’s OpenClaw skills so they reflect the Minerva CLI workflow that now exists, instead of the older generic folder-first workflow.

The biggest change is simple:
- `collect-evidence` should use Minerva CLI as the default operating backbone
- `minerva research` should be the default deep-search tool for open-web discovery beyond SEC sources
- `web_search` should be treated as a lighter, shallower search layer
- the browser skill should be an escalation path when page interaction, attachment download, login state, or page fidelity matters
- `analyze-business` should sit on top of `collect-evidence` and focus on business judgment, not collection mechanics

## Current mismatch

The current OpenClaw skills are directionally right, but stale in a few important ways:

1. `collect-evidence` still teaches the old generic layout:
   - `00-notes/`
   - `01-data/00-sources/01-reference/02-structured/`
   - `02-research/`

2. `analyze-business` still assumes an older numbered workflow tree and carries too much manual orchestration in the skill body.

3. Neither skill currently treats the Minerva CLI as the primary workflow engine.

4. Neither skill currently reflects that `minerva research` now exists and should be the main deep-search path for non-SEC discovery.

## Design principle

Use the CLI for deterministic workflow state, file layout, and repeatable collection.

Use search and browser tools to fill what the CLI does not natively collect.

Optimize evidence collection for recall, not for minimal sufficiency. Collect a little more than the evidence-collecting agent thinks is enough, especially once the core buckets are already covered.

Keep the boundary clean:
- `collect-evidence` builds and verifies the evidence base
- `analyze-business` evaluates whether the evidence is sufficient, builds judgment from it, and writes the deep dive

## Principle-led rewrite

The skills will read better if they are built around a few strong principles, with the operational details supporting those principles instead of competing with them.

## `collect-evidence` principles

### 1. Optimize for comprehensive evidence, not minimum sufficiency

The job is not to stop at the first plausible research set. The job is to build an evidence base that is broad enough and deep enough to support serious judgment.

Supporting details:
- collect a little more than the agent first thinks is enough
- treat coverage thresholds as floors, not finish lines
- prefer differentiated additional sources over repetitive filler
- revisit thin buckets even after the obvious work is done

### 2. Go beyond the company’s own story

A strong evidence base cannot rely mostly on management framing.

Supporting details:
- collect competitor evidence, not just company evidence
- collect ecosystem evidence, not just direct product evidence
- include customers, partners, suppliers, distributors, regulators, and relevant market-structure sources where they matter
- explicitly check for supply-chain dependencies, bottlenecks, bargaining power, and chokepoints

### 3. Prefer durable source quality and preserve local artifacts

Evidence quality matters as much as evidence count.

Supporting details:
- prefer primary and source-of-record material first
- save sources locally whenever possible
- when human review matters, prefer preserving a human-readable artifact too
- register blocked or reference-only items explicitly instead of silently dropping them

### 4. Build a reusable research asset, not a one-off dump

The company folder should become more valuable over time.

Supporting details:
- reuse and extend the existing company root when revisiting a company
- preserve previous work and add new quarters, filings, releases, and external research into the same tree
- refresh inventory, extraction, and coverage instead of rebuilding parallel folders
- leave a handoff that makes the next analysis pass easier

### 5. Surface what is still weak

A strong collection skill should not hide thinness behind activity.

Supporting details:
- separate discovered, downloaded, extracted, and blocked clearly
- report strongest and weakest buckets, not just raw counts
- leave a short gap memo when important evidence is still thin
- say plainly what still threatens analysis quality

## `analyze-business` principles

### 1. Use the checklist as the actual spine of the deep dive

The checklist should not be a ceremonial audit pasted on at the end. It should define what a complete deep dive means.

Supporting details:
- structure the deep dive around the checklist sections
- use the checklist as both workflow and completion standard
- make unsupported or weak sections visible instead of smoothing them over

### 2. Start from readiness, then interpret

Good synthesis starts only after the evidence base is ready enough to support judgment.

Supporting details:
- check `minerva analysis status` before deep synthesis
- use `collect-evidence` again whenever the evidence base is thin, stale, or lopsided
- use bundles first and raw sources where nuance or conflict requires it

### 3. Seek fragility, risk, and failure modes early

The analysis should not merely explain how the business works. It should test how it breaks.

Supporting details:
- look explicitly for permanent-loss scenarios
- investigate leverage, concentration, cyclicality, dependency, and governance risk
- search for bottlenecks, chokepoints, weak links, and hidden assumptions
- make thesis-break conditions explicit

### 4. Be comprehensive about the business system, not just the company

The company is embedded in a system. A serious deep dive should reflect that.

Supporting details:
- treat competitors, substitutes, ecosystem actors, and supply chain as core analytical inputs
- assess bargaining power, channel structure, and market constraints
- test whether the moat is real from outside the company’s own framing

### 5. Use repeated adversarial thinking to resist neat narratives

A single smooth narrative is often a warning sign.

Supporting details:
- use `brainstorm` early to widen the question set
- rerun it after substantive work to challenge emerging conclusions
- rerun it near the end when the thesis feels too neat, too consensus, or too management-framed
- preserve disagreement, alternative framings, and unresolved tensions in the final judgment

### 6. End with an honest audit

A deep dive is not complete until it has been checked for weak evidence, unsupported claims, and false confidence.

Supporting details:
- confirm the checklist is actually fulfilled
- call out thin evidence and single-source claims
- state uncertainties, disconfirming evidence, and falsification conditions
- make the recommendation explicit and monitorable

## Recommended tool hierarchy

### For `collect-evidence`

1. **Minerva evidence CLI first**
   - `minerva evidence init`
   - `minerva evidence collect sec`
   - `minerva evidence register`
   - `minerva evidence inventory`
   - `minerva evidence extract`
   - `minerva evidence coverage`

2. **Minerva deep search second**
   - use `minerva research "..."` for broad, deeper web discovery outside the SEC workflow
   - this should be the default search layer when the task is to find non-SEC sources worth collecting

3. **OpenClaw web tools third**
   - use `web_search` for a quicker, shallower pass or fast spot checks
   - use `web_fetch` to pull readable page content when a normal fetch is enough

4. **Browser skill last**
   - use when the source requires interaction, dynamic rendering, attachment clicks, or careful page inspection
   - use when PDF download, transcript capture, or page-state fidelity matters

### For `analyze-business`

1. `minerva analysis status`
2. `minerva analysis context`
3. targeted reading of analysis bundles
4. targeted extraction questions against those bundles
5. only then fall back to raw sources
6. if evidence is thin or lopsided, route back into `collect-evidence`

## Recommended update for `collect-evidence`

## Core job

Rewrite the skill around this job:

> Build an auditable, on-disk evidence base using Minerva CLI as the default workflow, then use `minerva research`, OpenClaw web tools, and the browser skill to fill missing non-SEC evidence.

## Canonical workflow

```text
check whether the company folder already exists
→ check relevant INDEX.md files and existing evidence state
→ minerva evidence init
→ minerva evidence collect sec
→ minerva evidence inventory
→ minerva evidence coverage
→ run minerva research to expand non-SEC discovery beyond the minimum obvious set
→ use web_search/web_fetch for lighter follow-up when useful
→ use browser when collection requires interaction or page fidelity
→ save or register external sources explicitly
→ minerva evidence register
→ minerva evidence extract
→ rerun inventory + coverage
→ do one more recall pass for adjacent but relevant sources
→ report downloaded / discovered / extracted / blocked separately
```

## What the skill should explicitly teach

### 1. The actual company-root layout

The skill should document the current workflow layout:

```text
reports/00-companies/{nn}-{slug}/
  notes/
  data/
    sources/
    references/
    structured/
    meta/
  research/
  analysis/
  provenance/
```

Short meanings:
- `data/sources/` = locally saved raw sources
- `data/references/` = reference-only, discovered, blocked, or rights-limited items
- `data/structured/` = extraction outputs derived from saved sources
- `data/meta/` = registry, inventory, coverage, and run manifests
- `analysis/` = workflow readiness and context bundles for the business-analysis layer

### 2. The evidence-state model

The skill should keep these states explicit:
- `discovered`
- `downloaded`
- `extracted`
- `blocked`

It should say clearly:
- do not call a source “collected” unless it is saved locally or explicitly registered with a non-downloaded status
- do not treat a search result list as evidence
- do not treat prose notes as inventory truth

### 3. Bucket-driven gap filling

The skill should teach a bucket-by-bucket collection loop, for example:
- SEC annual filings
- SEC quarterly filings
- earnings releases
- financial statements
- investor relations materials
- transcripts
- external research
- competitor evidence
- ecosystem evidence

For each weak bucket:
- use the cheapest reliable discovery tool first
- collect locally when possible
- register explicitly when not possible
- keep blocker notes short and concrete

### 4. A recall rule

The skill should optimize for recall while still preventing pointless drift.

Recommended rule:
- do not stop at the first moment coverage looks adequate
- once the core buckets are covered, collect a little more than seems necessary
- prefer extra relevant evidence over premature closure
- stop only when additional search is clearly repetitive, low-yield, off-scope, or blocked
- always separate discovered, downloaded, extracted, and blocked counts in the final status

### 5. Collection quality bar

A good `collect-evidence` run should leave behind:
- a reusable company root
- locally saved raw sources
- explicit registry entries for external, blocked, or reference-only items
- structured outputs tied back to saved sources
- updated inventory and coverage artifacts
- evidence that slightly exceeds the bare minimum where practical
- a clear summary of what is still missing

## Brainstorm: how to make `collect-evidence` less shallow

The current rewrite is better than the old skill, but it is still too skeletal. Here are the most useful ways to deepen it.

### 1. Teach collection as a layered evidence build, not just a command chain

The skill should say that a serious evidence base usually has layers:
- company primary sources
- financial statements and filings
- earnings materials and management commentary
- investor relations artifacts such as decks, letters, and event transcripts
- customer, partner, supplier, regulator, and market-structure evidence
- competitor evidence
- ecosystem evidence
- external research and third-party framing

This makes the skill feel like a real research system rather than a short CLI wrapper.

### 2. Make competitor and ecosystem collection part of the collection skill

Right now those ideas are implied, but not operationalized enough.

The skill should explicitly say:
- do not collect only the company’s own story
- collect enough evidence from the most relevant competitors to compare positioning, pricing, growth, margins, and capital allocation
- collect enough ecosystem evidence to understand demand, bargaining power, dependencies, channels, and constraints

That would materially improve downstream `analyze-business` quality.

### 3. Add a source ladder

The skill should teach a source-priority ladder like this:
1. primary company filings and statements
2. company-produced but less formal materials
3. counterparties and ecosystem participants
4. regulators and industry bodies
5. informed external research
6. commodity news coverage

That would help the agent choose better evidence instead of treating every web result as equally useful.

### 4. Make `minerva research` more central in the middle of the workflow

It should not read like a fallback after SEC collection.

A better pattern is:
- collect the deterministic SEC baseline
- run `minerva research` to widen the surface area
- use that output to decide what additional sources should be saved, fetched, or registered
- use browser only when the source actually requires interaction or fidelity

### 5. Add explicit human-readability guidance

The skill should say:
- when a PDF, deck, or filing is important for human review, prefer saving the human-readable artifact too
- markdown and extracted text are good for model work, but not always enough for Anton’s read-through
- when both are available, keeping a machine-friendly and human-friendly form is usually worth it

### 6. Add anti-thinness guidance

The skill should teach that a bucket can be technically present but still analytically weak.

Examples:
- one earnings release is not enough to understand a cadence
- one competitor source is not enough for a real comparison
- a single article does not make an external-research bucket robust

This matters because a formally complete registry can still produce a shallow deep dive.

### 7. Add a gap memo expectation

When coverage is still weak, the skill should leave behind a short gap memo stating:
- which buckets are still thin
- why they matter
- what was tried
- what the next best collection step is

That makes the handoff to `analyze-business` much cleaner.

### 8. Add explicit revisit behavior

The skill should say that when the same company is revisited, the agent should extend the existing evidence base rather than start over.

That means:
- reuse the existing company root
- preserve prior sources
- add the new quarter, new release, or new research to the same tree
- refresh inventory, extraction, and coverage instead of rebuilding parallel folders

### 9. Add a “slightly beyond enough” heuristic by bucket

The current recall language is directionally right, but it would be stronger if it felt operational.

For example:
- if annual filings are covered, try to collect one more adjacent annual or amendment if useful
- if earnings are covered, add a little extra management commentary or transcript evidence
- if external research is covered, add a few more differentiated sources instead of many repetitive ones

### 10. Make the final report from `collect-evidence` more useful

Instead of only reporting counts, the skill should teach the agent to report:
- strongest buckets
- thinnest buckets
- most important missing source types
- what is newly collected versus previously present
- what is likely good enough for analysis versus what still threatens analysis quality

That gives `analyze-business` a much better launch point.

## Recommended update for `analyze-business`

## Core job

Rewrite the skill around this job:

> Use the evidence base produced by `collect-evidence`, validate readiness with Minerva analysis commands, then analyze the business using the context bundles as the default working surface.

## Canonical workflow

```text
check whether the evidence base already exists
→ minerva analysis status
→ if not analysis-ready, call collect-evidence to fill gaps
→ minerva analysis context
→ read context bundles first
→ run brainstorm early to create a first society of thoughts
→ ask targeted questions against bundles
→ inspect raw sources only where needed
→ rerun brainstorm at key inflection points to pressure-test the work
→ write the deep dive
→ run a final audit to confirm the checklist is actually fulfilled
→ state uncertainties, disconfirming evidence, and thesis-break conditions
```

## What the skill should explicitly teach

### 1. Readiness before synthesis

The first question should be:

> Is the evidence base actually ready for business analysis?

The skill should make `minerva analysis status` the gate before the agent starts synthesizing.

### 2. Bundle-first analysis

The default working surface should be:
- `analysis/status.*`
- `analysis/context-manifest.*`
- `analysis/bundles/*.md`

The skill should say:
- start with bundles for speed and consistency
- drop to raw filings, earnings, or external sources when something conflicts, feels thin, or needs nuance

### 3. Clean dependency on `collect-evidence`

The skill should not re-teach collection mechanics in detail.

Instead:
- if evidence is missing, thin, stale, or one-sided, route back to `collect-evidence`
- if evidence is good enough, proceed with analysis

That keeps the contract clean.

### 4. Business judgment belongs here

This skill should own:
- business model understanding
- customer value proposition
- moat and competitive positioning
- industry structure and ecosystem role
- management and incentives
- capital allocation
- financial quality
- risk, fragility, and thesis-break conditions
- valuation versus embedded expectations

It should not spend most of its body on storage layout or collection logistics.

### 5. Competitor and ecosystem work should be analysis-driven

The skill should say:
- use competitor and ecosystem evidence when it changes economics, bargaining power, growth, or risk
- use `minerva research` to identify and deepen the most relevant comparison targets when the evidence base is thin
- route the actual source collection back through `collect-evidence`

### 6. Use `brainstorm` frequently as a society-of-thoughts layer

The skill should explicitly call for repeated use of the `brainstorm` skill, not just a one-off kickoff.

Recommended pattern:
- run `brainstorm` early to widen the question set
- rerun it after the first bundle pass to challenge emerging conclusions
- rerun it again near the end if the thesis still feels too neat, too consensus, or too management-framed

This keeps the analysis adversarial, multi-perspective, and less likely to collapse into a single premature narrative.

### 7. Keep the checklist, but move repetitive detail out of the main skill body

The current long-form checklist is still useful, but it should not dominate the main skill.

Recommended split:
- `SKILL.md` = core workflow, gates, operating rules, and output expectations
- `references/checklist.md` = full company-analysis checklist
- `references/cli-workflow.md` = common command patterns
- `references/section-questions.md` = suggested questions for each analysis bundle

That keeps the skill lean while preserving the full rigor.

## Proposed skill-level wording changes

## `collect-evidence`

Suggested frontmatter direction:

> Collect and organize source material before synthesis using Minerva CLI as the default workflow engine. Use when the next useful step is to initialize or reuse a company evidence tree, collect SEC materials, register external or blocked sources, run extraction and coverage, or fill evidence gaps with `minerva research`, OpenClaw web tools, and browser-assisted collection.

## `analyze-business`

Suggested frontmatter direction:

> Analyze a company or stock and produce a deep-dive report using the evidence base built by `collect-evidence`. Use when the task is to assess whether evidence is sufficient, run `minerva analysis status` and `minerva analysis context`, interpret the business, competition, management, economics, risks, and valuation, and write a judgment-heavy report grounded in saved local evidence.

## Implementation recommendation

Do not just append a few CLI commands to the current skills.

Instead:
1. rewrite each skill around its new primary job
2. strip stale layout references from the main body
3. fold the important checklist and workflow details directly into the main skill files rather than splitting them into separate references
4. make `minerva research` a first-class part of the collection story
5. keep browser as an escalation layer, not the default first step
6. encode the recall bias explicitly in `collect-evidence`
7. encode repeated `brainstorm` use and a final checklist audit explicitly in `analyze-business`
8. make the `analyze-business` checklist the core spine of the deep dive rather than a post-hoc audit appendage

## Net result

If updated well:
- `collect-evidence` becomes a workflow skill that reliably builds an auditable evidence base
- `analyze-business` becomes a judgment skill that starts from deterministic readiness and context bundles
- Minerva CLI handles the repeatable plumbing
- `minerva research` handles deeper open-web discovery
- OpenClaw web tools and browser capability fill the remaining gaps without becoming the whole workflow
