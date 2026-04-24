# Trace Analysis: AI-Media Zettel-Wiki v3 Construction

**Date:** 2026-04-23
**Session ID (main):** `5228c9c7-76ab-4ab9-b3b3-125f0dbaabb6`
**Thread:** Slack `#all-minerva` — ":thread: Test Zettel-Wiki v3 - Charlie"

---

## 1. Session Overview

- **Agent:** Charlie (agent ID: `main`)
- **Start Time:** 2026-04-23 05:26:07 UTC (01:26 EDT)
- **End Time:** 2026-04-23 05:36:57 UTC (01:36 EDT)
- **Total Wall Time:** 10 minutes 50 seconds
- **Model (main):** `anthropic/claude-opus-4-6`
- **Model (subagents):** `google/gemini-3-flash-preview` (gemini-flash)
- **Main Session Turns:** 61 assistant turns
- **Main Session Tool Calls:** 67
- **Subagent Sessions:** 15 (8 extraction + 7 structure notes)
- **Total Tool Calls (all sessions):** ~328
- **User Messages:** 1 (initial ingest request) + 14 subagent completion events
- **Slack Updates Sent:** 2 (progress + completion)

---

## 2. Execution Timeline

| Timestamp (UTC) | Tool | Key Parameters / Input | Outcome / Reasoning Summary |
| :--- | :--- | :--- | :--- |
| 05:26:11 | `read` | `~/.openclaw/skills/zettel-wiki/SKILL.md` | Skill discovery and rule verification. |
| 05:26:11 | `exec` | `find ... -maxdepth 1` | Initial folder survey of 00-ai-media. |
| 05:26:15 | `exec` | `find ... -type f -name '*.md'` | Full file listing of source corpus. |
| 05:26:15 | `read` | `references/ingest.md` | Loaded ingest workflow conventions. |
| 05:26:30 | `think` | Task strategy and source categorization. | Decided: raw evidence only from `01-data/02-structured/`. Skip `00-notes/` and `02-research/`. Plan 8 parallel subagents by source category. |
| 05:26:35 | `read` ×4 | `zettel-template.md`, `page-template.md`, `schema.md`, `audit.md` | Loaded all skill reference files in parallel. |
| 05:26:53 | `think` | Architecture and batching plan. | Designed 8 extraction batches with non-overlapping timestamp namespaces. Chose gemini-flash for subagents. |
| 05:27:00 | `message` | Slack update to Anton. | "On it. Setting up a Zettel-Wiki at `00-ai-media/wiki/`…" |
| 05:27:04 | `exec` | `mkdir -p wiki/{pages,zettels}` | Created wiki directory structure. |
| 05:27:11 | `write` ×4 | `INDEX.md`, `LEDGER.md`, `pages/INDEX.md`, `zettels/INDEX.md` | Initialized wiki infrastructure files. |
| 05:27:18 | `exec` | `ls` of all source category folders | Verified exact file counts and paths for batch assignment. |
| 05:27:33 | `think` | Subagent batch design. | Finalized 8 batch assignments with file lists and timestamp ranges. |
| 05:27:52 | `sessions_spawn` | `zettel-filings-early` (gemini-flash) | Batch 1: FY21–FY23 filings. Namespace 0200. |
| 05:28:01 | `sessions_spawn` | `zettel-filings-mid` (gemini-flash) | Batch 2: 1H FY24 + FY24 filings. Namespace 0300. |
| 05:28:12 | `sessions_spawn` | `zettel-filings-recent` (gemini-flash) | Batch 3: 1H FY25 + FY25 + 1H FY26. Namespace 0400. |
| 05:28:24 | `sessions_spawn` | `zettel-transcripts` (gemini-flash) | Batch 4: All transcripts. Namespace 0500. |
| 05:28:36 | `sessions_spawn` | `zettel-product-docs` (gemini-flash) | Batch 5: All product documentation. Namespace 0600. |
| 05:28:48 | `sessions_spawn` | `zettel-customers` (gemini-flash) | Batch 6: Customer evidence + key metrics. Namespace 0700. |
| 05:28:59 | `sessions_spawn` | `zettel-competitors` (gemini-flash) | Batch 7: Competitor analyses. Namespace 0800. |
| 05:29:13 | `sessions_spawn` | `zettel-news-metrics` (gemini-flash) | Batch 8: News + key metrics + valuation. Namespace 0900. |
| 05:29:18 | `sessions_yield` | Wait for completions. | Paused main session for parallel extraction. |
| 05:29:26–05:31:44 | `sessions_yield` ×7 | Progressive completions. | Batches completed in order: filings-early, filings-mid, filings-recent, competitors, customers, product-docs, news-metrics, then transcripts. |
| 05:31:44 | `exec` | `ls wiki/zettels \| wc -l` | Verified 109 zettels on disk. |
| 05:31:47 | `exec` | Full zettel listing | Confirmed all files present and sorted. |
| 05:32:01 | `think` | Post-extraction consolidation. | All 8 batches done, 0 failures. Planned 7 structure notes from zettel clusters. |
| 05:32:05 | `exec` | Build zettel catalog (IDs + titles + tags) | Extracted frontmatter from all 109 zettels for cluster analysis. |
| 05:32:41 | `think` | Structure note clustering and page design. | Identified 7 thematic clusters. Mapped specific zettel IDs to each cluster. Decided to use subagents for page writing + zettel backlink updates. |
| 05:33:01 | `sessions_spawn` | `page-competitive-moat` (gemini-flash) | Structure note 1: Competitive Moat & Vertical Integration. |
| 05:33:17 | `sessions_spawn` | `page-lexi-product` (gemini-flash) | Structure note 2: LEXI Product Suite & AI Technology. |
| 05:33:28 | `sessions_spawn` | `page-business-model` (gemini-flash) | Structure note 3: Business Model Transformation. |
| 05:33:38 | `sessions_spawn` | `page-financials` (gemini-flash) | Structure note 4: Financial Performance & Valuation. |
| 05:33:50 | `sessions_spawn` | `page-global-expansion` (gemini-flash) | Structure note 5: Global Expansion & Go-to-Market. |
| 05:34:00 | `sessions_spawn` | `page-customers` (gemini-flash) | Structure note 6: Customer & Market Evidence. |
| 05:34:11 | `sessions_spawn` | `page-competitive-landscape` (gemini-flash) | Structure note 7: Competitive Landscape. |
| 05:34:15 | `sessions_yield` | Wait for completions. | Paused main session for structure note writing. |
| 05:34:25–05:35:20 | `sessions_yield` ×6 | Progressive completions. | All 7 pages completed within ~60 seconds of each other. |
| 05:35:26 | `exec` | `ls wiki/pages/*.md` | Verified all 7 pages + INDEX present. |
| 05:35:32 | `exec` | Build zettel INDEX from frontmatter | Generated full zettel catalog table. |
| 05:35:42 | `exec` | Write zettel INDEX content | Wrote 109-row catalog to `zettels/INDEX.md`. |
| 05:35:51 | `write` | `pages/INDEX.md` | Updated page directory with all 7 structure notes. |
| 05:35:58 | `write` | `wiki/INDEX.md` | Updated master wiki index with final counts. |
| 05:36:09 | `write` | `wiki/LEDGER.md` | Wrote construction session audit log. |
| 05:36:14 | `exec` | Orphan audit (`grep` for missing Related sections) | Found 1 orphan: board governance zettel (202604230526). |
| 05:36:18 | `read` | `zettels/202604230526.md` | Read orphan zettel to determine correct links. |
| 05:36:23 | `edit` | `zettels/202604230526.md` | Fixed orphan: added Related links to competitive-moat and customer-evidence pages. |
| 05:36:27 | `read` | `pages/competitive-moat.md` (limit 40) | Quality spot-check of structure note. |
| 05:36:30 | `read` | `pages/financial-performance.md` (limit 30) | Quality spot-check of structure note. |
| 05:36:33 | `read` | `00-ai-media/INDEX.md` | Read parent folder index for update. |
| 05:36:39 | `edit` | `00-ai-media/INDEX.md` | Updated parent folder reference from v2 to v3 stats. |
| 05:36:54 | `message` | Completion report to Anton. | "Done. Wiki built at `00-ai-media/wiki/`. 109 zettels, 7 structure notes…" |

