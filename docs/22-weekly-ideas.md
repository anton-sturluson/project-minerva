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

Each lead has at most two searches, six downloads including archive navigation, and three identity assessments. Source verification uses `gpt-6-luna`; thesis extraction and claim review each use `gpt-6.1-sol`. These are separate schema-constrained API calls, not agent sessions. OpenAI calls use low reasoning, a 180-second timeout, no automatic SDK retries and `store=False`.

Set `MINERVA_IDEAS_SOURCE_MODEL`, `MINERVA_IDEAS_EXTRACTION_MODEL` and `MINERVA_IDEAS_REVIEW_MODEL` to override stages. An explicit `--model` overrides all three for a single invocation (for example, `--model gemini-2.5-flash-lite` for cheap diagnostics). OpenAI stages require `OPENAI_API_KEY`; Gemini stages require `GEMINI_API_KEY`. No silent model fallback is used. Model calls have bounded time/output. Provider failures are operational errors, not unavailable-source claims.

Company and fund identity must match the discovery lead. Distinctive fund words are preserved; a sibling fund is not a substitute. The displayed period retains the source wording. A normalized period end is used only for the documented 190-day freshness window and the check against future commentary.

Models select source block/passage IDs. Python supplies the exact archived evidence. Claims require investment reasoning about the featured company; holdings weights, performance attribution and general manager commentary alone are excluded. A separate support review checks each claim against its selected evidence, with at most one correction. Equity/credit, stance and explicitly stated action are separate fields. Semantic review remains fallible; inspect the retained evidence when reviewing a view.

## Commands

```sh
uv sync --extra jobwatch
uv run minerva ideas init
uv run minerva ideas run
uv run minerva ideas run --fresh          # explicitly redo all research for this issue
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

Unchanged newsletter rosters reuse their run. `run --fresh` creates a new run with no inherited approvals, preserving earlier evidence and publication receipts. A model configuration change alone does not invalidate completed views: use `--fresh` to reprocess them. Completed views and known gaps are skipped; retries of gaps are explicit. A Postgres session lock prevents concurrent work on one run and releases on process failure. A run has a 20-minute processing budget; remaining work can be resumed.

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

Keep its owner, Saturday schedule and explicit `#ideas` Slack channel. Set OpenClaw delivery to `mode=none` and leave `delivery.threadId` unset. Minerva sends the parent and replies explicitly through `openclaw message send`; scheduler announcement must stay disabled to prevent an extra channel post. Configure this once with:

```sh
openclaw cron edit EXISTING_JOB_UUID --no-deliver --clear-thread-id
```

Each new publication starts with `🧵 Manager Ideas - YYYY-MM-DD`, using the newsletter issue date. The complete verified summary follows in replies to that new message. Long summaries are split on line boundaries into bounded replies in the same thread. Neither the parent title nor the destination is selected by a model.

Configure the three stage environment variables above in the command environment. The wrapper uses the installed `.venv/bin/minerva`, with no dependency installation during scheduled runs. Brave/OpenAI keys are inherited from the Gateway environment.

`weekly` reconciles legacy announcements, researches incomplete work, then publishes only when no pending, sourced or failed items remain. Gaps stay in diagnostic status. It returns `NO_REPLY` after publication or a confirmed duplicate; the publication receipt in `minerva ideas status` records actual Slack delivery. With announcements disabled, the cron's own announcement status is not the publication receipt.

Publication identity includes the format, destination, parent title and full digest. The existing publications table stores the parent ID and acknowledged reply IDs as progress; raw transport acknowledgements stay beside the archived payload. A timeout or partial send marks the publication uncertain and blocks automatic resending, preserving any confirmed parent/replies for investigation. Read the saved receipts and Slack thread before resolving an uncertain send. Do not delete publication rows to force a retry.

`render` remains a side-effect-free preview. `prepare` and `reconcile` retain the legacy announce-mode contract for earlier receipts; `prepare` does not send the new threaded format. Legacy reconciliation requires exact payload equality, successful execution and the explicit destination in the Gateway receipt.

The runtime uses a dedicated clean worktree detached at a verified merged `main` commit. Keep that checkout and its ignored environment file until a verified deployment replaces it; do not use a development branch as the scheduled runtime. Back up the existing job configuration before changing it; do not create a duplicate automation or restart the Gateway for this workflow.

## Validation

The PR series includes live Postgres import/source tests, bounded public-source discovery and extraction with Flash-Lite, full-issue processing, explicit gap retries, no-op resume, concurrency rejection, publication-state integration tests, and actual OpenClaw delivery tests. Threaded publication is verified with per-message Slack acknowledgements and direct parent/thread readback; a process exit code alone is insufficient. The separate Slack connector may not have access to the Gateway's Slack workspace, so direct channel readback is a distinct capability.

## References

### Implementation
- [CLI](../src/harness/commands/ideas.py) — command contracts and scheduled entry point.
- [Store](../src/harness/ideas/store.py) — the three-table Postgres schema and filesystem contract.
- [Research](../src/harness/ideas/research.py) and [extraction](../src/harness/ideas/extraction.py) — source budgets, identity checks and evidence gates.
- [Publication](../src/harness/ideas/publication.py) — deterministic rendering, duplicate protection and transport verification.

### Model API
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) — schema-constrained responses; application evidence checks remain mandatory.
- [GPT-6 model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6.1-sol) — exact model IDs and supported reasoning settings.

### Platform behavior
- [OpenClaw automation payloads](https://docs.openclaw.ai/automation/cron-jobs/payloads) — native command execution and silent-output handling.
