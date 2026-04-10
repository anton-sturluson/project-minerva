# Minerva Design — Evidence Collection and Analysis Workflow CLI

Date: 2026-04-09
Status: Implementation draft

## Scope

Implement these workflow commands:
- `evidence init`
- `evidence collect sec`
- `evidence register`
- `evidence inventory`
- `evidence extract`
- `evidence coverage`
- `analysis status`
- `analysis context`

Do not implement yet:
- first-class `analysis run`
- wrapper commands like `valuation-pack`, `report-skeleton`, `company start`
- browser collection
- final memo generation

For section-level analysis in v1, use existing `extract` against the context bundles produced by `analysis context`.

## Canonical workflow

```text
init company evidence tree
  ↓
collect SEC sources
  ↓
register external/reference/blocked sources
  ↓
inventory current state
  ↓
extract structured outputs from saved sources
  ↓
check coverage against profile targets
  ↓
compute analysis status
  ↓
build analysis context bundles
  ↓
run existing `extract` on section bundles as needed
  ↓
write / revise deep-dive memo
```

## Layout principles

- Keep the outer company folder format unchanged: `reports/00-companies/{nn}-{slug}/`.
- Inside a company root, use exactly these top-level folders: `notes/`, `data/`, `research/`, `analysis/`, `provenance/`.
- Make `data/` easy to scan by using exactly four direct subfolders: `sources/`, `references/`, `structured/`, `meta/`.
- Avoid redundant company nesting inside a company root. SEC downloads should land under source-type folders such as `sources/10-K/` or `sources/earnings/`, not `sources/sec/{ticker}/...`.
- Keep analysis workflow state shallow. `status.json`, `status.md`, `context-manifest.json`, `context-manifest.md`, and `bundles/` should sit directly under `analysis/`.
- Keep metadata centralized in `data/meta/` so registry, inventory, coverage, collection summaries, and extraction manifests are all in one predictable location.

The rationale for the flatter layout is operational rather than cosmetic:
- paths are shorter and easier to pass to commands
- humans can inspect a company root without mentally decoding numbered subfolders
- collectors and extractors do less path translation
- status and context artifacts become obvious workflow outputs instead of hidden implementation details

## Commands

## 1. `minerva evidence init`

Purpose:
- create or reuse the standard company tree
- initialize metadata files
- refresh relevant `INDEX.md` files

Inputs:
- `--root`
- `--ticker`
- `--name`
- `--slug`

Writes:
- company folder tree
- `data/meta/source-registry.json`
- `data/meta/source-registry.md`
- relevant `INDEX.md` files

Model:
- none

Implementation notes:
- deterministic path creation
- idempotent on rerun

## 2. `minerva evidence collect sec`

Purpose:
- collect SEC materials into the standard company tree
- replace ad hoc output paths with workflow-aware paths

Inputs:
- `--root`
- `--ticker`
- `--annual`
- `--quarters`
- `--earnings`
- `--financials`

Writes:
- `data/sources/10-K/...`
- `data/sources/10-Q/...`
- `data/sources/earnings/...`
- `data/sources/financials/...`
- collection summary JSON/markdown in `data/meta/`
- source-registry updates
- inventory refresh

Model:
- none

Implementation notes:
- reuse the current `sec bulk-download` implementation internally
- flatten only the evidence workflow layout; the standalone SEC command can keep its own defaults
- `evidence collect sec` becomes the only public workflow bulk SEC collector

## 3. `minerva evidence register`

Purpose:
- register externally collected sources
- register reference-only sources
- register blocked sources

Inputs:
- `--root`
- `--status` (`downloaded|discovered|blocked`)
- `--bucket`
- `--source-kind`
- `--title`
- `--path` (optional)
- `--url` (optional)
- `--notes` (optional)

Writes:
- `data/meta/source-registry.json`
- `data/meta/source-registry.md`
- relevant `INDEX.md` files

Model:
- none

Implementation notes:
- this is required to make mixed-source inventory deterministic
- use explicit bucket tags rather than fuzzy inference in v1

## 4. `minerva evidence inventory`

Purpose:
- compute current evidence state
- verify downloaded file existence
- summarize downloaded / discovered / extracted / blocked counts

Inputs:
- `--root`
- `--write-index`

Writes:
- `data/meta/inventory.json`
- `data/meta/inventory.md`
- relevant `INDEX.md` files

Model:
- none

Implementation notes:
- derive state from deterministic paths + registry entries
- do not infer truth from prose notes
- ignore generated `INDEX.md` files when counting tracked artifacts

## 5. `minerva evidence extract`

Purpose:
- run extraction over saved local sources using a named profile
- write mirrored structured outputs under `data/structured/`

Inputs:
- `--root`
- `--profile`
- `--source-prefix`
- `--match`
- `--force`
- optional model override

Writes:
- mirrored extraction outputs in `data/structured/...`
- extraction run manifest in `data/meta/extraction-runs/`
- relevant `INDEX.md` files

Model:
- yes
- default: cheap/light extraction model

Implementation notes:
- one model call per matched file
- use existing `extract-many` core logic
- skip outputs that already exist unless `--force`
- write JSON + markdown per extracted source
- source-backed outputs mirror the source-type folder layout; reference-backed outputs land under `structured/references/`

## 6. `minerva evidence coverage`

Purpose:
- compare actual evidence state against coverage profile targets
- answer whether required evidence is complete enough for analysis

Inputs:
- `--root`
- `--profile`

Writes:
- `data/meta/coverage.json`
- `data/meta/coverage.md`

Model:
- none in v1
- optional LLM assistance later for ambiguous bucket assignment

Implementation notes:
- read `source-registry.json` + `inventory.json`
- compare counts against explicit profile targets
- statuses:
  - `good`
  - `partial`
  - `missing`
  - `blocked`
