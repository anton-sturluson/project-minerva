# Morning brief synthesis contract

The collection script has already populated prepared evidence, `news`, and `prices`. Do not repeat collection, browse the web, delegate synthesis or writing, or post to Slack with a messaging tool. The one permitted delegated call is `uv run minerva brief select-news`, which runs a fixed Terra selection pass and writes the shortlist you must consume.

## 1. Validate the input

Read the `synthesis-handoff.json` path printed by `scripts/run_morning_brief.sh`. Treat this prompt as the versioned synthesis contract. Before accessing the database, require a JSON object with `status` set to `ready`; require `date`, `window_start`, `window_end`, `db`, `prepared_evidence`, `evidence_stats`, `collector_stats`, `holdings_path`, `watchlist_path`, `instructions`, `article_shortlist`, and `slack_brief_output` with the expected types; and require `instructions` to identify this prompt. Stop with a concise schema/version error if validation fails. Do not infer missing values.

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

## 3. Run the Terra selection pass

Invoke the fixed selection command once, passing the exact handoff path:

```bash
uv run minerva brief select-news --handoff "$SYNTHESIS_HANDOFF_PATH"
```

That command reads every complete article summary in the fixed window from SQLite, splits them into at most four balanced batches, and calls `uv run minerva extract-files --model gpt-5.6-terra --thinking high --concurrency 4` with the versioned selection prompt. On success it writes the JSON shortlist to the handoff's `article_shortlist` path. Do not retry, tune, or replace this command. If it fails, stop with a concise failure message and cite the handoff and shortlist paths.

Read `article_shortlist` after the command exits. The shortlist has:

- `status` equal to `ready`,
- `selected_developments` — the grounded developments with `section`, `takeaway`, `materiality`, `article_keys`, and `urls`,
- `selected_articles` — the subset of window records whose keys appear in a development,
- `counts` — `input_articles`, `selected_articles`, `selected_developments`, and per-`sources`,
- `provenance` — model, thinking, prompt, and window metadata.

For the brief you may read only the shortlist and, if needed, the SQLite rows keyed by `selected_articles[*].article_key`. Do not read summaries for any other article, do not add article keys or URLs that are not in the shortlist, and do not restore anything the selection pass excluded. You may group and rank the selected developments and clearly label rumors or third-party interpretations.

## 4. Write the Slack brief

Write the canonical `slack_brief_output` from the shortlist. Do not create a separate report or memo.

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

Get final article and per-source counts from `article_shortlist.counts` (which mirrors the verified window query) and collector successes and failures from `collector_stats`. Cite factual claims with the direct source URLs the shortlist provides, linking to original articles rather than `finnhub.io/api/news` proxy pages when possible. Do not use Markdown headings or tables.

## 5. Return the result

Do not call Slack or any messaging tool. Return the exact contents of `slack_brief_output`, with no preamble, commentary, or code fence, so the cron delivery layer posts it once. If a required step explicitly listed in Sections 1-4 fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief. Only those failures are fatal. Do not invent or invoke validation commands not listed in this contract; if an unlisted command fails, correct or skip it rather than aborting when `slack_brief_output` can still be produced and read.