---

## 3. Content Ingestion Map

### Main Session Content Reads

The main session read zero raw evidence files for extraction — all extraction was delegated to subagents. The main session read only:

| File | Lines Read | Purpose |
| :--- | :--- | :--- |
| `SKILL.md` | 122 | Skill instructions |
| `references/ingest.md` | 137 | Ingest workflow |
| `references/zettel-template.md` | 48 | Zettel template |
| `references/page-template.md` | 38 | Page template |
| `references/schema.md` | 56 | Naming conventions |
| `references/audit.md` | — | Audit workflow |
| `zettels/202604230526.md` | ~25 | Orphan zettel audit |
| `pages/competitive-moat.md` | 40 | Quality spot-check |
| `pages/financial-performance.md` | 30 | Quality spot-check |
| `00-ai-media/INDEX.md` | ~12 | Parent index update |

**Total main session reads:** 10 `read` calls, all infrastructure/audit.

### Subagent Extraction Reads

| Subagent | Label | Source Files Read | Key Sources |
| :--- | :--- | :--- | :--- |
| `015cdda3` | filings-early | 6 | FY21 annual report, FY21 results, FY22 results pres, FY23 results, FY23 annual report |
| `260fb7b2` | filings-mid | 4 | 1H FY24 results, 1H FY24 pres, FY24 results pres, FY24 results |
| `56f243aa` | filings-recent | 6 | 1H25 pres, half-yearly report, FY25 results, 1H FY26 results, AGM address, appendix 4G |
| `cde2dd3a` | transcripts | 7 | ASX small-mid cap conf (2021), FY22 investor pres, AI captioning webinar, Strawman H1 interview, AGM webcast, AGM address, AGM recording |
| `01fc48bb` | product-docs | 10 | HD492 manual, LEXI DR manual, Falcon guide, gov solutions, LEXI AI/Brew/Cloud/Quick Facts/Recorded/Voice one-pagers |
| `4db5bf8f` | customers | 7 | Seven Network renewal, Reddit threads (×3), PlayBox case study, ACMA breach report, Amagi case study |
| `955dca40` | competitors | 0 (via task) | Verbit overview, 3Play encoder, ENCO enCaption5, Evertz suite, SyncWords, Verbit gov (source text embedded in task prompt) |
| `28a0721b` | news-metrics | 0 (via task) | Slator Google contract, LEXI 3.0 launch, UN languages, LEXI Recorded launch, Strawman interview, IBC EAA (source text embedded in task prompt) |

