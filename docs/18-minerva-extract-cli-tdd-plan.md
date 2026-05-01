# Minerva extract CLI — TDD improvement plan

**Date:** May 1, 2026
**Status:** Audited and revised plan
**Primary code:** [extract.py](project-minerva/src/harness/commands/extract.py)
**Primary tests:** [test_extract.py](project-minerva/tests/test_harness/test_extract.py)

---

## Problem statement

The current extraction CLI has the wrong shape for the workflows we actually use.

`minerva extract` is the useful primitive: one extraction prompt/question pack against one input file or stdin. But it does not expose Gemini thinking controls even though the source default is `gemini-3-flash`, where we want minimal thinking for cheap, fast extraction.

`minerva extract-many` is misleading. It asks multiple questions against the same document by making one Gemini call per question. That gives per-question isolation, but it duplicates the full document context for every question and is the wrong primitive for extraction at scale. If we want multiple questions against one file, a single `extract` call with a question pack is usually simpler and cheaper.

The missing command is `extract-files`: one extraction prompt/question pack applied across many files with controlled concurrency and durable per-file outputs.

---

## Target command model

### 1. `minerva extract`

One input source, one model call, one output.

Supported examples:

```bash
minerva extract "What does management say about churn?" --file source.md
minerva extract --questions-file questions.md --file source.md
cat source.md | minerva extract --questions-file questions.md
```

Rules:

- Accept either a positional prompt/question, `--questions-file`, or both.
- Treat `--questions-file` as a literal prompt/question pack, not one question per line.
  - Preserve markdown headings, bullets, numbering, and internal blank lines.
  - Trim only outer whitespace.
- When both positional prompt and `--questions-file` are provided, compose one prompt with clear sections and make a single model call.
- Add `--thinking <level>`.
- Default to `--thinking minimal` when the model is `gemini-3-flash`.
- Continue supporting `--model` and `--max-tokens`.
- Do not make one model call per question.
- Do not read stdin when `--file` is provided; the current unconditional stdin read can hang in an interactive terminal.

### 2. Remove `minerva extract-many`

Remove the command registration, run-chain dispatcher, tests, and docs/tool references for `extract-many`.

Replacement guidance:

- Many questions over one file: `minerva extract -q questions.md -f source.md`.
- One or more questions over many files: `minerva extract-files -q questions.md -f ...`.

Hidden references to remove or update:

- [extract.py](project-minerva/src/harness/commands/extract.py) help text, callbacks, dispatch helpers, and alternatives.
- [commands/__init__.py](project-minerva/src/harness/commands/__init__.py) registration.
- [cli.py](project-minerva/src/harness/cli.py) run-chain dispatcher and `_available_root_commands()` manual command list.
- [fileinfo.py](project-minerva/src/harness/commands/fileinfo.py) recommendations.
- Historical docs matched by `rg "extract-many" docs src tests`.

### 3. Add `minerva extract-files`

Many input files, same extraction prompt/question pack, one model call per file.

Proposed syntax:

```bash
minerva extract-files "What does management say about churn?" \
  -f 'data/sources/**/*.md' \
  -o data/extractions/churn \
  --concurrency 4

minerva extract-files -q questions.md \
  -f oracle/income.md -f microsoft/q3-call.md -f amazon/q1-call.md \
  -o data/extractions/cross-company

minerva extract-files -q questions.md \
  -F selected-files.txt \
  -o data/extractions/curated-cross-company

minerva extract-files --questions-file questions.md \
  --files 'data/sources/**/*.md' \
  --out data/extractions/source-summary \
  --model gemini-3-flash \
  --thinking minimal
```

Rules:

- Accept either a positional prompt/question, `--questions-file`, or both.
- Treat `--questions-file` exactly like `extract`: literal markdown prompt pack, formatting preserved.
- Support repeated `--files` / `-f` values and glob patterns.
- Support `--files-from LIST` / `-F LIST` for curated files scattered across unrelated folders; the list file is newline-delimited, supports comments with `#`, and resolves relative entries from the list file's directory.
- Expand globs deterministically and sort by path.
- Deduplicate paths after expansion.
- Fail cleanly if a glob matches nothing, unless we later add an explicit `--allow-empty` flag.
- Require `--out` for MVP. Skip `--stdout`; multiple file outputs to stdout are noisy and easy to misuse.
- Do not combine all files into one giant prompt.
- Treat `extract-files` as UTF-8 text/markdown extraction only. PDFs, spreadsheets, images, archives, and binary/non-UTF-8 files should produce clear per-file manifest failures telling the user to convert first or use a PDF/image-specific tool.
- Use bounded concurrency; default `--concurrency 4`, lower bound `1`.
- Fail the command if any file extraction fails, but keep successful outputs and write an error summary.

Output layout:

- Write one markdown file per input file under `--out`.
- Preserve enough relative path context to avoid duplicate basenames.
- Recommended helper: compute the common parent of all input files, then mirror relative paths under `--out`, replacing the extension with `.md`.
  - Example: `data/sources/10-K/2025/item-1.md` -> `out/10-K/2025/item-1.md` if common parent is `data/sources`.
  - If two inputs still collide after normalization, append a short stable hash suffix.
- Write a manifest file under `--out`, e.g. `manifest.json`, containing source path, output path, status, error if any, model, thinking level, timestamp, and prompt/questions-file metadata.
- Timestamp should use UTC ISO-8601 to avoid timezone ambiguity.
- Default overwrite policy: fail if an output file already exists unless `--force` is passed. This avoids quietly clobbering extraction artifacts.

---

## Gemini thinking design

Use the installed `google-genai` support for `GenerateContentConfig.thinking_config` / `ThinkingConfig`.

The implementation must be model-aware. Gemini 3 and Gemini 2.5 do not use the same thinking controls.

### Gemini 3 policy

For `gemini-3*` models, use `thinking_level`:

| CLI level | Gemini 3 config |
| --- | --- |
| `minimal` | `thinking_config.thinking_level = "MINIMAL"` |
| `low` | `thinking_config.thinking_level = "LOW"` |
| `medium` | `thinking_config.thinking_level = "MEDIUM"` |
| `high` | `thinking_config.thinking_level = "HIGH"` |

Policy:

- Default `gemini-3-flash` to `minimal`.
- Do not advertise true `off` for Gemini 3 Flash; Gemini 3 Flash's closest cheap setting is `minimal`.
- If a user passes `--thinking off` with a Gemini 3 model, fail clearly or normalize to `minimal` with explicit messaging. Recommendation: fail clearly so users do not think thinking was fully disabled.
- Do not set `thinking_budget` for Gemini 3.

### Gemini 2.5 policy

For `gemini-2.5*` models, use `thinking_budget`:

| CLI level | Gemini 2.5 config |
| --- | --- |
| `off` | `thinking_config.thinking_budget = 0` |
| `adaptive` | `thinking_config.thinking_budget = -1` |

For fixed low/medium/high on Gemini 2.5, either map to documented budgets after verifying model limits or reject with a clear error. Recommendation for MVP: support only `off` and `adaptive` for Gemini 2.5 until budget values are deliberately chosen.

### Non-Gemini-3/2.5 policy

For other Gemini model strings:

- If `--thinking` is omitted, omit `thinking_config`.
- If `--thinking` is provided, either map only when known-safe or fail clearly.
- Never silently send unsupported thinking config.

### Implementation shape

Create small helpers and test them without hitting Gemini:

- `_resolve_default_thinking(model, explicit_thinking)`
- `_build_thinking_config(model, thinking)`
- `_build_generate_config(model, max_tokens, thinking)`

Prefer constructing `google.genai.types.GenerateContentConfig` and `google.genai.types.ThinkingConfig`, or at least assert against the exact serialized shape. Never set both `thinking_level` and `thinking_budget` in the same request.

If the selected model rejects a thinking config, surface the API error clearly. Do not silently retry without thinking unless Anton explicitly asks for fallback behavior later.

---

## Parser design

The current `minerva run` dispatcher is too primitive for the target surface.

Problems to fix:

- `extract.dispatch()` assumes `args[0]` is the question, so `extract --questions-file q.md --file doc.md` cannot work.
- `parse_flag_args()` overwrites repeated flags, so it cannot support repeated `--files` values.
- Flag ordering is brittle; agents should be able to put flags before or after the positional prompt.

Plan:

- Introduce command-local argument parsing helpers for extraction commands instead of stretching `parse_flag_args()`.
- Support flags before and after the positional prompt.
- Support repeated `--files` for `extract-files`.
- Return clean errors on unknown flags, missing flag values, missing question source, missing file source, and invalid thinking level before any Gemini call.

---

## TDD plan

### Phase 0 — Capture current behavior before changing it

Add or update tests that pin the existing surface area we intend to preserve:

- `extract` reads `--file` and sends document text to `_generate_answer`.
- `extract` reads stdin only when `--file` is omitted.
- `extract` returns a helpful error when neither input nor question source exists.
- `extract` honors `--model` and `--max-tokens`.

These tests are the guardrail while removing `extract-many`.

### Phase 1 — Add literal question-pack support to `extract`

Write failing tests first:

- `extract_command` accepts `questions_file` and preserves the file's internal markdown formatting.
- Positional prompt + `--questions-file` are both included in a single model call under clear headings.
- Empty/whitespace-only `--questions-file` fails cleanly.
- Missing `--questions-file` path fails cleanly.
- CLI callback accepts `--questions-file` without a positional question.
- Run-chain dispatch supports `extract --questions-file questions.md --file source.md`.
- Flags work before and after the positional prompt.
- Quoted prompts with spaces survive dispatch parsing.

Then implement:

- Replace line-based `_merge_questions` semantics with `_build_question_pack` / `_read_question_pack` semantics.
- Change `_generate_answer` to receive a prompt/question-pack string, not a single conceptual question.
- Update `SYSTEM_PROMPT` wording so it supports one or many questions and asks for clearly labeled answer sections when the prompt contains multiple questions.

### Phase 2 — Add thinking support to `extract`

Write failing tests first:

- Default `extract` with model `gemini-3-flash` resolves to `thinking="minimal"`.
- Explicit `--thinking minimal|low|medium|high` on `gemini-3*` maps to `thinking_level` and never sets `thinking_budget`.
- Explicit `--thinking off` on `gemini-3*` fails clearly before calling Gemini.
- Explicit `--thinking off|adaptive` on `gemini-2.5*` maps to `thinking_budget` and never sets `thinking_level`.
- Invalid `--thinking nonsense` returns a clean CLI error before calling Gemini.
- Non-default model with omitted `--thinking` omits `thinking_config` unless a known policy says otherwise.

Then implement:

- Add `thinking` parameter through CLI callback, run-chain dispatch, `extract_command`, and `_generate_answer`.
- Add `_resolve_default_thinking`, `_build_thinking_config`, and `_build_generate_config` helpers.
- Update `client.models.generate_content(..., config=...)` to include both `max_output_tokens` and optional `thinking_config`.

### Phase 3 — Remove `extract-many`

Write failing/removal tests first:

- Root command registry no longer includes `extract-many`.
- Run-chain dispatcher no longer recognizes `extract-many`.
- `_available_root_commands()` no longer advertises `extract-many`.
- Help text and docs no longer recommend `extract-many`.
- Old `test_extract_many_*` tests are deleted or replaced with `extract --questions-file` tests.

Then implement:

- Remove `extract_many_app` registration from [commands/__init__.py](project-minerva/src/harness/commands/__init__.py).
- Remove `extract-many` dispatcher entry and manual availability entry from [cli.py](project-minerva/src/harness/cli.py).
- Delete `dispatch_many`, `extract_many_command`, and `_gather_answers` if no longer used.
- Update examples in code help strings, [fileinfo.py](project-minerva/src/harness/commands/fileinfo.py), and docs.

### Phase 4 — Add `extract-files`

Write failing tests first:

