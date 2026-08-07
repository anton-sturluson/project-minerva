# Morning brief synthesis contract

The collection script has already populated prepared evidence, `news`, and `prices`. Do not repeat collection, browse the web, start another agent or session, or post to Slack with a messaging tool. After summary completion, the only additional model work permitted is the fixed Terra selection pass in Section 3; perform the orchestration, synthesis, and writing in this run.

## 1. Validate the input

Read the `synthesis-handoff.json` path printed by `scripts/run_morning_brief.sh`. Treat this prompt as the versioned synthesis contract. Before accessing the database, require a JSON object with `status` set to `ready`; require `date`, `window_start`, `window_end`, `db`, `prepared_evidence`, `evidence_stats`, `collector_stats`, `holdings_path`, `watchlist_path`, `instructions`, and `slack_brief_output` with the expected types; and require `instructions` to identify this prompt. Stop with a concise schema/version error if validation fails. Do not infer missing values.

Use `window_start` and `window_end` exactly as provided with today's collected data.

## 2. Complete pending summaries safely

- Select eligible `news` rows using `published_at` as UTC epoch seconds in the fixed half-open interval from `window_start` inclusive to `window_end` exclusive. The timestamps represent the previous run date at 04:00 through the run date at 04:00 in `America/New_York`. Do not use calendar-date prefix matching or change these bounds.
- Process only rows where `content` is non-empty and `summary` is NULL or blank.
- For each row, pipe `content` on stdin to:

```bash
uv run minerva summarize --model gemini-3.6-flash --thinking high
```

- Run no more than four summarization subprocesses at once. Keep article content and generated summaries in memory; do not write article or summary files.
- If any summarization fails, do not write a partial batch. Report the failure count and artifact paths concisely.
- After all calls succeed, persist summaries with parameter binding in one SQLite transaction. Update by `article_key` only where the summary is still NULL or blank.
- Re-query the same fixed half-open window and require zero eligible blank summaries before selection. Reruns must be idempotent.

## 3. Run the Terra selection pass without loading summaries

Do not read article summaries into your context. Use shell subprocesses for all batch export and grounding checks:

1. Create one temporary selection directory and arrange unconditional cleanup on success or failure. Resolve the versioned selection prompt at `scripts/prompts/morning_brief_selection.md`; do not copy, modify, or replace it.
2. Run one short Python subprocess that reads the handoff, holdings, and watchlist and queries SQLite directly. Bind the exact epoch bounds derived from `window_start` and `window_end`; select every row with non-empty `content` and a complete non-blank `summary`, ordered by `published_at, article_key`. Require this row count to equal `evidence_stats.eligible_rows` and require the Section 2 blank-summary count to be zero.
3. In that subprocess, partition the ordered rows deterministically into `min(4, article_count)` contiguous batches whose sizes differ by at most one. For a zero-article window, write one empty batch so the fixed command still runs. Write compact `batch-01.json` through at most `batch-04.json` in the temporary directory. Every batch must include the holdings/watchlist identities under `portfolio_watchlist` and an `articles` array; every article must contain exactly `article_key`, `url`, `title`, `source`, `published_at`, and `summary`, with every queried article appearing exactly once. The subprocess must emit nothing to stdout and must never print summaries or batch contents.
4. Do not use `read`, `cat`, `jq`, or any other context-loading operation on the batch files. Invoke the existing extractor exactly once, letting it parallelize the temporary files:

```bash
uv run minerva extract-files \
  --questions-file "$SELECTION_PROMPT" \
  --files "$SELECTION_TMP/batch-*.json" \
  --out "$SELECTION_TMP/results" \
  --model gpt-5.6-terra \
  --thinking high \
  --concurrency 4
```

5. After that single command succeeds, use another short Python subprocess—not your context—to require one successful manifest entry and one strict JSON result per exported batch. For each result, validate the selection-prompt schema and verify every returned article key exists in its paired batch and every returned URL belongs to those selected batch records. Emit no batch data or summaries to stdout. If export, extraction, or grounding fails, stop with one concise selection failure naming the failed phase.
6. Only after the grounding check succeeds, read the small Terra result files into your context. Do not read the batch inputs, manifest, excluded summaries, or any other article summaries. Across the results, group duplicate or follow-up coverage into one development, deduplicate keys and URLs while preserving their first deterministic occurrence, and rank the developments for the brief. The verified union of selected article keys is an immutable ceiling: do not query, add, or restore any excluded article, key, URL, or development. Clearly label rumors and third-party interpretations.
7. Remove the entire temporary selection directory after the result files have been consumed. Do not persist selection outputs or alter the handoff.

## 4. Write the Slack brief

Write the canonical `slack_brief_output` from the verified Terra selections. Do not create a separate report or memo.

Write exactly these three sections in the order shown, with no other text or sections:

```text
_Crawler:_ {total articles} — {source} {count} · {source} {count} · ...; {successful}/{total} collectors succeeded, {failed} failed.

_Portfolio / Watchlist Events_
• _{Company/ticker — takeaway}:_ Explain what happened, the important facts, and why it matters. Cite the original sources.

_Worth Knowing Today_
• _{Investor takeaway}:_ Explain the development, why it matters to investors, and any important uncertainty. Cite the original sources.
```

If nothing material occurred for the portfolio or watchlist, use the approved fallback:

```text
• No material portfolio or watchlist developments during the collection period.
```

Get final article and per-source counts from the verified fixed-window query and collector successes and failures from `collector_stats`. Cite factual claims with the direct source URLs in Terra's verified selections, linking to original articles rather than `finnhub.io/api/news` proxy pages when possible. Do not use Markdown headings or tables. Do not run a deterministic Slack validator or rewriter.

## 5. Return the result

Do not call Slack or any messaging tool. Return the exact contents of `slack_brief_output`, with no preamble, commentary, or code fence, so the cron delivery layer posts it once. If a required step explicitly listed in Sections 1-4 fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief. Only those failures are fatal. Do not invent or invoke validation commands not listed in this contract; if an unlisted command fails, correct or skip it rather than aborting when `slack_brief_output` can still be produced and read.
