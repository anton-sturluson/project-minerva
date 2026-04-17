# Zettel-Wiki: Design Synthesis

## What this document is

A working design for a skill that merges Karpathy's LLM Wiki pattern with the Zettelkasten method. The goal: an agent-maintained, compounding knowledge base built from markdown files — a personal Wikipedia where the agent does all the writing and bookkeeping, and the human directs.

*v6 — Simplified: no type/subtype fields, added topic tags, stripped model-specific machinery.*

---

## The Two Source Concepts (Summary)

### Karpathy's LLM Wiki

Instead of re-deriving knowledge from raw documents on every query (the RAG pattern), the LLM incrementally builds and maintains a persistent wiki — interlinked markdown files that sit between the user and raw sources. Knowledge is compiled once and kept current.

Three layers: raw sources (immutable ground truth) → wiki (LLM-generated synthesis) → schema (conventions and workflows).

Three workflows: **ingest** (process a source, update pages across the wiki), **query** (answer questions with citations to wiki pages), **lint** (periodic health checks for contradictions, orphans, staleness).

Key insight: Personal wikis die because maintenance burden exceeds human willpower. LLMs eliminate that bottleneck.

### The Zettelkasten Method

A personal thinking tool structured as a hypertext — a web of thoughts, not a collection of notes. Three pillars: hypertextual (notes link to each other), atomic (one thought per note — the "Zettel"), personal.

Every connection must have explicit context — *why* the link exists. The "why" is itself created knowledge. Links without explanation are noise.

Structure notes sit above atomic Zettels as hierarchical entry points — doorways into clusters of related thoughts.

Key insight: The system scales organically. Knowledge compounds rather than bloating.

---

## The Merged Design

### Core Architecture

The key realization: *Structure notes are Wikipedia pages. Zettels are the atomic building blocks underneath them.*

Two layers of authored content:

| Layer | What it is | Examples |
|---|---|---|
| **Wiki pages** (structure notes) | Hierarchical topic pages that organize and narrate. Varying depth — the tree grows as the domain demands. | `companies/apple.md`, `concepts/zettelkasten.md`, `domains/ai-infra/gpu-supply-chain.md` |
| **Zettels** (atomic notes) | One thought per file. Timestamp-ID'd. Tagged with topic hashtags for discovery. | `202604160930.md` — "Apple services > hardware in Q2 2025"; `202604160945.md` — "Platform economics" |

Wiki pages link down to Zettels. Zettels link to each other and back up to wiki pages. The whole thing forms a navigable hypertext — enter via a topic page and drill into atomic claims, or surface from a Zettel up to broader context.

The hierarchy uses *folders and nested folders* with `INDEX.md` files — the same indexing protocol we already use across the hard-disk. Depth is not fixed — the tree grows organically as knowledge accumulates.

### Agents & Workflows

The wiki is operated by three specialized subagents, orchestrated by the main agent (Charlie/Steve).

#### Ingest Agent

Processes raw sources into wiki knowledge.

- Identifies a source — could be a file anywhere on disk, a URL, or content from conversation. Sources are *not* copied into the wiki — they stay where they live.
- Uses `minerva extract` for reading large-context sources. Can use large models (gpt-5.4) for complex reasoning or small models for simple extraction — picks the right tool for the source complexity.
- Extracts atomic insights → creates individual Zettels in `zettels/` using the skill's template (`references/zettel-template.md`), each with one thought, timestamp ID, and topic tags for discovery.
- For each new Zettel, searches existing Zettels (via INDEX files) for related content. If a clearly duplicate Zettel exists, enriches the existing one (adds to its "Related" section) instead of creating a new file. Otherwise creates bidirectional links *with explicit context*.
- Updates or creates relevant wiki pages in `pages/`.
- Updates all affected `INDEX.md` files and appends to `LEDGER.md`.

*Why ingest handles linking (not query):* The ingest agent needs to understand the wiki well enough to place Zettels correctly — searching for related content is inherent to that job. The "find related" step during ingest is a targeted check against the INDEX, not a full synthesis. Deeper, non-obvious connections that ingest missed are caught by the maintain agent.