**Total unique source files read across all subagents:** ~40 files + task-embedded text for 2 batches.

---

## 4. Wiki Output Map

| Path | Description |
| :--- | :--- |
| `wiki/INDEX.md` | Master catalog of the wiki structure |
| `wiki/LEDGER.md` | Permanent audit log (construction session) |
| `wiki/pages/INDEX.md` | Page catalog |
| `wiki/pages/competitive-moat.md` | Competitive Moat & Vertical Integration — iCap, hardware control, switching costs, data flywheel |
| `wiki/pages/lexi-product-suite.md` | LEXI Product Suite — LEXI 3.0/DR/Voice/Recorded/AI/Vision, Alta, technology features |
| `wiki/pages/business-model-transformation.md` | Business Model Transformation — SaaS pivot, margins, HaaS, strategic cannibalization |
| `wiki/pages/financial-performance.md` | Financial Performance & Valuation — ARR growth, EBITDA, margin expansion, DCF |
| `wiki/pages/global-expansion.md` | Global Expansion & Go-to-Market — geographic growth, indirect sales, EAA/ADA catalysts |
| `wiki/pages/customer-evidence.md` | Customer & Market Evidence — Seven Network, Google, UK Parliament, sports league wins |
| `wiki/pages/competitive-landscape.md` | Competitive Landscape — Verbit, ENCO, Evertz, SyncWords, virtual encoding threats |
| `wiki/zettels/INDEX.md` | Zettel catalog (109 entries) |
| `wiki/zettels/20260423*.md` | 109 atomic knowledge notes |