- if registry is too incomplete to satisfy a bucket, treat as `missing`
- `good` requires meeting the target count, not just “at least one file exists”

## 7. `minerva analysis status`

Purpose:
- summarize where the company deep-dive workflow currently stands
- provide the next deterministic step

Inputs:
- `--root`

Writes:
- `analysis/status.json`
- `analysis/status.md`

Model:
- none

Implementation notes:
- read registry / inventory / coverage / context presence / note presence
- compute stage from files on disk, not via LLM
- ignore generated folder indexes when deciding whether notes, bundles, or provenance exist
- suggested stage model:
  - `initialized`
  - `collecting`
  - `extracting`
  - `analysis-ready`
  - `analysis-in-progress`
  - `memo-in-progress`
  - `complete`
- include a deterministic `next_step`

## 8. `minerva analysis context`

Purpose:
- build bounded context bundles for analysis sections
- package the actual extracted file contents that should be used for section analysis

Inputs:
- `--root`
- `--profile`

Writes:
- `analysis/context-manifest.json`
- `analysis/context-manifest.md`
- `analysis/bundles/*.md`
- relevant `INDEX.md` files

Model:
- none in v1

Implementation notes:
- this is not inventory
- `inventory` answers: what exists?
- `analysis context` answers: which actual extracted file bodies belong in a given section bundle?
- build section bundles from structured outputs using a context profile
- include token estimate per bundle in the manifest
- allow valuation artifacts to be included if present

## Analysis runs in v1

Do not build a first-class `analysis run` command yet.

Use existing `extract` on section bundles, e.g.:

```bash
minerva extract "What matters most about competitive position and why?" \
  --file hard-disk/reports/00-companies/12-robinhood/analysis/bundles/competition.md \
  --model <stronger-model>
```

This keeps v1 smaller while proving whether a first-class analysis runner is actually needed.

## On-disk layout

```text
reports/00-companies/{nn}-{slug}/
  notes/
  data/
    sources/
      10-K/
      10-Q/
      earnings/
      financials/
    references/
    structured/
      10-K/
      10-Q/
      earnings/
      financials/
      references/
      registered/
    meta/
      source-registry.json
      source-registry.md
      inventory.json
      inventory.md
      coverage.json
      coverage.md
      sec-collection-summary.json
      sec-collection-summary.md
      extraction-runs/
  research/
  analysis/
    status.json
    status.md
    context-manifest.json
    context-manifest.md
    bundles/
      business-overview.md
      competition.md
      management.md
      risks.md
      valuation.md
  provenance/
```

## Deep-dive note versioning and provenance

Deep dives should be versioned independently from the underlying evidence tree.

Suggested note naming:
- `notes/{date}-{slug}-deep-dive-v1.md`
- `notes/{date}-{slug}-deep-dive-v2.md`
- `notes/{date}-{slug}-deep-dive-v3.md`

Provenance records should live under:
- `provenance/`

Each provenance record should capture:
- note path
- note version
- context-manifest path
- coverage snapshot path
- inventory snapshot path
- section bundle paths used
- valuation artifact paths used (if any)
- created timestamp

## Profiles

Keep profiles in repo-managed files.

Suggested directories:
- `profiles/evidence/extract/*.yaml`
- `profiles/evidence/coverage/*.yaml`
- `profiles/analysis/context/*.yaml`

Responsibilities:
- extract profile = question packs by source kind
- coverage profile = bucket targets / thresholds
- context profile = which buckets feed which section bundles

## Relevant artifact fields

Keep JSON schemas minimal in v1.

### `source-registry.json`

Required fields:
- `id`
- `title`
- `ticker`
- `bucket`
- `source_kind`
- `status`
- `local_path`
- `url`
- `notes`
- `created_at`
- `updated_at`

### `inventory.json`

Required fields:
- `root`
- `counts`
- `downloaded_missing_on_disk`
- `last_updated`

### `coverage.json`

Required fields:
- `profile`
- `bucket_results[]`
- `ready_for_analysis`

### `context-manifest.json`

Required fields:
- `profile`
- `included_artifacts[]`
- `bundle_paths[]`
- `estimated_tokens`

### `status.json`

Required fields:
- `stage`
- `next_step`
- `milestones[]`

## Module layout

```text
src/harness/
  commands/
    evidence.py
    analysis.py
    sec.py
    extract.py
  workflows/
    evidence/
      collector.py
      registry.py
      inventory.py
      coverage.py
      profiles.py
      render.py
      paths.py
      extraction.py
    analysis/
      status.py
      context.py
```

Guideline:
- `commands/*.py` stay thin
- `workflows/*` own file/state logic
- markdown rendering is shared utility code

## Phased implementation

## Phase 1

Build:
1. `evidence init`
2. `evidence collect sec`
3. `evidence register`
4. `evidence inventory`

## Phase 2

Build:
5. `evidence extract`
6. `evidence coverage`
7. extraction / coverage profiles

## Phase 3

Build:
8. `analysis status`
9. `analysis context`
10. prove the section-bundle pattern using existing `extract`

## Phase 4

Do:
11. update `collect-evidence` skill to use the evidence workflow
12. update `analyze-business` skill to use `analysis status` + `analysis context`
13. revisit whether a first-class `analysis run` command is needed

## Acceptance criteria

- a company evidence tree can be initialized with one command
- SEC collection writes to deterministic workflow paths without redundant ticker nesting
- external/reference/blocked sources can be explicitly registered
- inventory reflects on-disk state without reading prose notes
- extraction runs over a source tree and writes mirrored structured outputs
- coverage compares actual counts against profile targets
- analysis status is computed deterministically from disk state
- analysis context writes reusable section bundles directly under `analysis/`
- existing `extract` can be used directly against those bundles
