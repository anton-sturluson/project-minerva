---
name: learn
description: "Ingest knowledge from URLs or files into hard-disk/knowledge/ with epistemological rigor. Filters noise, enforces citations, and maintains topic indexes."
user_invocable: true
argument: "<url-or-file-path> [learning-objective]"
---

# Learn — Knowledge Ingestion Skill

Ingest and curate knowledge from external sources into `hard-disk/knowledge/` with rigorous filtering. Not a fact-dumping tool — every extraction must pass an insight filter before storage.

## Workflow

### Step 1: Define learning objective

Before fetching anything, articulate a concrete learning objective. "Learn this article" is insufficient.

Good: "Build a reusable reference for SaaS valuation norms to benchmark future company analyses."
Bad: "Learn about SaaS."

If the user provides only a URL/path without an objective, ask them to state one. Infer a reasonable default only if the source context makes the purpose obvious.

### Step 2: Fetch content

- **URLs**: Use `WebFetch` to retrieve the content.
- **Local files**: Use `Read` to load the file.
- **Failure policy**: If the URL is inaccessible (paywall, 404, rate-limited), ask the user to paste the content or provide an alternative source. Do NOT proceed with partial or summarized content.

### Step 3: Classify source quality

Label the source as one of:

| Classification | Definition | Example |
|---|---|---|
| **Primary** | Original data producer | SEC filing, company earnings release, proprietary dataset |
| **Secondary** | Aggregates/analyzes primary data | Analyst newsletter, research report, industry survey |
| **Opinion** | Author's interpretation without novel data | Blog post, editorial, prediction piece |

**Rule**: Numeric claims from Secondary or Opinion sources must be flagged as `⚠️ single-source` in the knowledge file unless cross-verified against a primary source during ingestion.

### Step 4: Scan existing knowledge

Read existing files in `hard-disk/knowledge/` — not just list folder names. For each candidate claim from the source, classify as:

- **New** — no existing coverage in the knowledge base
- **Updates existing** — supersedes or adds to a current file (update that file; don't create a duplicate)
- **Already known** — skip entirely

### Step 5: Apply the insight filter

Every candidate extraction must pass **at least one** of these criteria:

1. **Changes a decision** — would you do something differently knowing this?
2. **Contradicts prior assumptions** — challenges existing knowledge in the base
3. **Provides a reusable mechanism** — framework, formula, or mental model (not just a datapoint)
4. **Has clear boundary conditions** — "works when X, fails when Y"
5. **Is falsifiable** — can be tested or measured later
6. **Generalizes** — applies across companies, sectors, or time periods

Claims that fail all six are noise — do not store them. Explicitly list what was excluded and why.

### Step 6: Present extraction plan to user

Before writing any files, present a summary for approval:

```
## Extraction Plan

**Learning objective**: [stated objective]
**Source**: [title] by [author] — Classification: [Primary/Secondary/Opinion]

### Proposed knowledge files

| # | Action | Path | Content summary | Time horizon | Insight filter criteria |
|---|--------|------|-----------------|-------------|----------------------|
| 1 | NEW | 00-saas/valuation-multiples.md | ... | point-in-time (Dec 2025) | Changes decisions, generalizes |
| 2 | UPDATE | 00-saas/operating-benchmarks.md | ... | point-in-time (Dec 2025) | Changes decisions |

### Conflicts with existing knowledge
[List any contradictions — store both sides with confidence notes]

### Deliberately excluded (failed insight filter)
- [Item] — [reason it fails all six criteria]
```

Wait for user approval before proceeding. If the user requests changes, revise the plan.

### Step 7: Write knowledge files + sync indexes

Write all approved files, then:

1. **Update topic index** in both `CLAUDE.md` and `AGENTS.md` if new topic folders were created
2. **Run acceptance gate** (below) on every file before finishing

## Knowledge file format

Every file must follow this structure:

```markdown
---
title: "Descriptive Title"
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [tag1, tag2]
---

# Title

[Body content with inline citations per Citation Standard in CLAUDE.md]

Numeric claims from non-primary sources: ⚠️ single-source — verify via [suggested verification method]

## References

- [Source Title](url) — what was sourced from this reference
```

Tag each fact contextually as `evergreen` (frameworks, formulas, definitions) or `point-in-time (as-of YYYY-MM-DD)` (market data, benchmarks, snapshots).

## Acceptance gate

Before finishing, verify every written file passes ALL of these:

- [ ] YAML frontmatter with `title`, `created`, `updated`, `tags`
- [ ] Every factual claim has an inline citation
- [ ] Numeric claims from non-primary sources flagged `⚠️ single-source`
- [ ] Ends with `## References` section
- [ ] No subject overlap with existing knowledge files (updated instead of duplicated)
- [ ] Each fact tagged `evergreen` or `point-in-time` in context
- [ ] Topic index in both `CLAUDE.md` and `AGENTS.md` is current

Report the checklist result to the user when done.
