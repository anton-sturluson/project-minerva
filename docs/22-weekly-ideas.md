# Original-source weekly ideas

`minerva ideas` uses HF Best Ideas only to discover company/fund leads. Investment reasoning comes from original manager documents. It uses the existing shared Postgres server and ordinary report files.

## Storage

Set `MINERVA_DATABASE_URL` to the shared database connection and `MINERVA_IDEAS_ROOT` to the canonical report directory. The default report directory is `hard-disk/reports/05-weekly-ideas`. Credentials belong in the scheduled environment or an ignored deployment-owned `.env.local`, never in Git or an automation prompt.

Minerva owns only the `minerva_ideas` schema, with three tables:

| Table | Purpose |
| --- | --- |
| `runs` | Issue URL/date and run identity. |
| `items` | Roster ordinal, company/fund/symbol, current state/error, compact document identity and view references. |
| `publications` | Payload hash, run/job IDs, destination, attempt state and compact delivery receipt. |

Original PDF/HTML, readable text, search/model traces and publication payloads live beneath `<root>/<issue-date>/runs/<run-id>/`. Source materials are co-located in `research/`. Database evidence points to source blocks; it does not duplicate full documents. There is no company master, speculative alias registry, general task queue or event store.

Files are finalized before their database references are committed. Artifact writes cannot silently replace existing content. Paths are relative to the configured report root. `init` applies additive schema changes without touching other schemas.

## Research and evidence

Each lead has at most two searches, six downloads including archive navigation, and three identity assessments. The default model is `gemini-2.5-flash-lite`; `--model` can override it. Model calls have bounded time/output. Provider failures are operational errors, not unavailable-source claims.

Company and fund identity must match the discovery lead. Distinctive fund words are preserved; a sibling fund is not a substitute. The displayed period retains the source wording. A normalized period end is used only for the documented 190-day freshness window and the check against future commentary.

Models select source block/passage IDs. Python supplies the exact archived evidence. Claims require investment reasoning about the featured company; holdings weights, performance attribution and general manager commentary alone are excluded. A separate support review checks each claim against its selected evidence, with at most one correction. Equity/credit, stance and explicitly stated action are separate fields. Semantic review remains fallible; inspect the retained evidence when reviewing a view.

## Commands

```sh
uv sync --extra jobwatch
uv run minerva ideas init
uv run minerva ideas run
uv run minerva ideas status              # latest issue, including delivery receipts
uv run minerva ideas status RUN_UUID
uv run minerva ideas resume RUN_UUID
uv run minerva ideas resume RUN_UUID --retry-gaps --limit 10
uv run minerva ideas render RUN_UUID
```

Use `render` for a preview: it has no model calls or delivery side effects. The diagnostic commands return JSON. `weekly` returns only the publishable digest or `NO_REPLY`.

For explicit candidate inputs:

```sh
uv run minerva ideas import issue.json --run-id RUN_UUID
uv run minerva ideas source RUN_UUID ORDINAL ORIGINAL_URL
uv run minerva ideas research RUN_UUID ORDINAL
uv run minerva ideas extract RUN_UUID ORDINAL
```

An import contains an issue URL/date and `roster` entries with `company`, `fund` and optional `symbol`. Reimporting the same UUID/content is idempotent. Duplicate roster rows are preserved by ordinal. Attaching a source does not approve its thesis.

Unchanged newsletter rosters reuse their run. Completed views and known gaps are skipped; retries of gaps are explicit. A Postgres session lock prevents concurrent work on one run and releases on process failure. A run has a 20-minute processing budget; remaining work can be resumed.

| Item state | Meaning |
| --- | --- |
| `pending` | Research has not completed. |
| `sourced` | A document candidate exists; no publishable view is approved. |
| `ready` | Evidence-backed view passed the current checks. |
| `gap` | No eligible view within the research/validation budget. This does not prove an original does not exist. |
| `failed` | Operational failure requiring retry or repair. |

## OpenClaw operation

The existing automation uses a native **command** payload with explicit argv:

```sh
scripts/run_weekly_ideas.sh EXISTING_JOB_UUID
```

Keep its owner, Saturday schedule and explicit Slack channel/thread. Configure `MINERVA_IDEAS_MODEL=gemini-2.5-flash-lite` in the command environment. The wrapper uses the installed `.venv/bin/minerva`, with no dependency installation during scheduled runs. Brave/Gemini keys are inherited from the Gateway environment. Native command execution avoids a reporting model rewriting content or generating fallback acknowledgements for a silent repeat.

`weekly` reconciles earlier delivery, researches incomplete work, and prepares output only when no pending, sourced or failed items remain. Gaps are omitted from the digest and retained in diagnostic status. Multiple fund views are grouped by company.

`prepare RUN_UUID JOB_UUID` claims a delivery attempt; it is not a preview command. Confirmed duplicates return `NO_REPLY`, which the native command scheduler suppresses. An uncertain attempt cannot be blindly repeated.

```sh
uv run minerva ideas reconcile EXISTING_JOB_UUID
```

Reconciliation requires exact equality between the prepared payload and the native run's full stdout summary, a successful execution, a fresh transport receipt and the expected explicit destination. Truncated or ambiguous records do not confirm delivery. Investigate uncertainty before another attempt; do not delete publication rows to force a resend.

The runtime currently uses a reviewed worktree pending merge. Keep that checkout and its ignored environment file until a verified deployment replaces it. Back up the existing job configuration before changing it; do not create a duplicate automation or restart the Gateway for this workflow.

## Validation

The PR series includes live Postgres import/source tests, bounded public-source discovery and extraction with Flash-Lite, full-issue processing, explicit gap retries, no-op resume, concurrency rejection, publication-state integration tests, and actual OpenClaw delivery tests. Full native stdout and transport receipts are used for verification; a process exit code alone is insufficient. The separate Slack connector may not have access to the Gateway's Slack workspace, so direct channel readback is a distinct capability.

## References

### Implementation
- [CLI](../src/harness/commands/ideas.py) — command contracts and scheduled entry point.
- [Store](../src/harness/ideas/store.py) — the three-table Postgres schema and filesystem contract.
- [Research](../src/harness/ideas/research.py) and [extraction](../src/harness/ideas/extraction.py) — source budgets, identity checks and evidence gates.
- [Publication](../src/harness/ideas/publication.py) — deterministic rendering, duplicate protection and transport verification.

### Platform behavior
- [OpenClaw automation payloads](https://docs.openclaw.ai/automation/cron-jobs/payloads) — native command execution and silent-output handling.
