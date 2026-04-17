# Minerva Evidence Starter, Live-Tested

Date: 2026-04-16
Status: Live-tested review draft

## Why this doc exists

Anton asked for a detailed starter walkthrough of the current `minerva evidence` workflow, based on real test runs rather than only the design docs.

This writeup focuses on two things:
- how each `minerva evidence` function *currently works*
- how the pieces are *intended to work together* as a starter workflow

Where current behavior differs from the likely intended design, I call that out plainly.

## Executive summary

The current evidence workflow is real, coherent, and usable:

1. `evidence init`
2. `evidence collect sec`
3. `evidence register`
4. `evidence inventory`
5. `evidence coverage`
6. `evidence extract`
7. downstream handoff to `analysis status` and `analysis context`

The main issue is that several readiness signals are currently *artifact-count based* rather than *logical-source based*.

That matters because:
- `--html` creates extra downloaded artifacts that increase coverage counts
- financial statement markdown and CSV files both count toward coverage
- inventory `extracted_files` counts both `.json` and `.md` outputs per extracted source

So the workflow basically works, but the measurement layer is currently a bit too flattering.

## What I tested

### Code and tests inspected

- `src/harness/commands/evidence.py`
- `src/harness/workflows/evidence/collector.py`
- `src/harness/workflows/evidence/registry.py`
- `src/harness/workflows/evidence/inventory.py`
- `src/harness/workflows/evidence/coverage.py`
- `src/harness/workflows/evidence/extraction.py`
- `src/harness/workflows/evidence/paths.py`
- `src/harness/workflows/evidence/render.py`
- `profiles/evidence/coverage/default.yaml`
- `profiles/evidence/coverage/test-minimal.yaml`
- `profiles/evidence/extract/default.yaml`
- `tests/test_harness/test_evidence.py`

### Automated tests run

```text
uv run pytest tests/test_harness/test_evidence.py -q
```

Result: `7 passed`

### Live smoke-test root

```text
/private/tmp/minerva-evidence-smoke-hood-20260416
```

### Live commands run

```text
uv run minerva evidence init \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --ticker HOOD \
  --name "Robinhood Markets" \
  --slug robinhood

EDGAR_IDENTITY='Charlie Buffet charlie.buffet.42@gmail.com' \
uv run minerva evidence collect sec \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --ticker HOOD \
  --annual 1 \
  --quarters 1 \
  --earnings 1 \
  --financials \
  --html

uv run minerva evidence register \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --status downloaded \
  --bucket external-research \
  --source-kind external-research \
  --title "Smoke test industry report" \
  --path /private/tmp/minerva-evidence-smoke-hood-20260416/data/references/industry-report.md \
  --url https://example.com/industry-report

uv run minerva evidence register \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --status discovered \
  --bucket external-research \
  --source-kind expert-call \
  --title "Potential channel check" \
  --url https://example.com/channel-check

uv run minerva evidence register \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --status blocked \
  --bucket external-research \
  --source-kind industry-report \
  --title "Paywalled market study" \
  --url https://example.com/paywalled-report

uv run minerva evidence inventory \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416

uv run minerva evidence coverage \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --profile default

uv run minerva evidence coverage \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --profile test-minimal

uv run minerva evidence extract \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --profile default \
  --model gemini-3.1-flash-lite-preview

uv run minerva evidence extract \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --profile default \
  --source-prefix data/sources/financials \
  --model gemini-3.1-flash-lite-preview

uv run minerva evidence extract \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416 \
  --profile default \
  --match industry \
  --model gemini-3.1-flash-lite-preview

uv run minerva analysis status \
  --root /private/tmp/minerva-evidence-smoke-hood-20260416
```

## Live results at a glance

### SEC collection

```text
collected_count: 12
```

