# Morning Brief v2: Browser-Based News Collection

**Date:** 2026-05-03
**Status:** Revised v3 — full article collection, paragraph summaries, LGCY date bug fixed
**Branch:** main (deployed, iterating in-place)

## Context

The morning brief pipeline was restructured to add browser-based news collection from paywalled and bot-protected sources. The initial deployment (v2) proved the architecture works — parallel browser agents, shell-level parallelism, deterministic merge — but collected only headlines + 1-2 sentence summaries. This revision fixes three problems:

1. **Raw data should be full articles.** One file per article with the complete text. This is what we're paying for with WSJ/Economist subscriptions — saving 1-sentence summaries throws away the value.
2. **Summaries should have substance.** The brief agent needs paragraph-level summaries to write a good brief, not one-liners.
3. **IR date bug.** The old `minerva brief ir` CLI stamped all items with today's date instead of parsing `pubDate` from RSS. It also scraped page navigation sections as "events." Browser-based IR collection with real date awareness replaces this.

## Architecture (unchanged from v2)

```
Single cron job (6f14f630, timeout 3600s)
│
├── PHASE 1: Structured data (shell script, sequential)
│   ├── minerva portfolio sync, brief filings, brief earnings, brief market
│
├── PHASE 2: News collection (parallel openclaw agent calls)
│   ├── One agent per source, each writes raw articles + source summary
│   └── IR tickers batched in groups of 5
│
├── PHASE 3: Merge (deterministic Python script)
│   ├── Reads per-source summary files
│   ├── Writes articles.md (merged summaries for brief agent)
│   ├── Writes INDEX.md (file listing with links)
│   └── Updates LEDGER.md
│
├── PHASE 4: Evidence preparation (minerva brief prep)
│
└── PHASE 5: Brief writing (opus agent reads prepared evidence + articles.md)
```

## Data format

### Daily folder structure

```
data/02-news/2026-05-03/
├── INDEX.md                              # summary table with links
├── articles.md                           # merged paragraph summaries (brief agent reads this)
├── wsj-summary.md                        # WSJ source summary
├── economist-summary.md                  # Economist source summary
├── reuters-markets-summary.md            # Reuters source summary
├── bls-calendar-summary.md               # BLS source summary
├── bea-schedule-summary.md               # BEA source summary
├── fed-press-summary.md                  # Fed source summary
├── ir-summary.md                         # IR combined summary
├── raw/
│   ├── wsj-trump-hormuz.md              # full WSJ article
│   ├── wsj-gamestop-ebay.md             # full WSJ article
│   ├── wsj-fuel-price-airlines.md       # full WSJ article
│   ├── economist-merz-trump.md          # full Economist article
│   ├── economist-carmakers-chinese.md    # full Economist article
│   ├── reuters-sell-in-may.md           # full Reuters article
│   ├── reuters-yen-intervention.md      # full Reuters article
│   ├── bls-jolts-march-2026.md          # full BLS release
│   ├── fed-fomc-may-statement.md        # full Fed release
│   ├── ir-googl-q1-results.md           # full IR press release
│   ├── ir-avgo-10g-pon.md              # full IR press release
│   └── ...
```

### Raw article file (`raw/{source}-{slug}.md`)

One file per article. Full text. Real metadata.

```markdown
# Trump Says U.S. Will 'Guide' Stranded Ships Through Strait of Hormuz

Source: Wall Street Journal
URL: https://www.wsj.com/politics/...
Published: 2026-05-03
Collected: 2026-05-03T08:01:23Z
Section: Politics

The U.S. military will begin escorting commercial vessels through the
Strait of Hormuz as early as next week, President Trump said Saturday,
calling the plan a humanitarian gesture as discussions with Iran continue.

The arrangement, which doesn't involve escorts by U.S. warships, would
allow stranded commercial ships to transit the strait under U.S.
coordination. Several dozen cargo and tanker vessels have been stuck
near the strait since Iran effectively closed it to commercial traffic
in March...

[full article text continues]
```

### Source summary file (`{source}-summary.md`)

One per source. Paragraph-level summaries of each article collected. Written by the browser subagent.

