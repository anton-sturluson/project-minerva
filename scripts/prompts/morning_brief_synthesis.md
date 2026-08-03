# Morning brief synthesis contract

The collection script has already populated prepared evidence, `news`, and `prices`. Do not repeat collection, browse the web, delegate synthesis, or post to Slack with a messaging tool.

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
- Re-query the same fixed half-open window and require zero eligible blank summaries before synthesis. Reruns must be idempotent.

## 3. Select the developments

Read the prepared-evidence JSON, relevant `prices` rows, and the complete summary of every article from the collection period before deciding what to include. Do not select from headlines or URLs alone. Confirm that the number of summaries read matches the total article count in `evidence_stats`; otherwise stop and report both counts and the diagnostic artifact path.

Create a ranked list of distinct material developments. Combine duplicate, syndicated, and follow-up articles about the same development, then use this list when writing the Slack brief.

- Include every development that offers a concrete investor takeaway. Do not omit a qualifying item merely for brevity or impose an arbitrary bullet limit.
- Portfolio / Watchlist Events may cover companies listed in `holdings_path` or `watchlist_path`. Do not use the broader company universe or promote an unrelated company because of a ticker-text match.
- Worth Knowing Today may include material market, macro, policy, industry, technology, or business developments, including slightly adjacent items.
- Omit duplicates, irrelevant ticker matches, and low-substance commentary. Clearly label rumors and third-party interpretations.
- Prefer company filings and official sources, followed by WSJ, Economist, and Reuters.

## 4. Write the Slack brief

Write `slack_brief_output` from the ranked list. Do not create a separate report or memo.

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

Get final article and per-source counts from the verified window query and collector successes and failures from `collector_stats`. Cite factual claims with direct source URLs from SQLite, linking to original articles rather than `finnhub.io/api/news` proxy pages when possible. Do not use Markdown headings or tables.

## 5. Return the result

Do not call Slack or any messaging tool. Return the exact contents of `slack_brief_output`, with no preamble, commentary, or code fence, so the cron delivery layer posts it once. If a required phase fails, return one concise failure message naming the phase and diagnostic artifact path instead of a partial brief.