Those 12 artifacts were:
- 1 `10-K` markdown
- 1 `10-K` HTML
- 1 `10-Q` markdown
- 1 `10-Q` HTML
- 1 earnings markdown
- 1 earnings HTML
- 3 financial statement markdown files
- 3 financial statement CSV files

### Registry after manual external registration

```text
source_count: 15
```

Breakdown:
- 13 downloaded
- 1 discovered
- 1 blocked

### Inventory after extraction

```text
blocked: 1
discovered: 1
downloaded: 13
downloaded_missing_on_disk: 0
extracted_files: 14
reference_files: 1
registry_total: 15
source_files: 12
```

### Coverage

Default profile:

```text
ready_for_analysis: False
```

Test-minimal profile:

```text
ready_for_analysis: True
```

### Extraction

First full extraction run:

```text
matched_count: 7
processed_count: 7
skipped_existing_count: 0
```

Immediate rerun without `--force`:

```text
matched_count: 7
processed_count: 0
skipped_existing_count: 7
```

Filtered reruns:

```text
--source-prefix data/sources/financials  -> matched_count: 3
--match industry                         -> matched_count: 1
```

### Downstream status

```text
stage: analysis-ready
next_step: minerva analysis context --root /private/tmp/minerva-evidence-smoke-hood-20260416 --profile default
```

## The current workflow, in plain English

```text
initialize company tree
  ↓
download SEC baseline into standard folders
  ↓
register non-SEC sources and blocked items
  ↓
recompute inventory
  ↓
measure coverage against a profile
  ↓
extract structured notes from saved local sources
  ↓
check analysis status and build bundles
```

That is the intended starter arc.

The important boundary is:
- `evidence *` builds the evidence base
- `analysis *` consumes that evidence base

## How each function currently works

## 1. `minerva evidence init`

Code path:
- `src/harness/commands/evidence.py`
- `src/harness/workflows/evidence/registry.py`
- `src/harness/workflows/evidence/paths.py`

### What it does

It creates or reuses the standard company tree and initializes the source registry.

### What it is supposed to do in detail

`init` is supposed to be the clean starting point for every company workflow.

Its intended responsibilities are:
- establish one canonical company root so every later command writes into the same tree
- guarantee the standard folder layout exists before any collection begins
- initialize the metadata shell so later commands do not have to guess where registry and status files belong
- make reruns safe, so revisiting a company extends the same evidence tree instead of creating parallel copies
- create a reusable research asset, not a one-off scratch folder

Its intended non-goals are just as important:
- it is not supposed to collect evidence
- it is not supposed to infer readiness
- it is not supposed to silently invent coverage state from missing data

In other words, `init` should give the workflow a stable home and then get out of the way.

### Required inputs

- `--root`
- `--ticker`
- `--name`
- `--slug`

### What it writes

Inside the company root it creates:

```text
notes/
data/
  sources/
  references/
  structured/
  meta/
    source-registry.json
    source-registry.md
    extraction-runs/
research/
analysis/
  bundles/
provenance/
```

It also refreshes `INDEX.md` files for the whole tree.

### How it is designed

This is the deterministic path normalizer. It gives the rest of the workflow a stable home.

### Important behavior

- It is idempotent.
- It does not collect anything itself.
- It stores company metadata in the registry even before there are any sources.

### Live observation

The command completed immediately and created the tree exactly as expected.

## 2. `minerva evidence collect sec`

Code path:
- `src/harness/commands/evidence.py`
- `src/harness/workflows/evidence/collector.py`
- reused SEC implementation in `src/harness/commands/sec.py`

### What it does

It pulls SEC materials into `data/sources/` and then registers every downloaded file into the source registry.

### What it is supposed to do in detail

`collect sec` is supposed to provide the deterministic primary-source baseline for a company.