- Command requires at least one question source and at least one file source.
- Repeated `--files` values are accepted.
- Glob expansion is sorted, deduped, and fails on no matches.
- One Gemini call is made per file, not per question.
- `--questions-file` works exactly like `extract`, preserving formatting.
- `--out` creates one markdown output per input file.
- Output path helper mirrors relative input paths and avoids duplicate-basename collisions.
- Existing output files fail unless `--force` is passed.
- `--concurrency 1` runs deterministically and is easy to test.
- Partial failure writes successful outputs, records failures in the manifest, and exits non-zero.
- `--model`, `--thinking`, and `--max-tokens` are passed through to each extraction.
- Run-chain dispatch supports `extract-files`.
- File read errors and likely-binary/unreadable text files produce per-file failures, not total crashes.

Then implement:

- Add a new Typer command app, probably in `src/harness/commands/extract.py` unless it grows large enough to split.
- Register it as `extract-files` in `commands/__init__.py`.
- Add run-chain dispatcher support; extraction commands should stay composable in `minerva run`.
- Create helpers for file expansion, output path mapping, manifest writing, and bounded async execution.
- Use `asyncio` + semaphore for bounded concurrency.

### Phase 5 — Docs and migration cleanup

Update:

- [14-evidence-v2-quickstart.md](project-minerva/docs/14-evidence-v2-quickstart.md) to replace `extract-many` with `extract --questions-file` and `extract-files`.
- [05-morning-market-brief-cli-gap-analysis.md](project-minerva/docs/05-morning-market-brief-cli-gap-analysis.md), [06-collect-evidence-analyze-business-cli-plan.md](project-minerva/docs/06-collect-evidence-analyze-business-cli-plan.md), and [16-analyze-business-wiki-integration-plan.md](project-minerva/docs/16-analyze-business-wiki-integration-plan.md) where they mention `extract-many`.
- CLI help examples in `EXTRACT_HELP`.
- Fileinfo recommendations.

Migration note to keep in the plan and release notes, not necessarily in user-facing command help forever:

```text
`extract-many` was removed. Use `extract --questions-file` for many questions over one file, or `extract-files --questions-file` for the same question pack over many files.
```

---

## Acceptance gates

Before calling this done:

```bash
uv run pytest tests/test_harness/test_extract.py -q
uv run pytest tests/test_harness/test_cli.py -q
uv run pytest tests/test_harness -q
uv run python -m compileall src/harness
uv run minerva --help
uv run minerva extract --help
uv run minerva extract-files --help
rg "extract-many" src tests docs --glob '!docs/18-minerva-extract-cli-tdd-plan.md'
```

Expected `rg "extract-many"` result after migration: no source/test hits, and only deliberate historical migration notes if we choose to keep them. The plan doc itself is excluded because it explains the removal.

If Gemini credentials are available, run one live smoke test against a tiny fixture:

```bash
printf 'Revenue was $10M. Churn improved.' > /tmp/minerva-extract-smoke.md
uv run minerva extract "What revenue is stated?" \
  --file /tmp/minerva-extract-smoke.md \
  --model gemini-3-flash \
  --thinking minimal
```

Also verify the installed `minerva` entrypoint after packaging/update, because the global CLI currently can lag repo source.

---

## Decisions made after audit

- `--questions-file` means literal markdown prompt pack, not one question per line.
- `--stdout` for `extract-files` is not MVP.
- Gemini thinking config must be model-aware: Gemini 3 uses `thinking_level`; Gemini 2.5 uses `thinking_budget`.
- `--thinking off` should not be presented as supported for Gemini 3 Flash.
- Parser work is part of the feature, not incidental cleanup.
- `extract-files` writes a manifest and requires `--out`.
- Existing outputs are protected unless `--force` is passed.

---

## Implementation order summary

1. Tests for existing `extract` behavior and stdin-read fix.
2. Tests for `extract --questions-file` literal prompt-pack behavior.
3. Implement `extract --questions-file` as a single-call prompt pack.
4. Tests for model-aware `--thinking` config.
5. Implement Gemini thinking config.
6. Remove `extract-many` tests/registration/dispatch/help references.
7. Tests for `extract-files` parsing, file expansion, output paths, manifest, and partial failure behavior.
8. Implement `extract-files` with bounded concurrency and durable outputs.
9. Update docs and run acceptance gates.