```markdown
# WSJ — 2026-05-03

Collected: 2026-05-03T08:05:00Z
Method: browser
Status: ok
Articles saved: 12

## Trump Says U.S. Will 'Guide' Stranded Ships Through Strait of Hormuz

Section: Politics | [full article](./raw/wsj-trump-hormuz.md) | [source](https://www.wsj.com/...)

The president announced a plan to escort stranded commercial ships through the
Strait of Hormuz, calling it a humanitarian gesture. The arrangement doesn't
involve military warship escorts — it's civilian-facing U.S. coordination. Iran
hasn't responded publicly. Oil dropped on the news. Several dozen vessels have
been stuck near the strait since March. The move comes as broader nuclear
negotiations with Iran remain stalled, with Trump saying he could restart
strikes "if they misbehave."

## GameStop Is Offering to Buy eBay for $56 Billion

Section: Business / Deals | [full article](./raw/wsj-gamestop-ebay.md) | [source](https://www.wsj.com/...)

Ryan Cohen said GameStop has built a roughly 5% stake in eBay and is offering
$125 per share in cash and stock — a ~20% premium to Friday's close. This is
the latest in Cohen's strategy to transform GameStop from a meme stock into a
diversified holding company. eBay has not yet responded publicly...
```

### `articles.md` (merged summaries)

Built by `merge_news.py` from all `*-summary.md` files. This is what the opus brief agent reads.

```markdown
# News Collection — 2026-05-03

Sources: 8 | Articles: 42

---

# WSJ — 2026-05-03
[contents of wsj-summary.md]

---

# The Economist — 2026-05-03
[contents of economist-summary.md]

---

# IR — 2026-05-03
[contents of ir-summary.md]

---
...
```

## Files to change

### Modify

| File | Change |
|---|---|
| `scripts/prompts/collect_news.md` | Major rewrite: triage front page, click into articles, save full text per article, write source summary with paragraph summaries |
| `scripts/prompts/collect_news_webfetch.md` | Rewrite: save one file per item, write source summary |
| `scripts/merge_news.py` | Rewrite: read `*-summary.md` files instead of `raw/*.md`, build articles.md from summaries |
| `data/02-news/INDEX.md` | Update conventions |

### No change

| File | Reason |
|---|---|
| `scripts/run_morning_brief.sh` | Shell script unchanged — same parallelism, same agent calls |
| Cron job prompt | Already updated with timeout guidance |
| `data/02-news/news-sources.json` | Source registry unchanged |

## Browser subagent prompt (collect_news.md) — new behavior

For editorial sources (WSJ, Economist, Reuters):

1. Open the source front page in browser
2. Scan visible headlines. Decide which articles are *interesting* for our portfolio, the broader economy, or potential investment ideas. Be inclusive — err on the side of saving more, not less — but skip lifestyle fluff, sports, pure entertainment
3. For each interesting article:
   a. Click into it (or open in new tab)
   b. Extract the full article text
   c. Generate a slug from the headline (lowercase, hyphens, max ~5 words)
   d. Write to `{NEWS_DIR}/raw/{source_id}-{slug}.md` with full text and metadata
   e. Navigate back to front page (or close tab)
4. After all articles are saved, write `{NEWS_DIR}/{source_id}-summary.md` with:
   - Header metadata (collected timestamp, method, status, article count)
   - For each article: headline, section, links (to raw file and source URL), and a paragraph-length summary

For calendar/data sources (BLS, BEA, Fed):

1. Open the page in browser
2. Identify recent releases, upcoming data, policy statements
3. For each item: save full text to `raw/{source_id}-{slug}.md`
4. Write `{source_id}-summary.md` with paragraph descriptions

For IR pages:

1. Open the company IR page
2. Look for press releases, announcements, news items — **use the real publication date** visible on the page, not today's date
3. Only save items published in the last 7 days (or since last collection)
4. For each recent item: click in, save full press release text to `raw/ir-{ticker}-{slug}.md`
5. All IR summaries go into a combined `ir-summary.md`

## Merge script (merge_news.py) — new behavior

1. Read all `*-summary.md` files in `{date}/` (not raw files)
2. Parse source name, status, article count from headers
3. Concatenate summaries into `articles.md` with source separators
4. Build `INDEX.md`:
   - Summary table of sources
   - File listing of all raw articles with links
5. Append to LEDGER.md (idempotent)

## LGCY fix

The old `minerva brief ir` CLI is no longer called. Browser-based IR collection:
- Reads real publication dates from the page
- Only saves recent items (last 7 days)
- Distinguishes press releases from page navigation/section headers
- Saves full press release text, not just headlines

## Execution order

### Wave 1: Update files
- [ ] Rewrite `scripts/prompts/collect_news.md`
- [ ] Rewrite `scripts/prompts/collect_news_webfetch.md`
- [ ] Rewrite `scripts/merge_news.py`
- [ ] Update `data/02-news/INDEX.md`

### Wave 2: Test
- [ ] Test one source (WSJ) to verify full article extraction
- [ ] Test merge with new summary format
- [ ] Run full pipeline

### Wave 3: Verify
- [ ] Trigger cron test run
- [ ] Check raw articles are complete
- [ ] Check summaries have paragraph detail
- [ ] Check IR dates are correct
- [ ] Verify brief quality