Its intended responsibilities are:
- collect the core company-authored evidence that is available from SEC workflows without manual browsing
- save those materials into predictable folders so humans and downstream commands can find them easily
- preserve durable local artifacts, ideally in both machine-usable and human-reviewable forms when that is valuable
- map the collected materials into standard evidence buckets so later coverage checks are consistent
- update the registry immediately so the workflow can reason from explicit saved sources rather than rescanning folders ad hoc
- refresh inventory automatically so the tree is auditable right after collection

What it is *not* supposed to do:
- it is not supposed to decide whether the evidence base is fully sufficient
- it is not supposed to replace external research, competitor evidence, customer evidence, or ecosystem evidence
- it is not supposed to hide the difference between one logical source and several helper artifacts

The ideal role of `collect sec` is: "give me the clean, deterministic baseline quickly, then let the rest of the workflow show what is still missing."

### Required inputs

- `--root`
- `--ticker`

### Main options

- `--annual`
- `--quarters`
- `--earnings`
- `--financials/--no-financials`
- `--html/--no-html`

### What it writes

Typical outputs:

```text
data/sources/10-K/*.md
data/sources/10-K/*.html
data/sources/10-Q/*.md
data/sources/10-Q/*.html
data/sources/earnings/*.md
data/sources/earnings/*.html
data/sources/financials/{income,balance,cash}.md
data/sources/financials/{income,balance,cash}.csv
data/meta/sec-collection-summary.json
data/meta/sec-collection-summary.md
data/meta/source-registry.json
data/meta/source-registry.md
data/meta/inventory.json
data/meta/inventory.md
```

### How it is designed

This is the deterministic baseline collector. The design intent is:
- get the primary company-authored evidence in one shot
- standardize storage paths
- register those files immediately
- refresh inventory so the tree is auditable right away

### Important behavior

It calls `_bulk_download_one(...)`, then walks `data/sources/` and registers every file except dotfiles and `INDEX.md`.

That means the registry unit is currently **downloaded file artifact**, not **logical evidence document**.

### Live observation

For a `1/1/1` run with `--html` enabled, I got `collected_count: 12`.

That count was not:
- 1 annual filing
- 1 quarterly filing
- 1 earnings release
- 3 financial statements

It was:
- each markdown file
- plus each HTML file
- plus each CSV file

So a single logical filing can create multiple registry entries.

### Important design implication

This is the biggest current measurement distortion in the workflow.

If you enable `--html`, annual / quarterly / earnings counts effectively double.
If you include financials, each statement creates both markdown and CSV artifacts.

That makes coverage easier to satisfy than the actual evidence base deserves.

### Failure behavior

Without `EDGAR_IDENTITY`, the command fails immediately with a clear error:

```text
What went wrong: SEC evidence collection failed: EDGAR_IDENTITY is required for SEC commands
```

That part is good.

## 3. `minerva evidence register`

Code path:
- `src/harness/commands/evidence.py`
- `src/harness/workflows/evidence/registry.py`

### What it does

It inserts or updates a source entry in the registry.

### What it is supposed to do in detail

`register` is supposed to make every non-automatic source legible to the workflow.

Its intended responsibilities are:
- turn manual research finds into first-class workflow objects instead of leaving them buried in notes or chat history
- represent the difference between evidence that is saved locally, merely discovered, or materially blocked
- give external research the same registry-level visibility as SEC-collected material
- preserve provenance, so someone can later see what was downloaded, what still needs downloading, and what was inaccessible
- let the same company root accumulate useful evidence over time without losing track of where each item came from

This function matters because the deterministic collector only covers part of the world. `register` is supposed to close that gap and keep the evidence base honest.

### Required inputs

- `--root`
- `--status`
- `--bucket`
- `--source-kind`
- `--title`

Optional:
- `--path`
- `--url`
- `--notes`

### Supported statuses

- `downloaded`
- `discovered`
- `blocked`

### How it is designed

This is the bridge from deterministic SEC collection to everything else.

It lets the workflow track:
- locally saved external sources
- promising sources found but not yet downloaded
- blocked sources such as paywalls or inaccessible pages