**Total files created:** 120 (109 zettels + 7 wiki pages + 4 infrastructure files).

### Zettel Distribution by Source Category

| Source Category | Files Read | Zettels | Namespace | Subagent |
| :--- | :--- | :--- | :--- | :--- |
| FY21–FY23 filings | 6 | 10 | `202604230200` | `015cdda3` |
| 1H FY24 + FY24 filings | 4 | 10 | `202604230300` | `260fb7b2` |
| 1H FY25 + FY25 + 1H FY26 filings | 6 | 10 | `202604230400` | `56f243aa` |
| Transcripts | 7 | 32 | `202604230500` | `cde2dd3a` |
| Product documentation | 10 | 14 | `202604230600` | `01fc48bb` |
| Customer evidence | 7 | 14 | `202604230700` | `4db5bf8f` |
| Competitor analyses | 6 (embedded) | 7 | `202604230800` | `955dca40` |
| News + key metrics + valuation | 6 (embedded) | 12 | `202604230900` | `28a0721b` |
| **Total** | **~52** | **109** | | |

---

## 5. Think Steps

### Step 1: Task Strategy (05:26:30 UTC)
> "Let me understand what Anton is asking:
> 1. Use the zettel-wiki skill on the AI Media company folder
> 2. Create the wiki in `00-ai-media/wiki/` (not the default wiki location)
> 3. Only read files within the 00-ai-media folder
>
> So I need to:
> - Set up a wiki structure at `00-ai-media/wiki/` with `pages/`, `zettels/`, `INDEX.md`, `LEDGER.md`
> - Process raw evidence from the 01-data folder (structured sources) into zettels
> - DO NOT use notes/memos from 00-notes (those are synthesis, not raw evidence per the skill)
> - Create structure notes from the emergent zettel clusters
>
> The raw evidence sources are in `01-data/02-structured/`: 00-filings, 02-transcripts, 03-product-docs, 04-customer-evidence, 05-competitors, 06-news, 08-key-metrics, 10-valuation.
>
> This is a large body of evidence. I should use parallel subagents for extraction, then consolidate. I have up to 10 parallel subagents. Let me batch by source category."

### Step 2: Architecture Planning (05:26:53 UTC)
> "The raw evidence sources in `01-data/02-structured/`: filings (~20+ files), transcripts (~10), product docs (~10), customer evidence (~7), competitors (~6), news (~7), key metrics, valuation.
>
> I should NOT use 00-notes/ or 02-research/ — they are outputs of prior analysis.
>
> Plan: 8 subagents with non-overlapping timestamp namespaces:
> 1. Filings early (FY21-FY23): namespace 0200
> 2. Filings mid (FY24): namespace 0300
> 3. Filings recent (FY25-FY26): namespace 0400
> 4. Transcripts: namespace 0500
> 5. Product docs: namespace 0600
> 6. Customer evidence: namespace 0700
> 7. Competitors: namespace 0800
> 8. News + metrics + valuation: namespace 0900
>
> Each subagent gets: model gemini-flash, lightContext true, wiki root path, zettel template, source file list, timestamp namespace. After they all complete: consolidate, cross-link, structure notes, INDEX, LEDGER, audit."