#### Query Agent

Answers questions against the wiki.

- Reads `INDEX.md` files and wiki pages to find relevant clusters.
- Reads the relevant Zettels, follows their connections.
- Synthesizes an answer with citations to specific Zettels and raw sources.
- If the answer produces new insight, files it as a new Zettel (and updates wiki pages if needed).

#### Maintain Agent

Handles both correctness and structural evolution in one pass. This merges what v3 called "lint" and "evolve" — the boundary between fixing broken things and proposing growth is too fuzzy to justify two agents. When you notice orphan Zettels, you naturally see that they should cluster into a new wiki page. When you find a page that's too large, you're already making the structural decision about how to split it.

**Correctness checks:**
- Orphan Zettels (no inbound links from other Zettels or wiki pages)
- Links without context (missing "why")
- Contradictions between Zettels — contradictions are fine and expected. Link the conflicting Zettels to each other with context explaining *what* contradicts and *how* the agent reads the tension. Don't resolve unless clearly wrong — the world has genuine disagreements.
- Stale content superseded by newer sources (the agent uses judgment — time-bound facts need freshness checks more than evergreen definitions or patterns)
- Missing Zettels (referenced but don't exist)
- Broken links to raw sources (files moved or deleted)

**Structural evolution:**
- Wiki pages that should be split (too large) or new pages for emerging Zettel clusters
- Zettels that should be split (violating atomicity) or merged (redundant)
- Connections that should exist but don't — deeper, cross-domain links that ingest missed
- Promotions: Zettels that have accumulated enough related notes to warrant their own wiki page
- New folder structure as domains grow
- Questions worth investigating / sources to seek out

Fixes routine issues autonomously. Flags structural proposals to human when they're significant.

### Design Principles

1. **Wiki pages = structure notes.** Topic-level pages that organize clusters of Zettels. Depth varies naturally — no imposed limit. A wiki page reads like a Wikipedia article — coherent narrative with inline links to the Zettels that back each claim.

2. **Zettels = atomic thoughts.** Timestamp-ID'd files, each capturing one thought. Written as processed knowledge (not copy-paste). Every Zettel links to at least one other Zettel or wiki page, with explicit context for *why* the connection exists. Topic tags in frontmatter enable discovery across the wiki.

3. **Sources live where they live.** Raw sources are *not* copied into the wiki. They can be anywhere in the filesystem — company deep dives under `hard-disk/`, downloaded articles, research outputs, transcripts. The wiki references them via paths. All the work we do across the hard-disk gets organically connected through the wiki.

5. **Evidence is always linkable.** Every claim in a wiki page or Zettel hyperlinks back to its evidence — another Zettel or a raw file on disk. Trace any assertion back to ground truth in a couple of clicks.

6. **`INDEX.md` everywhere.** Folders use `INDEX.md` files for navigation, matching our existing convention. Agents maintain these as part of normal wiki operations.

7. **`LEDGER.md` as the activity log.** Chronological, append-only record of ingests, queries, maintenance passes. Parseable with simple tools (`grep "^## \[" LEDGER.md | tail -5`).

8. **Knowledge, not information.** Every page should answer "why does this matter?" and "how does this connect?" — not just state facts.

9. **Agent-driven, not human-gated.** The agent is the main driver. It writes, organizes, links, and maintains autonomously. The human guides via conversation.

10. **Link context as inline prose.** Every link includes a sentence explaining *why* the connection exists. For now, this is inline prose in the Connections section. As the wiki scales, we may need a more structured backend for link metadata.

11. **Topic tags for entry points.** Zettels carry lightweight hashtags (e.g., `#platform-economics`, `#apple`, `#margins`). Tags serve as entry points for discovery — similar to Luhmann's register — not as a rigid taxonomy. The agent assigns them during ingest; tags emerge organically from use.

### Directory Structure

```
wiki/
├── INDEX.md                   # Master catalog — all wiki pages and Zettel domains
├── LEDGER.md                  # Chronological activity log (append-only)
│
├── pages/                     # Wiki pages (structure notes) — the "Wikipedia" layer
│   ├── INDEX.md               # Index of all topic pages
│   ├── companies/             # Company-level pages
│   │   ├── INDEX.md
│   │   ├── apple.md
│   │   └── nvidia.md
│   ├── concepts/              # Concept/method pages
│   │   ├── INDEX.md
│   │   ├── zettelkasten.md
│   │   └── llm-wiki.md
│   └── domains/               # Broader domain overviews (can nest deeper)
│       ├── INDEX.md
│       ├── ai-infrastructure.md
│       └── gpu-supply-chain/  # Sub-domain — depth grows as needed
│           ├── INDEX.md
│           └── nvidia-h100-allocation.md
│
└── zettels/                   # Atomic notes — timestamp-ID'd, one thought each
    ├── INDEX.md               # Zettel catalog (auto-maintained)
    ├── 202604160930.md
    ├── 202604160935.md
    └── ...
```

**Folder purposes:**

- **`pages/`** — Wiki pages (structure notes). The readable, navigable layer — organized by domain/topic in nested subfolders that grow as deep as needed. Each page links down to the Zettels that support it. Think Wikipedia articles.
- **`zettels/`** — Atomic notes. Flat folder, timestamp IDs. Each captures one thought/claim/insight with explicit links to related Zettels and up to wiki pages. The raw knowledge building blocks.

Raw source files live wherever they already are on disk. The wiki links to them — never copies them.

### Page Formats

**Wiki page (structure note):**

```markdown
---
title: "Apple Inc."
created: 2026-04-16
updated: 2026-04-16
---

# Apple Inc.

Apple's business has shifted decisively toward services revenue,
which [exceeded hardware revenue in Q2 2025](../../zettels/202604160930.md).
This transition has implications for margin structure — see
[services margin expansion](../../zettels/202604160935.md).

The competitive landscape is shaped by
[Apple's AI infrastructure strategy](../../zettels/202604160940.md),
which differs from Google's approach in that...

## Related

- [AI Infrastructure](../domains/ai-infrastructure.md) — Apple as
  a player in the broader AI infra buildout
- [NVIDIA](nvidia.md) — supplier relationship and chip dependency
```

**Zettel example:**

```markdown
---
id: "202604160930"
title: "Apple services revenue exceeded hardware in Q2 2025"
tags: ["#apple", "#services-revenue", "#earnings"]
created: 2026-04-16
source: "/Users/charlie-buffet/Documents/project-minerva/hard-disk/companies/apple/filings/10q-q2-2025.md"
---

# Apple services revenue exceeded hardware in Q2 2025

For the first time, Apple's Services segment generated more
revenue than any single hardware category in Q2 2025. This
marks a structural shift — not a seasonal blip — driven by
App Store, iCloud, and Apple TV+ growth.

## Connections

→ [202604160935](202604160935.md) — This margin shift matters
because services carry ~70% gross margins vs ~35% for hardware,
fundamentally changing Apple's earnings profile.

→ [202604160945](202604160945.md) — This is a textbook instance
of the platform economics model: Apple owns the install base and
is shifting monetization to services.

## Related

- [Apple Inc.](../pages/companies/apple.md)

## Evidence

- [Apple 10-Q, Q2 2025](/Users/charlie-buffet/Documents/project-minerva/hard-disk/companies/apple/filings/10q-q2-2025.md) — Revenue breakdown table, p.12
```

**Another Zettel example (cross-domain pattern — no special type, just a regular Zettel):**

```markdown
---
id: "202604160945"
title: "Platform economics: own the base, monetize via services"
tags: ["#platform-economics", "#business-models", "#apple", "#nvidia"]
created: 2026-04-16
---

# Platform economics: own the base, monetize via services

Once a company controls a large, sticky install base (hardware,
OS, marketplace), it can layer recurring services on top at
high margins. The install base is the moat; services are the
monetization. The pattern recurs across tech:

- Hardware → services (Apple: devices → App Store, iCloud)
- GPUs → software ecosystem (NVIDIA: chips → CUDA, enterprise AI)
- Marketplace → ads + logistics (Amazon: retail → AWS, Prime)

## Connections

→ [202604160930](202604160930.md) — Apple's Q2 2025 services
revenue exceeding hardware is a direct manifestation of this
pattern.

## Related

- [Apple Inc.](../pages/companies/apple.md)
- [NVIDIA](../pages/companies/nvidia.md)
```

---

## Decisions Made

| Decision                                     | Rationale                                                                                                       |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| All agents share one wiki                    | Agents are a society of thought — one brain, not separate thinkers                                              |
| Three subagents (ingest, query, maintain)    | Lint + evolve merged — boundary too fuzzy for separate agents                                                   |
| Ingest agent handles linking                 | Needs to understand wiki for placement; deeper connections caught by maintain agent                             |
| Timestamp IDs for Zettels                    | Unique by construction, no collision risk, machine-friendly                                                     |
| Semantic filenames for wiki pages            | Human-readable entry points (`apple.md` not `202604160930.md`)                                                  |
| Provenance via Zettel frontmatter + Evidence | Each Zettel's `source:` field and Evidence section track where claims come from; LEDGER records ingest activity |
| `INDEX.md` / `LEDGER.md` naming              | Match existing conventions (all caps)                                                                           |
| Replace the `learn` skill                    | This subsumes what `learn` does, with better structure                                                          |
| Sources live outside the wiki                | Wiki references sources wherever they are on disk — no copying                                                  |
| Agent as primary driver                      | Human guides, agent writes and maintains autonomously                                                           |
| No fixed tree depth                          | Structure grows organically — depth varies by domain                                                            |
| Start without search infrastructure          | `INDEX.md` files are sufficient initially; add search when scale demands it                                     |
| Dedup is part of ingest                      | Ingest agent checks for existing Zettels before creating; enriches existing notes when duplicate is clear       |
| Use `minerva extract` for large sources      | Context management for large documents; pick model size to match source complexity                              |
| Templates in skill `references/`              | Always available in agent context, follows AgentSkills spec, works before wiki exists                           |
| Inline prose for link context                | Simple, readable; may evolve to structured metadata as wiki scales                                              |
| Wiki page splitting by agent judgment        | No fixed threshold — maintain agent decides when a page is too large                                            |
| No type/subtype fields                       | Folder location tells you what something is; one less field to maintain                                         |
| Topic tags for discovery                     | Lightweight hashtags in frontmatter — entry points like Luhmann's register, not a rigid taxonomy                |
| No model-specific machinery                  | Cross-domain patterns emerge naturally from good linking; no special rules needed                               |
| Subagent prompts in `references/`            | Each subagent gets focused, thorough instructions; SKILL.md stays a clean overview + router; follows AgentSkills spec |
| Skill name: Zettel-Wiki                      | —                                                                                                               |

---

---

## Skill Specification: `zettel-wiki`

Below is the draft SKILL.md and file layout, ready to be turned into an actual skill directory.

### Skill directory layout

```
zettel-wiki/
├── SKILL.md                   # Overview, routing, principles
└── references/
    ├── schema.md              # Naming conventions, INDEX/LEDGER formats
    ├── ingest.md              # Ingest subagent prompt
    ├── query.md               # Query subagent prompt
    ├── maintain.md            # Maintain subagent prompt
    ├── zettel-template.md     # Zettel format template
    └── page-template.md       # Wiki page format template
```

Templates and subagent prompts live in the skill's `references/` directory, following the OpenClaw AgentSkills spec. The wiki directory holds only content (pages, Zettels) and infrastructure files (INDEX, LEDGER).

### Draft SKILL.md

```markdown
---
name: zettel-wiki
description: >
  Build and maintain an agent-driven knowledge base using the Zettel-Wiki
  pattern — a fusion of Karpathy's LLM Wiki and the Zettelkasten method.
  The wiki is a persistent, compounding hypertext of interlinked markdown
  files: wiki pages (structure notes) for navigable topic articles, and
  Zettels (atomic notes) for individual thoughts and claims. Use when:
  (1) ingesting a source into the wiki (article, filing, transcript, URL),
  (2) querying the wiki for knowledge or synthesis,
  (3) maintaining wiki health — fixing orphans, contradictions, broken links,
  (4) evolving wiki structure — splitting pages, proposing connections,
  promoting Zettel clusters into new wiki pages,
  (5) connecting new work (deep dives, research, reports) to existing
  knowledge in the wiki.
---

# Zettel-Wiki

Agent-maintained knowledge base. Two content types, three workflows,
one wiki shared across all agents.

Wiki root: `<hard-disk-root>/wiki/`

## Content types

| Type | Location | ID scheme | Purpose |
|---|---|---|---|
| Wiki page | `pages/` (nested folders) | Semantic filename (`apple.md`) | Structure notes — navigable topic articles that link down to Zettels |
| Zettel | `zettels/` (flat) | Timestamp (`YYYYMMDDHHmm`) | Atomic notes — one thought per file |

Wiki pages narrate and organize. Zettels are the evidence underneath.
Every link between pages or Zettels includes inline prose explaining
*why* the connection exists. Zettels carry topic tags for discovery.

## Infrastructure files

- `INDEX.md` — master catalog, auto-maintained (every subfolder gets one)
- `LEDGER.md` — append-only activity log

## Workflows

Three subagents, orchestrated by the main agent. SKILL.md provides
the overview and routing; each subagent has a dedicated prompt in
`references/` with thorough, focused instructions.

### 1. Ingest → `references/ingest.md`

Process a source into wiki knowledge. Handles extraction, dedup,
Zettel creation, linking, wiki page updates, and INDEX/LEDGER bookkeeping.

### 2. Query → `references/query.md`

Answer questions against the wiki. Navigates via INDEX files and wiki
pages, synthesizes answers with citations, and files new Zettels when
the answer produces insight.

### 3. Maintain → `references/maintain.md`

Combined correctness + structural evolution. Fixes orphans, broken links,
missing context, contradictions. Proposes splits, promotions, new pages,
and folder restructuring.

## Principles

- *Knowledge, not information.* Process and contextualize — never
  just excerpt. Every page answers "why does this matter?"
- *Evidence is always linkable.* Trace any claim back to a raw
  source file in two clicks.
- *Agent-driven.* Write, organize, link, maintain autonomously.
  Human guides via conversation.
- *Link context as inline prose.* Every connection states its "why."

## Page format quick reference

Templates live in `references/zettel-template.md` and
`references/page-template.md`. See `references/schema.md` for
naming and INDEX/LEDGER conventions.

**Zettel frontmatter:** `id`, `title`, `tags`, `created`, `source`
**Zettel sections:** body → Connections (with context) → Related → Evidence

**Wiki page frontmatter:** `title`, `created`, `updated`
**Wiki page sections:** narrative body with inline Zettel links → Related
```

### Draft `references/schema.md`

Naming conventions and infrastructure file formats — the rules that
don't belong in templates or subagent prompts.

```markdown
# Zettel-Wiki Schema

Conventions for the wiki at `<hard-disk-root>/wiki/`.

## Naming

- Wiki pages: lowercase kebab-case semantic filenames (`apple.md`,
  `gpu-supply-chain.md`)
- Zettels: timestamp IDs in `YYYYMMDDHHmm` format (`202604160930.md`)
- Folders: lowercase kebab-case (`companies/`, `concepts/`, `domains/`)
- Infrastructure files: ALL CAPS (`INDEX.md`, `LEDGER.md`)

## INDEX.md format

Every folder gets an `INDEX.md` with a markdown table:

| Name | Type | Notes |
|---|---|---|
| `apple.md` | page | Apple Inc. — business model, competitive position |
| `nvidia.md` | page | NVIDIA — GPU supply, AI infra |

## LEDGER.md format

Append-only. Each entry:

## [YYYY-MM-DD HH:MM] action | Title

- **Action**: `ingest`, `query`, `maintain`
- **Details**: what was done, which files were created/updated
- **Agent**: which subagent performed the work
```

---

## Sources

- Karpathy, A. (2026). "LLM Wiki." https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Fast, S. (2020). "Introduction to the Zettelkasten Method." https://zettelkasten.de/introduction/