### Important behavior

- `downloaded` requires `--path`
- local paths are normalized relative to the company root when possible
- the registry entry id is deterministic from ticker, bucket, source kind, title, path, and URL
- rerunning the same registration updates the existing entry instead of creating a duplicate

### Live observation

I registered all three states successfully:
- one downloaded local report in `data/references/industry-report.md`
- one discovered source
- one blocked source

That worked cleanly and is probably the healthiest piece of the workflow right now.

## 4. `minerva evidence inventory`

Code path:
- `src/harness/workflows/evidence/inventory.py`
- render helpers in `src/harness/workflows/evidence/render.py`

### What it does

It recomputes the current evidence state from the registry plus the filesystem.

### What it is supposed to do in detail

`inventory` is supposed to be the workflow's audit pass.

Its intended responsibilities are:
- answer "what evidence do we think we have?"
- answer "what evidence is actually on disk?"
- detect mismatches between registry claims and local files
- summarize the current tree in a lightweight form a human can review quickly
- give downstream steps a stable snapshot of the current evidence state

Conceptually, `inventory` should be safe to rerun at any time. It is not supposed to change the evidence base itself. It is supposed to measure and report the state of that base.

### What it measures

- total registry entries
- downloaded / discovered / blocked counts
- downloaded entries whose files are missing on disk
- raw source file count under `data/sources/`
- reference file count under `data/references/`
- extracted artifact count under `data/structured/`

### How it is designed

This is the audit layer. Its job is to tell you whether the registry and the disk still agree.

### Important behavior

It can refresh `INDEX.md` files unless `--no-write-index` is used.

### Live observation

After the smoke test, inventory showed:

```text
downloaded: 13
discovered: 1
blocked: 1
downloaded_missing_on_disk: 0
source_files: 12
reference_files: 1
extracted_files: 14
```

### Important design implication

`extracted_files: 14` did **not** mean 14 extracted sources.
It meant 7 processed sources times 2 output files each (`.json` + `.md`).

So inventory is useful, but again the counting unit is artifact-level.

## 5. `minerva evidence coverage`

Code path:
- `src/harness/workflows/evidence/coverage.py`
- profiles in `profiles/evidence/coverage/*.yaml`

### What it does

It compares current registry state against a named coverage profile.

### What it is supposed to do in detail

`coverage` is supposed to translate raw evidence counts into an explicit readiness view.

Its intended responsibilities are:
- define what "enough evidence" means for a named workflow stage or profile
- show bucket-by-bucket where the evidence base is strong, thin, missing, or blocked
- distinguish between partial progress and hard collection blockers
- make the next collection move obvious instead of forcing the user to infer it from raw files
- serve as a floor for readiness, not as a substitute for judgment

In the ideal design, `coverage` should help the collector say: "we have the baseline here, we are thin here, and these are the next buckets to fill before serious synthesis."

### How status is computed

Per bucket:
- `good` if `downloaded_count >= target_count`
- `blocked` if blocked items exist and downloaded + discovered are still below target
- `partial` if there is at least some downloaded or discovered evidence but not enough
- `missing` otherwise

Overall:
- `ready_for_analysis: True` only if *every* bucket is `good`

### Current profiles

#### `default`

Targets:
- `sec-filings-annual`: 5
- `sec-filings-quarterly`: 4
- `sec-earnings`: 20
- `sec-financial-statements`: 5
- `external-research`: 20

#### `test-minimal`

Targets:
- 1 annual
- 1 quarterly
- 1 earnings
- 3 financial statements
- 1 external research

This is clearly a smoke-test profile, but it is also useful as a starter sanity-check profile.

### Live observation

With the smoke-test root:

- `default` returned `ready_for_analysis: False`
- `test-minimal` returned `ready_for_analysis: True`

The `test-minimal` coverage markdown showed:

