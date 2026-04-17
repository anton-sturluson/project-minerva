# Minerva Evidence V2, Zero-Based Agentic Redesign

Date: 2026-04-16
Status: Draft for review

## Why this exists

The current `minerva evidence` design is too bookkeeping-heavy for messy real-world research.

V2 should be simpler:
- deterministic about storage and provenance
- agentic about what matters, what is missing, and what to do next

The goal is not to repair every V1 command.
The goal is to keep only the functions an agentic evidence workflow actually needs.

## The minimal capability set

If we are ruthless, the workflow only needs a small set of core capabilities.

## 1. Canonical company workspace

We need one stable company root.

Why this is indispensable:
- the agent needs a durable home for the company across sessions
- saved evidence needs predictable locations
- later analysis needs a stable root to build on
- without this, agentic collection turns into file sprawl and memory loss

What this should do:
- create or reuse the company root
- create standard folders for raw sources, agent notes, and derived artifacts
- avoid creating parallel trees for the same company

What this should *not* do:
- perform evidence judgment
- infer readiness
- impose workflow stages

Recommendation:
- keep a lightweight `init` primitive

Suggested default folder structure:

```text
{company-root}/
  notes/
  plans/
  data/
    sources/
    references/
    cache/
    evidence.jsonl
    evidence.md
```

Folder purposes and which commands touch them:
- `notes/`: working notes and short research writeups. Agent-written.
- `plans/`: research and collection plans. Agent-written.
- `data/sources/`: durable source artifacts. Primary output location for `minerva evidence add-source`.
- `data/references/`: lightweight reference notes or helper material. Optional support location for `add-source` in note/reference mode.
- `data/cache/`: disposable intermediate output from browser, scraping, or conversion flows.
- `data/evidence.jsonl`: machine-friendly evidence ledger. Appended by `minerva evidence add-source`.
- `data/evidence.md`: human-readable rendered view of the evidence ledger. Regenerated after `add-source`.

Design rule:
- separate durable evidence, disposable helper output, and working notes

## 2. Durable source capture

This is the most important capability in the whole system.

The workflow needs one unified way to capture:
- downloaded local source
- discovered source not yet downloaded
- blocked source
- agent note about why the source matters

Why this is indispensable:
- if the agent cannot leave behind durable source records, evidence quality collapses back into chat history
- external evidence is too messy to rely on deterministic collectors alone
- provenance has to survive across sessions and across agents

What this should do:
- save the real source artifact locally whenever possible
- note the URL or blocker when the artifact cannot be saved
- append a lightweight JSONL evidence record in `data/evidence.jsonl`
- render that ledger into a markdown table in `data/evidence.md`
- attach short provenance metadata
- support both deterministic collectors and manual/browser/web flows

What this should *not* do:
- force the user to think in registry jargon
- require a separate mental model for SEC vs external vs blocked sources

Recommendation:
- replace `register` with a broader `add-source` / `save-source` primitive

What `add-source` is actually doing:
- it is **not** the discovery mechanism itself
- discovery can still happen through browser flows, the browser skill, `web_search`, `web_fetch`, `minerva research`, or helper collectors like SEC
- `add-source` is the persistence boundary where the agent turns a found thing into durable project state

So the flow becomes:
1. the agent discovers something using whatever tool is appropriate
2. if it matters, the agent saves the real artifact locally or records the URL/blocker
3. `add-source` appends a lightweight JSONL evidence record in `data/evidence.jsonl`
4. the system renders that ledger into `data/evidence.md`

That is why this function is still essential even in a non-deterministic world. It is the bridge between open-ended discovery and durable evidence.

## 3. Inspect / search current evidence state

The agent needs to be able to answer:
- what do we already have?
- what do we only know about but have not saved?
- what was blocked?
- what files and notes already exist?

Why this is indispensable:
- otherwise every session partially restarts the research
- the agent will re-search instead of extending prior work
- there is no reliable handoff between collection and analysis

What this should do:
- list and search current sources and derived artifacts
- open the relevant local files quickly
- surface saved / discovered / blocked state without forcing a heavyweight workflow step

What this should *not* do:
- become a mandatory ritual stage in the workflow
- overfocus on counts when retrieval and visibility are what matter

Recommendation:
- keep a background scan/index capability
- demote explicit `inventory` from a core public command

## 4. Agentic audit

This is the replacement for deterministic `coverage`.

The workflow still needs an answer to:
- what is strong?
- what is thin?
- what is missing?
- what is blocked?
- what is the next best collection move?
- are we ready for serious analysis?

Why this is indispensable:
- evidence collection without an explicit gap assessment tends to stop too early or expand randomly
- the agent needs a way to convert raw collection state into a judgment about sufficiency

What this should do:
- generate an evidence audit memo
- summarize strongest and weakest parts of the current evidence base
- name the missing evidence types that matter most
- recommend next collection steps
- provide an explicit readiness judgment

What this should *not* do:
- reduce readiness to bucket arithmetic alone
- pretend all evidence types are commensurable because they share a counter
- reward HTML/CSV helper artifacts as if they were distinct evidence units

Recommendation:
- replace `coverage` with an agent-generated `audit` artifact
- make the audit explicitly LLM/agent-driven
- allow lightweight deterministic stats underneath, but keep the user-facing layer judgment-based

## Optional, not foundational

## Per-source extraction / distillation

`extract`-like functionality is useful, but it should not be a mandatory workflow gate.

