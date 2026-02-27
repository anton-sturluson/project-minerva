# Search Agent Memory

## Blocked Sites (403 or equivalent)
- **SEC EDGAR** (sec.gov, data.sec.gov, efts.sec.gov): WebFetch returns 403, BUT curl with User-Agent header works. Use: `curl -s -H "User-Agent: Mozilla/5.0 (Macintosh) minerva-research agent@example.com" {URL}`
- **MacroTrends** (macrotrends.net): Returns 403
- **Investing.com**: Returns 403
- **Zacks**: Returns 403
- **GuruFocus**: Returns 403
- **FinViz**: Returns 403
- **FinanceCharts.com**: Returns 403
- **Fintel.io**: Returns 403
- **WSJ**: Blocked by Claude Code
- **CNBC**: Returns CSS only, no rendered content
- **MLQ.ai**: Returns 403
- **XTB.com**: Returns 403
- **BusinessWire.com**: Tends to timeout
- **PDF files**: WebFetch cannot parse binary PDFs - returns garbled content
- **Investor Relations sites** (e.g., investors.palantir.com): Use JavaScript rendering; WebFetch gets navigation only
- **Seeking Alpha**: Returns 403 (paywalled for transcripts and articles)
- **TipRanks**: Returns 403
- **Livewire Markets** (livewiremarkets.com): Returns 403
- **Listcorp** (listcorp.com): Returns 403
- **Morningstar** (morningstar.com): Returns 403
- **Perplexity Finance** (perplexity.ai/finance): Returns 403
- **StocksDownUnder** (stocksdownunder.com): JS-rendered (Beaver Builder), returns only CSS/JS code

## Reliable Financial Data Sources
- **StockAnalysis.com**: Excellent for FY2021+ income statement, balance sheet, cash flow (annual + quarterly). Use `?p=quarterly` for quarterly view.
- **BusinessQuant.com**: Excellent for single-metric quarterly time series going back to 2019. URL: `businessquant.com/metrics/{TICKER}/{metric}`. Working metrics: revenue, net-income, receivables-net, cash-from-operations, share-based-compensation, cost-of-revenue, deferred-revenue.
- **DiscountingCashFlows.com**: Best source for historical data going back to FY2018+, covers income statement, balance sheet, cash flow
- **StockTitan.net**: Excellent for FULL earnings press releases with complete IS, BS, CF, SBC breakdowns. Best alternative to blocked investor relations sites.
- **CompaniesMarketCap.com**: Good for single metrics (revenue, total assets) with long history
- **AlphaQuery.com**: Good for specific metrics like stock-based compensation with full history
- **Last10K.com**: Good for filing summaries, accession numbers, recent 10-K highlights
- **Bullfincher.io**: Decent for consolidated financial statements FY2021+
- **stock-analysis-on.net**: Detailed SEC-sourced data in thousands, FY2021+ (paywall for some data)
- **Captide.ai**: Good for earnings analysis summaries

## 13F Filing Sources
- **13f.info**: Good for finding filing accession numbers and basic metadata (CIK, filing dates, top holdings). URL: `13f.info/manager/{CIK}-{slug}`
- **InsideArbitrage.com**: Excellent for complete 13F holdings tables with Q/Q changes, % portfolio, and exited positions
- **HoldingsChannel.com**: Good for top 50 holdings with share changes (doesn't show all positions for large portfolios)
- **SEC EDGAR filing path pattern**: `/Archives/edgar/data/{CIK_NUM}/{ACCESSION_NO_SLASHED}/` - information table is usually `form13f_{YYYYMMDD}.xml` or `informationtable.xml`
- **WhalWisdom, StockCircle, HedgeFollow**: Use JS rendering, WebFetch gets empty content

## ASX (Australian) Stock Sources
- **ASX Announcements Search**: `asx.com.au/asx/v2/statistics/announcements.do?by=asxCode&asxCode={CODE}&timeframe=D&period=W`
- **ASX PDF Access Pattern**: Display URLs redirect through a terms page. Extract `pdfURL` from hidden form field in the HTML, then curl the direct PDF URL at `announcements.asx.com.au/asxpdf/{date}/pdf/{hash}.pdf`
- **Futunn ASX Mirrors**: `newsfile.futunn.com/public/NN-PersistNoticeAttachment/7781/{date}/ASX-FTP-{ID}.PDF` -- mirrors ASX PDFs and can be curled directly
- **Meyka** (meyka.com): Reliable for ASX stock analysis articles with price data, technicals, and AI ratings. URL pattern: `meyka.com/blog/{ticker}-{slug}-{MMDD}/`
- **Strawman** (strawman.com): Good for ASX community analysis and forum discussions. Fetchable with WebFetch.
- **HotCopper** (hotcopper.com.au): ASX forum, fetchable for overview pages (limited detail on individual posts)
- **Simply Wall St** (simplywall.st): Fetchable for news articles. Good for shareholder analysis.
- **Slator** (slator.com): Language industry publication, good for captioning/translation company interviews

## Search Strategies
- For FY2019/FY2020 data on companies that IPO'd in 2020: Use DiscountingCashFlows.com which has pre-IPO data
- WebSearch snippets from SEC filings sometimes contain specific numbers even when direct fetch fails
- Always fetch sequentially (one URL at a time) to avoid batch failures
- Financial aggregators often only show 5 most recent fiscal years; need specialized sources for older data
- For SEC EDGAR: Use curl with User-Agent header via Bash tool (WebFetch is blocked by SEC)
- For ASX-listed small caps: Seeking Alpha transcripts are the primary (often only) transcript source, but are paywalled. No reliable free alternative for ASX earnings call transcripts.
- For ASX PDFs: Always verify the downloaded PDF is for the correct company -- ASX search results can return wrong companies if using date-based URL guessing

## Output Directory Pattern
- `{output_dir}/sources/NNN-slug.md`
- `{output_dir}/sources/raw/NNN-slug.{html,pdf}`
- `{output_dir}/manifest.md`
(output_dir is always provided by the caller, typically under hard-disk/reports/{REPORT}/research/)
