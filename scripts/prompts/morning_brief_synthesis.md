# Morning brief synthesis contract

The collection script has already populated prepared evidence, `news`, and `prices`. Do not repeat collection, browse the web, or start another agent or session. After summary completion, the only additional model work permitted is the Terra selection pass in Section 3; perform the orchestration, synthesis, and writing in this run.

## 1. Validate the input

Read the `synthesis-handoff.json` path printed by `scripts/run_morning_brief.sh`. Treat this prompt as the versioned synthesis contract. Before accessing the database, require a JSON object with `status` set to `ready`; require `date`, `window_start`, `window_end`, `db`, `prepared_evidence`, `evidence_stats`, `collector_stats`, `holdings_path`, `watchlist_path`, `instructions`, and `slack_brief_output` with the expected types; and require `instructions` to identify this prompt. Stop with a concise schema/version error if validation fails. Do not infer missing values.

Use `window_start` and `window_end` exactly as provided with today's collected data.

## 2. Complete pending summaries safely

- Select eligible `news` rows using `published_at` as UTC epoch seconds in the fixed half-open interval from `window_start` inclusive to `window_end` exclusive. The timestamps represent the previous run date at 04:00 through the run date at 04:00 in `America/New_York`. Do not use calendar-date prefix matching or change these bounds.
- Process only rows where `content` is non-empty and `summary` is NULL or blank.
- For each row, pipe `content` on stdin to:

```bash
uv run minerva summarize --model gpt-5.6-luna --thinking medium
```

- Run no more than four summarization subprocesses at once. During this phase, keep article content and generated summaries in memory.
- If any summarization fails, do not write a partial batch. Report the failure count and artifact paths concisely.
- After all calls succeed, persist summaries with parameter binding in one SQLite transaction. Update by `article_key` only where the summary is still NULL or blank.
- Re-query the same fixed half-open window and require zero eligible blank summaries before selection. Reruns must be idempotent.

## 3. Select the articles with Terra

Do not read the batch inputs into your context.

1. Create a temporary directory.
2. Use `sqlite3` and standard shell tools to export every complete summary in the fixed window directly into JSONL batches of 30 articles each. Each line must contain `article_key`, `url`, `title`, `source`, `published_at`, and `summary`.
3. If batches exist, count them and run the extractor once with concurrency equal to the batch count; otherwise skip Terra selection:

```bash
BATCH_COUNT=$(find "$SELECTION_TMP" -name 'batch-*' -type f | wc -l | tr -d ' ')
uv run minerva extract-files \
  --questions-file scripts/prompts/morning_brief_selection.md \
  --files "$SELECTION_TMP/batch-*" \
  --out "$SELECTION_TMP/results" \
  --model gpt-5.6-terra \
  --thinking high \
  --concurrency "$BATCH_COUNT"
```

4. Extract only the non-null `article_key` values from Terra's JSONL results; do not use Terra's rationales in synthesis. Query titles and sources for the selected keys first. Read summaries for first-party sources (including filings and IR), regulators, WSJ, Economist, Reuters, and other clearly high-quality reporting. For Yahoo, Benzinga, Seeking Alpha, Chartmill, Fintel, and similar sources, use the title unless the article appears to contain a unique material fact or genuine variant perception. When several articles cover the same event, prefer the highest-quality source. Combine duplicate developments, classify portfolio/watchlist items using `holdings_path` and `watchlist_path`, and rank the results. Do not query excluded articles. Clearly label rumors and third-party interpretations.
5. Before writing, read up to five of the most recent previous `slack-brief.md` outputs in the dated sibling run directories. Exclude developments already covered unless today's evidence adds a material new fact; if retained, write only the update.
6. Delete the temporary directory after selection.

## 4. Write the Slack brief

Write the canonical `slack_brief_output` from the verified Terra selections. Do not create a separate report or memo.

Write exactly these three sections in the order shown, with no other text or sections:

```text
_Crawler:_ {total articles} — {source} {count} · {source} {count} · ...; {successful}/{total} collectors succeeded, {failed} failed.

_Portfolio / Watchlist Events_
• _{Company/ticker — takeaway}:_ Explain what happened, the important facts, and why it matters. Cite the original sources.

_Worth Knowing Today_
• _{Investor takeaway}:_ {Concise helpful explanation with original-source links.}
```

For `_Worth Knowing Today_`, select exactly 10 distinct non-portfolio events that are most useful for becoming a better investor. They may be company-specific or broader. Prefer developments with transferable lessons about economics, competition, incentives, capital allocation, regulation, technology, macro conditions, or risk.

If nothing material occurred for the portfolio or watchlist, use the approved fallback:

```text
• No material portfolio or watchlist developments during the collection period.
```

Get final article and per-source counts from the verified fixed-window query and collector successes and failures from `collector_stats`. Cite factual claims with the direct source URLs from the selected SQLite rows, linking to original articles rather than `finnhub.io/api/news` proxy pages when possible. Do not use Markdown headings or tables.

## 5. Return the result

Do not call Slack or any messaging tool. Return the exact contents of `slack_brief_output`, with no preamble, commentary, or code fence, so the cron delivery layer posts it once. If a required step in Sections 1-4 fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief. Do not run a Slack validator, rewriter, or other unlisted validation command; correct or skip failures outside the required steps when `slack_brief_output` can still be produced.