### Step 3: Subagent Batch Design (05:27:33 UTC)
> "Finalized 8 batch assignments with file lists:
> 1. Filings early: investorhub-3676802 through investorhub-4400818 (9 files) — namespace 0200
> 2. Filings mid: investorhub-6216424 through investorhub-6502528, 2024-08-29 files (7 files) — namespace 0300
> 3. Filings recent: investorhub-6815461 through 2026-02-25 (10 files) — namespace 0400
> 4. Transcripts: .md versions where both exist (7 unique) — namespace 0500
> 5. Product docs: 10 files — namespace 0600
> 6. Customer evidence: 7 files — namespace 0700
> 7. Competitors: 6 files — namespace 0800
> 8. News + key metrics + valuation: ~10 text files — namespace 0900
>
> Model choice: gemini-flash for all subagents (extraction-heavy, cost-efficient)."

### Step 4: Post-Extraction Consolidation (05:32:01 UTC)
> "All 109 zettels landed. Now I need to:
> 1. Build a full zettel catalog (read all titles/tags) for the INDEX
> 2. Identify natural clusters for structure notes
> 3. Wire cross-batch connections
> 4. Write structure notes
> 5. Update all INDEX.md files
> 6. Write the LEDGER entry
> 7. Run audit checks"

### Step 5: Structure Note Clustering (05:32:41 UTC)
> "I now have a full catalog of 109 zettels. Let me cluster them:
>
> 1. **Competitive Moat & Vertical Integration** (~15-20 zettels) — iCap network, vertical integration, hardware control, switching costs, data moat
> 2. **LEXI Product Suite & AI Technology** (~20+ zettels) — LEXI 3.0, DR, Voice, Recorded, AI, Brew, Vision, CCMatch, Alta
> 3. **Business Model Transformation** (~15 zettels) — SaaS pivot, HaaS, revenue mix, strategic cannibalization
> 4. **Financial Performance** (~10 zettels) — ARR, EBITDA, margin expansion, valuation, R&D
> 5. **Go-to-Market & Global Expansion** (~12 zettels) — geographic, indirect sales, EAA/regulatory
> 6. **Customer & Market Evidence** (~10 zettels) — Seven Network, Google, UK Parliament, enterprise validation
> 7. **Competitive Landscape** (~8 zettels) — competitors, virtual encoding threat, SRT
>
> 7 structure notes. Each subagent reads its assigned zettels, writes the page, and updates each zettel's `## Related` section with a backlink. Cross-batch connections are handled by the structure notes themselves — they serve as the connective tissue."

---

## 6. Cost & Token Summary

### Main Session (Opus)

| Metric | Value |
| :--- | :--- |
| Input tokens | 92 |
| Output tokens | 25,215 |
| Cache read | 3,395,459 |
| Cache write | 827,504 |
| **Total tokens** | **4,248,270** |

### Subagent Token Usage

#### Extraction Subagents

| Session ID | Label | Duration | Tool Calls | Files Read | Zettels | Input | Output | Cache Read | Total |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `015cdda3` | filings-early | 81s | 17 | 6 | 10 | 189,276 | 9,630 | 1,170,240 | 1,369,146 |
| `260fb7b2` | filings-mid | 76s | 15 | 4 | 10 | 93,227 | 9,260 | 511,620 | 614,107 |
| `56f243aa` | filings-recent | 82s | 18 | 6 | 10 | 150,743 | 10,123 | 910,122 | 1,070,988 |
| `cde2dd3a` | transcripts | 189s | 41 | 7 | 32 | 239,121 | 22,750 | 2,102,745 | 2,364,616 |
| `01fc48bb` | product-docs | 117s | 26 | 10 | 14 | 160,221 | 13,271 | 1,254,149 | 1,427,641 |
| `4db5bf8f` | customers | 93s | 21 | 7 | 14 | 127,587 | 11,347 | 486,879 | 625,813 |
| `955dca40` | competitors | 52s | 9 | 0† | 7 | 57,468 | 6,818 | 205,950 | 270,236 |
| `28a0721b` | news-metrics | 90s | 18 | 0† | 12 | 106,052 | 11,369 | 676,330 | 793,751 |
| **Subtotal** | | | **165** | **40** | **109** | **1,123,695** | **94,568** | **7,318,035** | **8,536,298** |

