# Morning brief synthesis contract

Prepared evidence, `news`, and `prices` are already populated. Do not run `scripts/run_morning_brief.sh` or `portfolio sync`, repeat collection, browse the web, or start another agent or session. After summaries, only the Section 3 selection pass may use a model; complete orchestration, premium-source auto-advance, synthesis, and writing in this run.

## 1. Validate the input

Read this run’s `synthesis-handoff.json`; the collection script wrote it before starting this agent. Treat this prompt as the versioned synthesis contract. Before accessing the database, require a JSON object with `status` set to `ready`; require `date`, `window_start`, `window_end`, `db`, `prepared_evidence`, `evidence_stats`, `collector_stats`, `holdings_path`, `watchlist_path`, `instructions`, and `slack_brief_output` with the expected types; and require `instructions` to identify this prompt. On failure, stop with a concise schema/version error; do not infer missing values.

Use `window_start` and `window_end` exactly as provided.

## 2. Complete pending summaries safely

- Select `news` rows with `published_at` in UTC epoch seconds in the half-open interval [`window_start`, `window_end`). These bounds represent 04:00 on the previous run date through 04:00 on the run date in `America/New_York`. Do not use calendar-date prefix matching or change the bounds.
- Process only rows where `content` is non-empty and `summary` is NULL or blank.
- For each row, pipe `content` on stdin to:

```bash
uv run minerva summarize --model gpt-6-luna --thinking medium
```

- Run at most four summarization subprocesses at once; keep content and summaries in memory.
- If any summarization fails, do not write a partial batch. Report the failure count and artifact paths concisely.
- After all calls succeed, persist summaries with parameter binding in one SQLite transaction, updating by `article_key` only where the summary is still NULL or blank.
- Re-query the same fixed half-open window and require zero eligible blank summaries before selection. Reruns must be idempotent.

## 3. Select non-premium articles with Sol 6.1 and auto-advance premium sources

Do not read the batch inputs into your context.

1. Create a temporary directory.
2. Create `$SELECTION_TMP/relevance-prompt.md` by copying `scripts/prompts/morning_brief_selection.md` and appending only the top-level `universe` array as `PORTFOLIO_UNIVERSE_JSON` from the validated handoff’s exact `prepared_evidence` path. Use short inline Python or `jq` without reading the source into your context.

3. Use `sqlite3` and standard shell tools to export every complete summary in the fixed window whose `source` is not exactly `wsj` or `economist` into JSONL batches of 30. Each line must contain `index`, `article_key`, `url`, `title`, `source`, `published_at`, and `summary`. Set `index` to the 1-based line position, restarting at 1 in each batch; keep batches unchanged until decoding. In `$SELECTION_TMP/auto-advanced-keys.jsonl`, export one `{"article_key":"..."}` object per complete summary whose `source` is exactly `wsj` or `economist`. Do not include those premium-source rows in the selection model's batch inputs.
4. If batches exist, run the extractor once with concurrency equal to the batch count; otherwise skip the selection pass:

```bash
BATCH_COUNT=$(find "$SELECTION_TMP" -name 'batch-*' -type f | wc -l | tr -d ' ')
uv run minerva extract-files \
  --questions-file "$SELECTION_TMP/relevance-prompt.md" \
  --files "$SELECTION_TMP/batch-*" \
  --out "$SELECTION_TMP/results" \
  --model gpt-6.2-sol \
  --max-tokens 100000 \
  --thinking high \
  --concurrency "$BATCH_COUNT"
```

5. Stop if extraction or index resolution fails. Do not use model rationales in synthesis.

```bash
uv run minerva brief resolve-selection --selection-dir "$SELECTION_TMP"
```

Use `selected-keys.jsonl` for the verified union. Auto-advance means eligible for final main-agent review, not guaranteed publication. Query titles and sources for the union first. Read summaries for first-party sources (including filings and IR), regulators, WSJ, Economist, Reuters, and other clearly high-quality reporting. For Yahoo, Benzinga, Seeking Alpha, Chartmill, Fintel, and similar sources, use the title unless the article appears to contain a unique material fact or genuine variant perception. Deduplicate overlapping coverage using the strongest original evidence or incremental insight. Classify portfolio/watchlist items using `holdings_path` and `watchlist_path`, and rank the results. Do not query articles excluded by the selection model unless their source is exactly `wsj` or `economist`, or the bounded shortfall review in Section 4 requires it. Label rumors and third-party interpretations.
6. Before writing, read up to five most recent previous `slack-brief.md` outputs in dated sibling run directories. Exclude developments already covered unless today's evidence adds a material new fact; if retained, write only the update.
7. Delete the temporary directory after selection.

## 4. Write the Slack brief

Write the canonical `slack_brief_output` from the verified union and any qualifying additions from the bounded shortfall review below, with exactly these four sections in order and no other text or sections. Do not create a separate report or memo:

```text
_Crawler:_ {total articles} — {source} {count} · {source} {count} · ...; {successful}/{total} collectors succeeded, {failed} failed.

_Portfolio / Watchlist Events_
• _{Company/ticker — takeaway}:_ Explain what happened, the important facts, and why it matters. Cite the original sources.

_Worth Knowing Today_
• _{Investor takeaway}:_ {Concise helpful explanation with original-source links.}

_Political / Macro_
• _{Investor takeaway}:_ {Concise helpful explanation with original-source links.}
```

For `_Worth Knowing Today_`, select exactly 10 distinct, evidence-backed non-portfolio developments useful to a long-term investor. Include durable business, technological, social, demographic, labor, institutional, or resource shifts that can materially reshape demand, productivity, costs, incentives, or risk. Exclude Political / Macro events, duplicates, and filler; do not split one development into multiple items to reach 10.

If the initial shortlist contains fewer than 10 qualifying developments after classification and deduplication, perform one bounded shortfall review of the remaining complete summaries in the same fixed window. Query titles and sources first, then read the summaries of plausible candidates, including articles the selection model excluded. Look across the full range of useful long-term topics above rather than restricting the section to major corporate announcements. Apply the same evidence, source-quality, prior-coverage, and no-filler standards; use no additional model calls, web browsing, collection, or older articles. Retain each added article's key and original source URL for traceability.

Before writing, count the top-level bullets between `_Worth Knowing Today_` and `_Political / Macro_` and require exactly 10. If the available evidence still cannot support 10 qualifying developments, stop and return a concise selection failure stating the qualifying count and the `prepared_evidence` artifact path. Do not publish a shorter normal brief or invent items to satisfy the count.

Include up to five distinct, evidence-backed event-driven developments in `_Political / Macro_` that materially change the outlook for growth, inflation, rates, trade, regulation, resource supply, or geopolitical tail risk. Exclude routine political activity, and do not duplicate any development from `_Worth Knowing Today_`.

If nothing material occurred for the portfolio or watchlist:

```text
• No material portfolio or watchlist developments during the collection period.
```

If no event qualifies for `_Political / Macro_`:

```text
• No qualifying political or macro developments during the collection period.
```

Get final article and per-source counts from the verified fixed-window query, and collector successes and failures from `collector_stats`. Cite factual claims with direct source URLs from selected SQLite rows; link to original articles rather than `finnhub.io/api/news` proxy pages when possible. Do not use Markdown headings or tables.

## 5. Return the result

Do not call Slack or any messaging tool. Return the exact contents of `slack_brief_output`, with no preamble, commentary, or code fence. If a required step in Sections 1-4 fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief. Do not run a Slack validator, rewriter, or other unlisted validation command; correct or skip failures outside the required steps when `slack_brief_output` can still be produced.