It is most valuable when:
- the source is long
- structured recall is useful later
- repeated reuse is likely
- we want consistent question sets for a source type

It should be treated as an accelerator, not as a required stage.

## Deterministic collectors

A deterministic SEC collector is still useful.

But it should be treated as a helper capability, not the mental model for the whole workflow.

The core model should be:
- save evidence
- inspect evidence
- audit evidence

not:
- count evidence into buckets until the machine says you are allowed to think

## The lean public interface

If we wanted a much smaller public surface, I would aim for three public functions.

## 1. `minerva evidence init`

Purpose:
- create or reuse the canonical company workspace

Public promise:
- "give me the stable home for this company"

Inputs:
- company identifier, such as ticker or company slug
- optional company name metadata
- optional root override

Outputs:
- canonical company root
- standard folder structure if missing
- stable path that later commands can reuse

Primary write locations:
- company root folders only

## 2. `minerva evidence add-source`

Purpose:
- unify downloaded, discovered, blocked, and helper-collected sources under one user-facing action

Public promise:
- "save the real evidence and log it in a lightweight ledger"

This is more than a ledger.
It is the moment where the agent takes something it found in the wild and makes it part of the durable company evidence base.

Inputs:
- company root or company identifier
- one source payload, such as local file, URL, note, or blocked-source record
- optional source metadata, such as title, source type, date, and why it matters
- optional collector mode, such as SEC-backed acquisition

Outputs:
- saved artifact under `data/sources/` when a real file is available
- reference or note artifact under `data/references/` when the input is intentionally lightweight
- appended JSONL evidence record in `data/evidence.jsonl`
- refreshed markdown-table view in `data/evidence.md`

Suggested modes:
- local file
- URL only
- blocked
- note
- optional collector-backed modes, like SEC

## 3. `minerva evidence audit`

Purpose:
- produce an agentic assessment of evidence quality, gaps, blockers, and next steps

Public promise:
- "tell me what we have, what is weak, and what to do next"

Inputs:
- company root
- current evidence ledger and relevant local files
- optional scope or audit question

Outputs:
- audit memo or structured artifact under the company workspace
- strongest evidence summary
- thinnest evidence summary
- blocked/high-friction evidence
- missing source types
- readiness judgment
- recommended next collection actions

Primary write locations:
- likely `notes/` or `analysis/` depending on how formal we want the audit artifact to be

## What gets deleted, absorbed, or demoted

## Delete as public concepts

### `register`

The capability survives.
The standalone user concept should not.

Reason:
- it is too bookkeeping-shaped
- it teaches the wrong mental model
- users should think in terms of adding evidence, not registering a row

### `coverage`

Delete the current bucket-count concept.

Reason:
- it is too arithmetic-heavy
- it breaks under heterogeneous external evidence
- it encourages metric gaming
- it mistakes helper artifacts for evidence units

## Demote from central stage to background helper

### `inventory`

Keep the underlying scan/index logic.
Demote it from a first-class workflow step.

Reason:
- inspectability matters
- mandatory inventory rituals do not

### `extract`

Keep it as an optional tool.
Remove it as a required gate.

Reason:
- useful in many cases
- harmful as a universal stage

## The underlying deterministic helpers that should remain

Even in a more agentic design, a few deterministic helpers are still worth keeping behind the scenes.

- file scan / index refresh
- local source metadata persistence
- path normalization
- SEC collector helper
- optional extraction helper
- audit artifact generation helper

The difference is that they should support the agent's judgment, not define it.

## Recommended migration from V1 to V2

| Current concept | V2 treatment | Why |
| --- | --- | --- |
| `evidence init` | keep | canonical workspace is still essential |
| `evidence collect sec` | keep as helper or optional mode under `add-source` | useful deterministic baseline, but not the whole worldview |
| `evidence register` | absorb into `add-source` | same capability, better mental model |
| `evidence inventory` | demote to background/on-demand helper | inspectability matters more than ritual counting |
| `evidence coverage` | replace with `audit` | readiness judgment should be agentic |
| `evidence extract` | keep as optional accelerator | useful, but not foundational |
| `analysis context` | delete as a public command | analysis should read directly from the evidence base or use a narrower helper later if needed |

## Proposed V2 workflow

### Fast starter path

```text
init/open company root
  ↓
add sources (agentic + helper collectors)
  ↓
audit evidence base
  ↓
add more sources if needed
  ↓
analyze
```

### What this changes philosophically

Old worldview:
- collect into deterministic buckets
- count enough things
- declare readiness
- then analyze

New worldview:
- preserve evidence rigorously
- let the agent judge sufficiency
- keep the evidence base inspectable
- move into analysis directly from the evidence base

## What I would build first

If we are serious about burning the old boat, I would build V2 in this order:

### Phase 1
- keep `init`
- create `add-source`
- create `audit`

### Phase 2
- move current SEC collection behind `add-source` or keep it as a helper alias
- move `inventory` logic to background refresh and search/index surfaces

### Phase 3
- deprecate user-facing `register`
- deprecate user-facing `coverage`
- remove `extract` as a workflow requirement
- remove `analysis context` as a public command

## Bottom line

The current system is not wrong because it has deterministic pieces.
It is wrong because too much of the *public workflow* is built around deterministic bookkeeping.

The V2 principle should be simple:
- hard determinism for saving real artifacts and recording lightweight JSONL provenance
- soft, agentic judgment for evidence sufficiency

If we follow that, the system gets smaller, cleaner, and much more compatible with real-world agentic collection.