```text
sec-filings-annual       good  downloaded=2
sec-filings-quarterly    good  downloaded=2
sec-earnings             good  downloaded=2
sec-financial-statements good  downloaded=6
external-research        good  downloaded=1 discovered=1 blocked=1
```

### Important design implication

This is the clearest place where the artifact-count problem leaks into decision quality.

Because coverage counts registry entries, not logical sources:
- one 10-K with markdown + HTML becomes `downloaded=2`
- one 10-Q with markdown + HTML becomes `downloaded=2`
- one earnings release with markdown + HTML becomes `downloaded=2`
- three financial statements with markdown + CSV become `downloaded=6`

So coverage can say `good` earlier than a human would.

### Another subtle issue

The targets are using mixed units.

Examples:
- `external-research: 20` reads like 20 distinct sources
- `sec-financial-statements: 5` only really makes sense if helper artifacts count

That inconsistency should probably be fixed before the skill protocol is treated as mature.

## 6. `minerva evidence extract`

Code path:
- `src/harness/workflows/evidence/extraction.py`
- question profile in `profiles/evidence/extract/default.yaml`

### What it does

It runs structured question-answer extraction over saved local sources whose `source_kind` appears in the named extraction profile.

### What it is supposed to do in detail

`extract` is supposed to convert raw saved documents into reusable, structured working knowledge.

Its intended responsibilities are:
- apply source-type-specific question sets to raw documents so important facts are pulled out consistently
- produce durable structured outputs that are easier to analyze than the raw filing or report alone
- make repeated analysis cheaper by saving the extracted answers once instead of rediscovering them every session
- keep the transformation auditable by tying each structured output back to a concrete saved source
- bridge the gap between evidence collection and higher-level analysis/context bundling

In the ideal workflow, `extract` should not replace judgment. It should reduce raw-document handling and create a consistent substrate for later synthesis.

### Requirements

- `GEMINI_API_KEY` must be set
- the source must be `downloaded`
- the source must have a local path
- the file must still exist on disk
- the `source_kind` must appear in the extraction profile

### Matching and filters

`extract` first builds its candidate set from the registry.

Then it filters by:
- `--source-prefix`, matched against `local_path`
- `--match`, matched against title / bucket / source kind / local path / notes

### How the prompt works

For each matched source, it combines all questions for that `source_kind` into one prompt with this shape:

```text
## <id>
<answer>
```

Then it splits the model response back into sections.

So extraction is *one model call per source*, not one model call per question.

That is a good design choice.

### What it writes

For each processed source it writes:
- `data/structured/.../*.json`
- `data/structured/.../*.md`

It mirrors source-relative paths when possible.

Examples from the live run:

```text
data/structured/10-K/2026-02-20.md
data/structured/10-Q/2025-11-06.md
data/structured/earnings/2026-03-24.md
data/structured/financials/income.md
data/structured/references/industry-report.md
```

It also writes a run manifest under:

```text
data/meta/extraction-runs/
```

### Skip behavior

If both the structured `.json` and `.md` already exist, rerunning without `--force` skips that source.

### Live observation

Full run:

```text
matched_count: 7
processed_count: 7
skipped_existing_count: 0
```

Immediate rerun:

```text
matched_count: 7
processed_count: 0
skipped_existing_count: 7
```

Filtered reruns:

```text
--source-prefix data/sources/financials -> matched_count: 3
--match industry                        -> matched_count: 1
```

### Failure behavior

A deliberately bad match filter produced a clean failure:

```text
What went wrong: evidence extraction failed: no downloaded sources matched the requested extraction filters
```

### Important design implication

Extraction currently aligns to `source_kind`, not coverage bucket completeness.

That is mostly fine, but it means coverage can look complete even if the meaningful extractable inputs are weak or duplicated.

## How the functions are designed to work together

## Intended starter sequence

### Step 1. Initialize once

Use `evidence init` to establish the canonical company root.

### Step 2. Collect deterministic primary evidence