† Source text was embedded in the task prompt rather than read via `read` tool.

#### Structure Note Subagents

| Session ID | Label | Duration | Tool Calls | Zettels Edited | Input | Output | Cache Read | Total |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `a5136602` | competitive-moat | 63s | 9 | 3 | 64,570 | 10,686 | 297,747 | 373,003 |
| `e34ed9c8` | lexi-product | 51s | 8 | 1 | 67,797 | 7,696 | 230,997 | 306,490 |
| `46b236d8` | business-model | 95s | 26 | 19 | 111,080 | 10,574 | 904,459 | 1,026,113 |
| `f3339ffe` | financials | 83s | 17 | 1 | 98,485 | 11,420 | 590,464 | 700,369 |
| `536d670d` | global-expansion | 64s | 19 | 16 | 123,376 | 6,628 | 496,300 | 626,304 |
| `62ab5839` | customers | 69s | 19 | 15 | 110,380 | 7,654 | 516,488 | 634,522 |
| `75639b62` | competitive-landscape | 57s | 15 | 12 | 91,478 | 6,122 | 362,949 | 460,549 |
| **Subtotal** | | | **113** | **67** | **667,166** | **60,780** | **3,399,404** | **4,127,350** |

### Grand Totals

| Metric | Main Session (Opus) | 8 Extraction (Flash) | 7 Structure (Flash) | Grand Total |
| :--- | :--- | :--- | :--- | :--- |
| Input tokens | 92 | 1,123,695 | 667,166 | 1,790,953 |
| Output tokens | 25,215 | 94,568 | 60,780 | 180,563 |
| Cache read | 3,395,459 | 7,318,035 | 3,399,404 | 14,112,898 |
| Cache write | 827,504 | 0 | 0 | 827,504 |
| **Total tokens** | **4,248,270** | **8,536,298** | **4,127,350** | **16,911,918** |

---

## 7. Subagent Usage

### 7.1 Extraction Subagents

| Session ID | Label | Duration | Tool Calls | Files Read | Zettels Written | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `015cdda3` | filings-early | 1m 21s | 17 | 6 | 10 | ✅ |
| `260fb7b2` | filings-mid | 1m 16s | 15 | 4 | 10 | ✅ |
| `56f243aa` | filings-recent | 1m 22s | 18 | 6 | 10 | ✅ |
| `cde2dd3a` | transcripts | 3m 9s | 41 | 7 | 32 | ✅ |
| `01fc48bb` | product-docs | 1m 57s | 26 | 10 | 14 | ✅ |
| `4db5bf8f` | customers | 1m 33s | 21 | 7 | 14 | ✅ |
| `955dca40` | competitors | 52s | 9 | 0† | 7 | ✅ |
| `28a0721b` | news-metrics | 1m 30s | 18 | 0† | 12 | ✅ |
| **Total** | | | **165** | **40** | **109** | **8/8 ✅** |

† Source text embedded in task prompt.

### 7.2 No Batch Failures

All 8 extraction subagents completed successfully — a first for the zettel-wiki series (v1: 0 subagents used, v2: 1 batch failure out of 8). The transcript batch (`cde2dd3a`) was the longest at 3m 9s and produced the most zettels (32), processing all 7 transcript files including conference recordings and webinars.

### 7.3 Structure Note Subagents

