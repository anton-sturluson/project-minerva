# Zettel-Wiki v3 — Design Document

**Date:** 2026-04-22
**Status:** Approved — ready for implementation
**Context:** Post-mortem of v2 AI-Media test run (trace: `analysis/01-zettel-wiki-v2-trace-analysis.md`)

---

## Principles

These govern the wiki. Everything else follows from them.

### Zettels first, structure emerges

Zettels are extracted from raw evidence without reference to a pre-defined topic list. Structure notes are written _after_ extraction, organizing the natural clusters that emerged. If the evidence warrants a structure that surprises you, that's the method working.

### Zettels are fixed, structure is fluid

A zettel, once written, is a durable record — it captures one thought grounded in one source. Structure notes are living documents that reorganize as new zettels arrive. During ingest, existing structure notes are reviewed to understand the current landscape and identify what new structures should emerge. Structure notes can be split, merged, reorganized, promoted into folders, or retired. (See [Communicating with Zettelkastens](https://zettelkasten.de/introduction/) on organic growth.)

### Raw evidence is primary

Adhere to building zettels from raw evidence — filings, transcripts, product docs, case studies, competitor analyses. Notes, memos, and deep dives are outputs of prior analysis and are not zettel sources. A zettel whose source is a synthesis document is a failure, not an edge case.

### Every connection explains why

Links without context are noise. Every connection between zettels, or between a zettel and a structure note, includes inline prose explaining the relationship. "See also" is never sufficient.

### Audit is a gate, not a suggestion

After every ingest, the agent performs an audit pass — verifying coverage, evidence grounding, and link soundness. Ingest is not complete until audit passes.

### Failed work is retried, not deferred

When a batch fails, retry immediately — smaller batches, different chunking, adjusted approach. Known gaps are not acceptable in a completion report.

### Depth varies naturally

Zettels and structure notes have no word count constraints. Split when unwieldy.

---

## Content types

### Zettel (atomic note)

One thought per file. The smallest unit of knowledge in the wiki.

- **Location:** `zettels/` (flat)
- **ID:** Timestamp (`YYYYMMDDHHmm`)
- **Grounding:** Every zettel traces back to a raw source.
- **Connections:** Bidirectional links to related zettels with explicit "why" context.
- **Tags:** 2–5 `#kebab-case` tags. Entry points, not taxonomy. Evolve organically.
- **Durability:** Fixed once written. May be marked stale or superseded, not rewritten.

### Structure note (wiki page)

A navigable topic article that organizes and narrates a cluster of zettels. Coherent prose, not bullet lists.

- **Location:** `pages/` (nested folders)
- **ID:** Semantic filename (`apple.md`, `gpu-supply-chain.md`)
- **Emergence:** Created when 3+ zettels cluster around a topic. Never pre-planned before extraction.
- **Fluidity:** Living documents — reviewed during every ingest, split when unwieldy, reorganized as knowledge shifts. Structure notes can reference each other.

### Multi-level wiki pages

When a structure note covers distinct sub-topics, it evolves into a wiki folder:

```
pages/apple.md                          ← single page (early)

pages/apple/                            ← wiki folder (after growth)
  ├── apple.md                          ← hub page
  ├── services-transition.md
  └── capital-allocation/               ← nested folder
        ├── capital-allocation.md
        └── buyback-program.md
```

Multi-level nesting is expected. Every folder gets an `INDEX.md`.

---

## What changes from v2

### Skill structure

| v2 (9 files) | v3 (7 files) |
|---|---|
| `SKILL.md` — workflow routing + model assignments | `SKILL.md` — principles + content types + step routing |
| `references/ingest.md` — 8-step recipe | `references/ingest.md` — principle-driven guidance |
| `references/audit.md` — check-only, don't fix | `references/audit.md` — verify AND fix AND evolve (merged with maintain) |
| `references/maintain.md` — separate fix + evolve | _(deleted — merged into audit)_ |
| `references/query.md` — navigation recipe | `references/query.md` — principle-driven guidance |
| `references/zettel-template.md` | `references/zettel-template.md` _(light edit)_ |
| `references/page-template.md` | `references/page-template.md` _(updated)_ |
| `references/schema.md` | `references/schema.md` _(updated)_ |

### How the reference files change

| v2 (rigid) | v3 (principle-driven) |
|---|---|
| "You are the ingest agent" | No agent framing — it's a step |
| Model assignments per workflow | No model assignments |
| Restates content type definitions | References SKILL.md — no redundancy |
| "Step 1 → Step 2 → Step 3" | Organized by concern, not by sequence |
| Quality checklist at the end | No checklist — principles cover it |
| Prescribes exact method | Describes what, why, key decisions, and pitfalls |

### Conceptual changes

| v2 | v3 |
|---|---|
| 4 separate workflows with dedicated models | 3 steps — agent figures out the approach |
| Separate agents per workflow | One agent, fluid switching |
| Soft preference for raw evidence | Hard rule: raw evidence only |
| Structure pre-planned before extraction | "Zettels first, structure emerges" |
| Audit checks but doesn't fix | Audit verifies, fixes, and evolves |
| Maintain as a separate workflow | Merged into audit |
| Single-level wiki pages | Multi-level wiki folders |

---

## Implementation plan

### Phase 1: Rewrite skill

1. Write new `SKILL.md`
2. Rewrite `references/ingest.md`
3. Rewrite `references/audit.md` (merged with maintain)
4. Rewrite `references/query.md`
5. Delete `references/maintain.md`
6. Update `references/page-template.md`
7. Update `references/schema.md`
8. Light-edit `references/zettel-template.md`

### Phase 2: Test run

Controlled ingest on a small evidence set (5–10 source files):
- Verify: zettels created from raw evidence (not synthesis documents)
- Verify: structure notes emerged from zettel clusters (not pre-planned)
- Verify: audit pass happens after ingest
- Verify: all zettels cross-linked with context

---

## Target file contents

These are the actual files that will be written.

### 1. SKILL.md

````
---
name: zettel-wiki
description: >
  Build and maintain an agent-driven knowledge base using the Zettel-Wiki
  pattern — a fusion of Karpathy's LLM Wiki and the Zettelkasten method.
  The wiki is a persistent, compounding hypertext of interlinked markdown
  files: structure notes (wiki pages) for navigable topic articles, and
  Zettels (atomic notes) for individual thoughts and claims.
---

# Zettel-Wiki

Agent-maintained knowledge base. Two content types, seven principles.

Wiki root: `/Users/charlie-buffet/Documents/project-minerva/hard-disk/wiki/`

## Principles

### Zettels first, structure emerges

Zettels are extracted from raw evidence without reference to a
pre-defined topic list. Structure notes are written after extraction,
organizing the natural clusters that emerged. If the evidence warrants
a structure that surprises you, that's the method working.

### Zettels are fixed, structure is fluid

A zettel, once written, is a durable record — one thought grounded
in one source. Structure notes are living documents that reorganize
as new zettels arrive. During ingest, existing structure notes are
reviewed to understand the current landscape and identify what new
structures should emerge. Structure notes can be split, merged,
reorganized, promoted into folders, or retired.

### Raw evidence is primary

Adhere to building zettels from raw evidence — filings, transcripts,
product docs, case studies, competitor analyses. Notes, memos, and
deep dives are outputs of prior analysis and are not zettel sources.
A zettel whose source is a synthesis document is a failure, not an
edge case.

### Every connection explains why

Links without context are noise. Every connection between zettels,
or between a zettel and a structure note, includes inline prose
explaining the relationship. "See also" is never sufficient.
Connections are bidirectional — update both sides.

### Audit is a gate, not a suggestion

After every ingest, verify coverage, evidence grounding, and link
soundness. Fix issues found. Ingest is not complete until audit
passes. This includes structural evolution: fixing orphans,
proposing page splits, creating new structure notes from emergent
zettel clusters.

### Failed work is retried, not deferred

When a batch fails, retry immediately — smaller batches, different
chunking, adjusted approach. Known gaps are not acceptable in a
completion report.

### Depth varies naturally

Zettels and structure notes have no word count constraints. A zettel
can be three sentences or a full page. A structure note can link to
3 zettels or 30. Split when unwieldy.

## Content types

### Zettel (atomic note)

One thought per file. The smallest unit of knowledge.

| Property | Detail |
|---|---|
| Location | `zettels/` (flat) |
| ID | Timestamp: `YYYYMMDDHHmm` |
| Grounding | Every zettel traces back to a raw source |
| Connections | Bidirectional links to related zettels with explicit context |
| Tags | 2–5 `#kebab-case` tags; entry points, not taxonomy |
| Durability | Fixed once written; may be marked stale, not rewritten |

A zettel is not an excerpt. It is processed knowledge — what the
source says and why it matters.

Template: `references/zettel-template.md`

### Structure note (wiki page)

A navigable topic article that organizes a cluster of zettels.
Coherent prose with inline zettel links, not bullet lists.

| Property | Detail |
|---|---|
| Location | `pages/` (nested folders) |
| ID | Semantic filename: `apple.md`, `gpu-supply-chain.md` |
| Emergence | Created when 3+ zettels cluster around a topic |
| Fluidity | Living document — reorganized as knowledge shifts |
| Cross-references | Structure notes can link to each other with context |

Template: `references/page-template.md`

#### Multi-level growth

When a structure note covers distinct sub-topics, it evolves into
a wiki folder. The hub page keeps the original filename inside the
folder. Sub-pages and nested folders are allowed. Every folder gets
an `INDEX.md`.

## How the wiki grows

### Ingest — `references/ingest.md`

Process new sources into wiki knowledge. Creates zettels from raw
evidence, cross-links them, reviews and updates structure notes.

### Audit — `references/audit.md`

Verify quality and evolve structure. Runs after every ingest
(mandatory) and periodically for wiki-wide health.

### Query — `references/query.md`

Answer questions from wiki knowledge. Synthesizes answers with
citations, files new zettels when the answer produces insight.

## Infrastructure

- `INDEX.md` — master catalog in every folder. Auto-maintained.
- `LEDGER.md` — append-only activity log.

Formats: `references/schema.md`
````

### 2. references/ingest.md

````
# Ingest — Zettel-Wiki

Process raw sources into wiki knowledge. See SKILL.md for principles
and content type definitions.

## What ingest accomplishes

New sources become wiki knowledge: zettels extracted from raw
evidence, cross-linked with explicit context, organized into
structure notes, with INDEX and LEDGER updated. Every zettel is
grounded and connected before ingest is considered complete.

## Sources

Sources are files on disk (filings, transcripts, product docs,
case studies), URLs, or conversation content. Never copy source
files into the wiki — reference them via paths or URLs.

Adhere to raw evidence. Filings, transcripts, product docs, and
case studies are valid zettel sources. Notes, memos, and deep
dives are not — they are outputs of prior analysis. If you catch
yourself building a zettel from a synthesis document, stop and
find the underlying raw source.

## Extraction

Read sources and identify discrete atomic insights. For each
candidate, the key decisions:

- **Knowledge or information?** Knowledge is contextualized,
  connected, and answers "why does this matter?" Information is
  a dead fact. Only knowledge becomes a zettel.
- **Can it stand alone?** One thought per zettel. Two distinct
  ideas = two zettels.
- **Already captured?** Check `zettels/INDEX.md`. Same claim with
  new evidence → enrich the existing zettel. Same topic, different
  angle → new zettel linked to the existing one. True duplicate
  → skip.

For batch extraction at scale, spawn subagents with non-overlapping
timestamp namespaces. Each worker gets a batch of source files and
the zettel template. After all workers complete, the main agent
reviews output and wires cross-batch connections — workers can
only link within their own batch. If a worker batch fails, retry
immediately with smaller batches.

## Cross-linking

Every new zettel gets at least one connection with explicit context
explaining why the link exists. Connections are bidirectional —
when linking A → B, update B → A too.

Cross-linking is not optional. Zettels without connections are
orphans and represent incomplete work. All zettels must be linked
before ingest is considered complete.

## Structure notes

After extraction, review what emerged:

- **Existing structure notes:** Read them. Understand the current
  landscape. Update their narratives to incorporate new zettels.
  Bump the `updated` field.
- **New clusters:** When 3+ new zettels cluster around a topic
  that has no structure note, create one. Let the topic emerge
  from the zettels — don't pre-define it.
- **Growth:** When a structure note now covers distinct sub-topics,
  consider evolving it into a wiki folder with sub-pages.

Structure notes are fluid. Reorganize them as needed — the current
structure is not sacred.

## Completing ingest

Update all affected INDEX.md files. Append a LEDGER entry with
source, files created, and files updated.

Then flow into audit. Ingest is not done until audit passes.

## Pitfalls

- Pre-planning structure note topics before extraction. Let
  structure emerge.
- Using notes or deep dives as zettel sources instead of raw
  evidence.
- Accepting batch failures as "known gaps" instead of retrying.
- Cross-linking only a few zettels and deferring the rest.
- Copying source text verbatim instead of processing it into
  knowledge.
````

### 3. references/audit.md

````
# Audit — Zettel-Wiki

Verify wiki quality and evolve wiki structure. See SKILL.md for
principles and content type definitions.

Audit runs after every ingest (mandatory) and periodically or
on request for wiki-wide health.

## What audit accomplishes

Recent ingest verified for quality. Issues found and fixed. Wiki
structure evolved — orphans linked, pages split when unwieldy, new
structure notes created from zettel clusters, redundant zettels
merged. INDEX files consistent. LEDGER updated.

## Quality verification

### Coverage

Were the right sources processed? Compare the source corpus against
what was actually ingested. High-value files (filings, transcripts,
product docs) should not be skipped without reason. Metadata files,
manifests, and download logs are fine to skip.

### Evidence grounding

Does every zettel trace back to a raw source? Flag zettels citing
synthesis documents instead of raw evidence. Spot-check claims
against cited sources when something feels uncertain.

### Link soundness

Are connections bidirectional? Does every connection include context
explaining why? Are there obvious missing connections between
related zettels?

## Structural evolution

### Orphan zettels

Zettels with no inbound links — nothing points to them. Read the
orphan, understand its content, and add connections from the most
relevant structure notes and related zettels. Add the link with
explicit context.

### Context-free links

Links that say "see [ID]" or "related to" without explaining why.
Read both sides, understand the relationship, add a one-sentence
explanation.

### Contradictions

Contradictions are expected — the world has genuine disagreements.
Don't resolve unless one claim is clearly wrong (superseded by a
newer source).

For legitimate contradictions: link the conflicting zettels to each
other, explain what contradicts and how the tension reads, update
any structure notes that reference both.

For clear errors: mark the incorrect zettel as superseded, link to
the correction, update structure notes that relied on the wrong claim.

### Page splits and folder promotion

When a structure note covers clearly distinct sub-topics, propose
evolving it into a wiki folder with sub-pages. The original file
becomes the hub page. Multi-level nesting is expected.

Flag significant restructuring to the user. Fix routine issues
autonomously.

### Zettel clusters without a structure note

Groups of 3+ related zettels that share connections but have no
structure note organizing them. Create a structure note — write
coherent narrative linking to the zettels.

### Redundant zettels

Near-duplicates covering the same ground. Merge into the richer
version. Add any unique evidence from the weaker one. Update all
inbound links to point to the survivor.

### Stale content

Zettels whose claims have been superseded by newer information.
Use judgment — time-bound claims need freshness checks more than
evergreen definitions. Add a staleness note and link to the newer
zettel if one exists.

## Batch operations

For large-scale cross-linking or orphan resolution, spawn subagents.
Give each worker a batch of zettels plus the full zettel catalog for
reference. Workers add connections; the main agent verifies quality
after completion.

## Autonomy vs. flagging

Fix autonomously: orphan links, broken links, missing INDEX entries,
context-free connections, INDEX regeneration, small structure note
updates.

Flag to user: significant page splits, major folder reorganization,
contradictions that require domain judgment, suggestions for sources
to seek out.

## Completing audit

Update all affected INDEX.md files. Append a LEDGER entry
summarizing what was verified, what was fixed, and what was
flagged.

## Pitfalls

- Checking without fixing. Audit both verifies and remediates.
- Silently resolving contradictions instead of linking both sides.
- Skipping audit after ingest because "it looked fine."
- Flagging everything to the user instead of fixing routine issues
  autonomously.
````

### 4. references/query.md

````
# Query — Zettel-Wiki

Answer questions using wiki knowledge. See SKILL.md for principles
and content type definitions.

## What query accomplishes

Questions answered with specific zettel citations. Contradictions
acknowledged. Gaps identified. When the synthesis produces a new
insight not already captured, it is filed as a new zettel —
the wiki compounds.

## Navigation

Start from the top and drill down:

1. Read `wiki/INDEX.md` — the master catalog.
2. Identify relevant structure notes in `pages/`.
3. Read those structure notes. Note the zettels they link to.
4. Read the relevant zettels. Follow their connections to find
   related zettels the structure note didn't reference.
5. Keep following links until the picture is complete.

Structure notes are the best starting point — they organize by
topic and link down to evidence. If a topic has no structure note,
scan `zettels/INDEX.md` for relevant titles or tags. Cross-domain
connections between zettels are often where the most interesting
answers live.

## Synthesis

Compose answers that:

- Cite specific zettels by ID or inline link. Not vague references
  to "the wiki."
- Cite raw sources when evidence traceability matters — follow the
  zettel's Evidence section back to the original document.
- Synthesize across zettels. Connect the dots, explain relationships,
  build arguments — don't just list what each zettel says.
- Acknowledge contradictions when zettels disagree. Present both
  perspectives with the context the wiki provides.
- State gaps clearly. If the wiki doesn't have enough to fully
  answer, say so and suggest what source would fill the gap.

## Compounding

When the synthesis reveals a new insight — a connection, pattern,
or conclusion not already captured in any existing zettel — file it:

- Create a new zettel following the template.
- Link it to the zettels that informed the insight.
- Update reciprocal connections.
- Consider whether it warrants updating or creating a structure note.
- Update INDEX and LEDGER.

Not every answer deserves a new zettel. File only when the insight
is durable and would be valuable for future queries.

## Pitfalls

- Answering from general knowledge instead of wiki content.
- Vague citations ("the wiki suggests...") instead of specific
  zettel references.
- Hiding contradictions instead of presenting both sides.
- Filing trivial or obvious observations as new zettels.
````

### 5. references/page-template.md

````
# Structure Note Template

Use this format for structure notes (wiki pages) in `pages/`.

    ---
    title: "Topic Title"
    created: YYYY-MM-DD
    updated: YYYY-MM-DD
    ---

    # [Title]

    [Coherent narrative that reads like a Wikipedia article.
    Inline links to zettels that back each claim:
    "Apple's services revenue [exceeded hardware](../../zettels/202604160930.md)
    in Q2 2025, marking a structural shift."

    The page organizes and narrates — zettels are the evidence
    underneath. Every factual claim links to the supporting zettel
    or raw source.]

    ## Related

    - [Related Structure Note](path/to/page.md) — [Why this note
      is related — not just "see also" but the specific connection.]

## Rules

- **Semantic filename:** lowercase kebab-case.
- **Reads like a Wikipedia article.** Coherent narrative, not
  bullet lists. Organize by logical sections, not by source.
- **Inline zettel links.** Every factual claim links to the
  zettel that backs it.
- **Related section.** Links to other structure notes with
  context explaining the relationship.
- **Updated field.** Bump `updated` when content changes.
- **Fluidity.** Structure notes are living documents —
  reorganized, split, merged as the wiki evolves.
- **Multi-level growth.** When a page covers distinct sub-topics,
  evolve it into a wiki folder. The original file becomes the hub
  page inside the folder. Sub-pages and nested folders are allowed.
  Every folder gets an INDEX.md.
- **Depth varies naturally.** No word count constraints.
````

### 6. references/schema.md

````
# Zettel-Wiki Schema

Conventions for the wiki at
`/Users/charlie-buffet/Documents/project-minerva/hard-disk/wiki/`.

## Naming

- Structure notes: lowercase kebab-case semantic filenames
  (`apple.md`, `gpu-supply-chain.md`)
- Zettels: timestamp IDs in `YYYYMMDDHHmm` format
  (`202604160930.md`)
- Folders: lowercase kebab-case (`companies/`, `concepts/`)
- Infrastructure files: ALL CAPS (`INDEX.md`, `LEDGER.md`)

## Wiki folders

When a structure note evolves into a folder, the hub page keeps
the same filename inside the folder:
`pages/apple.md` → `pages/apple/apple.md`

Sub-pages use semantic filenames. Nested folders are allowed.
Every folder gets an INDEX.md.

## INDEX.md format

Every folder gets an INDEX.md with a markdown table of
immediate children:

    | Name | Notes |
    |---|---|
    | `apple.md` | Apple — business model, competitive position |
    | `nvidia.md` | NVIDIA — GPU supply, AI infra |

The root INDEX.md is the master entry point.

## LEDGER.md format

Append-only chronological activity log:

    ## [YYYY-MM-DD HH:MM] action | Title

    - **Source**: path or URL
    - **Created**: list of new files
    - **Updated**: list of modified files

## Tag conventions

- Tags use `#kebab-case`: `#platform-economics`, `#apple`
- Tags are entry points, not a taxonomy — don't overthink them
- Tags evolve organically
````

### 7. references/zettel-template.md

````
# Zettel Template

Use this format for new zettels in `zettels/`.

    ---
    id: "YYYYMMDDHHmm"
    title: "Short descriptive title"
    tags: ["#topic-one", "#topic-two"]
    created: YYYY-MM-DD
    source: "path/to/raw/source/file or URL"
    ---

    # [Title]

    [Body: one thought, claim, or insight in your own processed words.
    Not a copy-paste — synthesized, contextualized.
    Answers "why does this matter?" and "how does this connect?"
    Stands alone as a single atomic thought.]

    ## Connections

    → [ID](ID.md) — [Why this connection matters. Not just "related to"
    but the specific nature of the link.]

    ## Related

    - [Structure Note Title](../pages/path/to/page.md)

    ## Evidence

    - [Source Title](path/to/raw/source) — [specific location: page,
      section, paragraph, table]

## Rules

- **One thought per file.** Two ideas = two zettels.
- **Timestamp ID:** `YYYYMMDDHHmm`. If creating multiple in the
  same minute, increment by one minute.
- **Title:** Short, descriptive, standalone.
- **Tags:** 2–5 hashtags. Don't over-tag.
- **Source:** Path to raw source or URL. Omit for conversation
  or synthesis insights.
- **Body:** Processed knowledge. Synthesize, contextualize. Don't
  just excerpt the source.
- **Connections:** Bidirectional. Update both sides. Every
  connection has explicit context explaining why.
- **Related:** Links to structure notes this zettel supports.
- **Evidence:** Specific citations back to raw sources.
````

### File to delete

- `references/maintain.md`

---

## Resolved design decisions

| Question | Decision | Rationale |
|---|---|---|
| Skill structure | 7 files: SKILL.md + 3 step files + 3 reference files | Detailed guidance without rigidity. Principles in SKILL.md, approach in step files, format in templates. |
| Reference file style | Organized by concern, not numbered steps | Guard against rigidity. Describe what/why/decisions/pitfalls, not recipes. |
| Model assignments | None | Agent uses its own model. Workspace conventions handle batch work. |
| Architecture instructions | None in skill | Agent knows from workspace conventions when to parallelize. |
| Audit vs. maintain | Merged into audit | One step for verification + structural evolution. |
| Multi-company parallelism | One company at a time | Simplicity. |
| Cross-page links | Structure notes can reference each other | Useful for navigation. |
| Tag hygiene | Tags evolve organically | Guard against rigidity and redundancy. |