Use `evidence collect sec` to pull the company-authored baseline into stable folders.

### Step 3. Add everything SEC does not cover

Use `evidence register` for:
- external reports downloaded locally
- discovered but not yet saved sources
- blocked sources that still matter

### Step 4. Recompute audit state

Use `evidence inventory` so the registry and filesystem are synchronized and reviewable.

### Step 5. Measure gap state

Use `evidence coverage` to see which buckets are still thin.

### Step 6. Convert raw sources into reusable structured notes

Use `evidence extract` on the saved local sources.

### Step 7. Hand off to analysis

Use `minerva analysis status` and then `minerva analysis context`.

## In practice, the workflow is a loop

The real working loop is closer to:

```text
init
  ↓
collect sec
  ↓
inventory
  ↓
coverage
  ↓
search/download/register external evidence
  ↓
inventory
  ↓
coverage
  ↓
extract
  ↓
status/context
```

That loop is what the `collect-evidence` skill should probably teach more explicitly.

## What is currently solid

- the path layout is clean and predictable
- the registry concept is strong
- `register` is flexible enough to unify downloaded / discovered / blocked evidence
- extraction profiles are clear and easy to extend
- the handoff into `analysis status` is sensible
- failures for missing EDGAR identity and empty extract matches are clear

## What needs improvement next

## 1. Coverage should count logical sources, not helper artifacts

Current problem:
- markdown and HTML both count
- markdown and CSV both count

Better design:
- separate `document_count` from `artifact_count`
- count one logical filing once, regardless of helper artifacts
- let HTML and CSV stay useful, but not inflate readiness

## 2. Coverage targets need consistent units

Current problem:
- some targets read like logical documents
- others only make sense as artifact counts

Better design:
- define every target in one unit system
- probably logical sources by bucket

## 3. The protocol should distinguish baseline readiness from full evidence maturity

Current problem:
- `test-minimal` is useful, but clearly much lighter than `default`
- `default` is the real target, but SEC collection alone cannot get you there

Better design:
- explicitly name profiles like `smoke`, `starter`, `deep-dive`
- teach the skill which one to use at which stage

## 4. Inventory should expose source-level extraction counts too

Current problem:
- `extracted_files` counts `.json` + `.md`

Better design:
- expose `extracted_sources`
- optionally keep `extracted_artifacts` as a secondary metric

## 5. The skill should say when to run coverage before and after external search

Current problem:
- the command set supports the loop
- the skill text still underspecifies the exact orchestration

Better design:
- collect SEC baseline
- run coverage
- fill missing buckets through research/register
- rerun coverage
- then extract and hand off

## Bottom line

The current `minerva evidence` layer is already a real workflow, not just a sketch.

As a starter, it works like this:
- build the company tree
- collect SEC baseline
- register the non-SEC world explicitly
- audit inventory
- measure bucket coverage
- extract reusable structured notes
- hand off to analysis

The main thing that now needs major improvement is not the existence of the workflow, but the *measurement logic* around it.

Right now the system is too willing to treat helper artifacts as evidence units. That makes inventory and coverage look stronger than they really are. Fixing that will make the skill protocol much more honest and much more useful.

## Zero-based redesign: what is actually indispensable

I agree with the broader criticism: we may be forcing too much determinism into places where the agent should be allowed to reason.

The key distinction is:
- *deterministic storage and provenance are still valuable*
- *deterministic workflow logic is where the current design starts to become brittle*

In a more agentic design, the system should be strict about preserving evidence and loose about how the agent reasons over it.

## The absolute minimum functionality I would keep

If we started from zero, these are the functions I think are actually indispensable.

### 1. Create or reuse a canonical company workspace

This is the one piece of hard determinism I would definitely keep.

We still need:
- one place where the company work lives
- predictable folders for raw sources, derived notes, and final analysis artifacts
- a stable root the agent can return to across sessions