| Session ID | Label | Duration | Tool Calls | Edits | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `a5136602` | competitive-moat | 1m 3s | 9 | 3 | ✅ |
| `e34ed9c8` | lexi-product | 51s | 8 | 1 | ✅ |
| `46b236d8` | business-model | 1m 35s | 26 | 19 | ✅ |
| `f3339ffe` | financials | 1m 23s | 17 | 1 | ✅ |
| `536d670d` | global-expansion | 1m 4s | 19 | 16 | ✅ |
| `62ab5839` | customers | 1m 9s | 19 | 15 | ✅ |
| `75639b62` | competitive-landscape | 57s | 15 | 12 | ✅ |
| **Total** | | | **113** | **67** | **7/7 ✅** |

**Backlink pattern:** Each structure note subagent wrote its page and then edited its assigned zettels to add `## Related` backlinks pointing to the new page. The `business-model` subagent made the most edits (19), reflecting the broad reach of business model transformation across filings, metrics, and product evidence.

---

## 8. Observations

### 8.1 Three-Phase Architecture: Scout → Extract → Synthesize

v3 introduced a clean three-phase architecture within a single session:

1. **Scout** (05:26–05:27): Skill loading, source survey, batch planning. 3 think steps, 0 content reads.
2. **Extract** (05:27–05:31): 8 parallel subagents read raw evidence and write zettels. Main session dormant.
3. **Synthesize** (05:31–05:36): Main session builds zettel catalog, identifies clusters, spawns 7 page subagents, then performs audit and finalization.

This is more disciplined than v2, where the main session read 2 content docs for orientation before spawning extractors. In v3, the orchestrator never reads a single source file — all content contact is delegated.

### 8.2 Zero Failures: 8/8 Extraction + 7/7 Structure Notes

For the first time in the series, no subagent batch failed. v2 lost batch 4 (FY21–23 filings, 9 files) to a context overflow — the same era of filings processed successfully in v3's batch 1 (filings-early). The likely reason: v3 split the filing history into 3 batches (early/mid/recent) instead of v2's 4 batches (which assigned 9 older filings to a single worker). Smaller batches per worker = fewer overflows.

### 8.3 Transcript Batch Dominance

The transcripts subagent (`cde2dd3a`) was an outlier: 32 zettels from 7 source files (4.6 zettels/file), taking 3m 9s and consuming 2.4M total tokens — the most of any batch. By comparison, filings averaged 1.5 zettels/file and product docs 1.4 zettels/file. Transcripts are information-dense because they capture unscripted management commentary, Q&A, and real-time market positioning that filings sanitize away.

### 8.4 Task-Embedded Source Text

Two batches (competitors and news-metrics) had their source files embedded directly in the task prompt rather than requiring the subagent to `read` them. This meant 0 `read` calls but higher input token counts relative to the actual extraction work. The tradeoff: fewer tool calls and round-trips at the cost of a larger initial context. For small files (competitor analyses and news articles tend to be short), this was likely more efficient.

### 8.5 Structure Note Subagents as Backlink Workers

The v3 page subagents did double duty: write the structure note _and_ edit every assigned zettel's `## Related` section to add a backlink. This eliminated the need for a separate cross-linking phase (which v2 required as a second 8-subagent pass). The most edit-heavy subagent was `business-model` (19 edits), while `lexi-product` made only 1 edit — suggesting it may have written the page but didn't update zettel backlinks comprehensively. This is a quality gap worth auditing.

### 8.6 Wall Time: 47% Faster Than v2 for Similar Output

| Metric | v1 | v2 (Ingest only) | v3 |
| :--- | :--- | :--- | :--- |
| Wall time | 13m 35s | 14m | 10m 50s |
| Subagents | 0 | 8 | 15 |
| Zettels | 30 | 117 | 109 |
| Structure notes | 10 | 9 | 7 |
| Source files processed | 4 (synthesized) | 47 (raw) | ~52 (raw) |
| Failures | 0 | 1 | 0 |