Without that, agentic collection turns into file sprawl and memory loss.

### 2. Save a source durably, with lightweight provenance

This is the single most important evidence primitive.

The system needs one unified way to say:
- here is a file we saved locally
- here is a URL we found but did not save yet
- here is something blocked by paywall/login/error
- here is why it matters

This does **not** need to look like the current `register` command.
But the capability itself is indispensable.

If the agent cannot leave behind a durable source record, the evidence base will decay into chat history.

### 3. Search / inspect the current evidence base

An agentic system still needs to answer:
- what do we already have?
- where is it?
- what did we already find but not download?
- what was blocked?

This could be a lightweight search/list/open function rather than a rigid `inventory` command, but some inspectability layer is essential.

Otherwise every session partially starts over.

### 4. Agentic gap assessment

This is the big replacement for deterministic `coverage`.

The system needs a way for the agent to answer:
- what evidence categories are strong?
- what is still thin?
- what is the next best collection step?
- are we ready for analysis, or not yet?

I do **not** think this should be a bucket counter.
I think this should be an agent-generated gap memo or review artifact, possibly with suggested next actions.

The judgment here should be agentic, not arithmetic.

### 5. Build an analysis-ready context package

At some point the agent needs to hand off from "I collected things" to "I can now reason over this coherently."

So I would keep some form of context builder or bundle builder that:
- gathers the most relevant saved artifacts
- organizes them into a usable analysis set
- creates a reproducible handoff point for deeper work

This can stay fairly deterministic because it is mostly packaging, not reasoning.

## What I would make optional rather than foundational

### 6. Per-source extraction / distillation

Something like `extract` is useful, but I no longer think it should be a mandatory stage in the workflow.

It is most useful when:
- documents are long
- repeated reuse is likely
- we want structured notes for specific source types
- we are preparing context bundles for deeper synthesis

But it should be an optional accelerator, not a core gating step.

## What I would demolish or absorb

### Demolish `coverage` in its current form

I would not try to repair the current bucket-count version first.
I would replace it with an agentic review step.

Reason:
- it is too tied to deterministic counts
- it breaks once the agent collects heterogeneous external data
- it encourages gaming the metric instead of improving the evidence base

### Absorb `register` into a broader `add source` or `save source` primitive

The capability is needed.
The current mental model probably is not.

A better design would let the agent say one thing like:
- add this downloaded file
- note this discovered URL
- mark this as blocked
- attach a short reason

That is simpler and more agentic.

### Demote `inventory` from a first-class workflow step to a background or on-demand scan

Some inventory logic is useful.
But forcing users or agents to think in terms of inventory as a core stage feels too mechanical.

Better design:
- keep the scan capability
- run it automatically when helpful
- surface it when auditing or debugging
- do not make it the center of the workflow

### Demote `extract` from required stage to optional tool

Keep the capability, but do not build the whole evidence protocol around it.

## The lean public interface I would aim for

If we wanted a much simpler, more agentic surface, I would aim for something closer to four public functions:

1. `init` or `open` company workspace
2. `add-source` or `save-source`
3. `review` or `gap-check`
4. `build-context`

And then keep lower-level helpers behind the scenes.

That would preserve the real invariants:
- durable evidence
- provenance
- inspectability
- readiness judgment
- handoff to analysis

without forcing the user or the agent through an overly deterministic pipeline.

## My current zero-based take

If we are being ruthless, the thing to protect is *not* the current command set.
It is the underlying capability set.

What must exist:
- canonical workspace
- durable source capture
- lightweight provenance
- inspect/search state
- agentic gap assessment
- context packaging

What does **not** need to survive in its current form:
- `register` as a standalone concept
- `inventory` as a mandatory stage
- `coverage` as bucket arithmetic
- `extract` as a required workflow gate

If you want, the next step I can take is to rewrite the doc around this zero-based model and propose a radically simpler v2 interface.