v3 produced nearly the same output as v2 (109 vs 117 zettels, 7 vs 9 pages) in 23% less wall time. The 8-zettel gap is partly explained by v3 skipping duplicate extraction (v2 had 6 identified duplicate clusters). The time savings come from:
1. No separate maintenance phase for cross-linking (folded into structure note subagents)
2. No batch failures requiring assessment
3. Zero main-session content reads (pure orchestration)

### 8.7 Token Economics

| Metric | v2 | v3 | Change |
| :--- | :--- | :--- | :--- |
| Total tokens | 25.7M | 16.9M | –34% |
| Main session | 11.0M | 4.2M | –62% |
| Subagent sessions | 14.8M | 12.7M | –14% |
| Subagent count | 16 | 15 | –6% |

v3 was significantly more token-efficient, mostly because the main session context was leaner (no content reads = smaller accumulating context = fewer cache write/read tokens). The subagent totals were similar because the raw source corpus is roughly the same size.

### 8.8 Think Step Discipline: 5 Decision Points

The orchestrator used `think` at 5 points: task interpretation (1), architecture planning (1), batch design (1), post-extraction assessment (1), and structure note clustering (1). This is fewer than v2's 11 think steps despite similar complexity — suggesting the v3 orchestrator was more decisive, spending less time on mid-extraction triage (which v2 needed for failure handling).

### 8.9 v1 → v2 → v3 Architecture Evolution

| Aspect | v1 | v2 | v3 |
| :--- | :--- | :--- | :--- |
| Agent model | Single Opus | Opus + Flash | Opus + Flash |
| Source material | 4 synthesized notes | 47 raw files | ~52 raw files |
| Main session content reads | 4 (all sources) | 2 (orientation) | 0 (pure orchestration) |
| Extraction subagents | 0 | 8 | 8 |
| Structure note subagents | 0 | 0 (Opus wrote all) | 7 (Flash wrote all) |
| Cross-linking | Manual (1 pass) | 8 subagents (separate phase) | Folded into page subagents |
| Zettels | 30 | 117 | 109 |
| Structure notes | 10 | 9 | 7 |
| Failures | 0 | 1/8 | 0/15 |
| Think steps | 4 | 11 | 5 |
| Total tokens | ~1.3M | ~25.7M | ~16.9M |
| Wall time | 13m 35s | ~20m | 10m 50s |

The key architectural shift from v2 to v3 is the delegation of structure note writing from Opus to Flash. In v2, the orchestrator synthesized all 9 pages itself (~8K output tokens, ~4 minutes). In v3, 7 Flash subagents wrote the pages in parallel (~60K output tokens combined, ~60 seconds). This trades Opus editorial quality for parallelism and speed. Whether the structure notes are as narratively coherent as v2's Opus-written pages is an open quality question that a content-level audit would answer.

### 8.10 Remaining Gaps

1. **Orphan audit was light.** Only 1 orphan was found and fixed (board governance zettel). The audit checked for missing `## Related` sections but did not verify that every zettel has _inbound_ connections from other zettels — only that it links to a structure note. True cross-zettel connectivity was not audited.

2. **Lexi-product backlinks.** The `page-lexi-product` subagent made only 1 edit despite being assigned ~20 zettels. This suggests many LEXI-related zettels may lack backlinks to their structure note — a gap the v2 maintenance phase would have caught.

3. **No duplicate detection.** v2 identified 6 duplicate zettel clusters. v3 did not run any duplicate analysis. With 109 zettels extracted from overlapping chronological filings, duplicates are likely present.

4. **Source exclusion rationale undocumented.** The skill says research outputs and notes are not zettel sources, and the orchestrator respected this. But the LEDGER entry does not record _which_ files from `01-data/02-structured/` were included vs. excluded, or why some filings (e.g., appendix 4E, annual report appendices) were skipped while others were processed.
