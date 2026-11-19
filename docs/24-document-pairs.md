# Complete document pairs

Use explicit sources, not a new scraper. Prefer a complete publisher PDF when equally authoritative; a partial PDF does not replace complete HTML. Retain the original PDF bytes. HTML/XML goes directly to full Markdown, then `md2pdf` renders a clearly labelled generated PDF. These commands make no model calls.

## Installation and safe trial

Install the optional local parser with `uv sync --extra documents` (pins `pymupdf==2.1`). The existing `md2pdf` executable must be on PATH for generated PDFs. The parser performs no OCR. Scanned pages require a separate reviewed OCR workflow. Complex tables/charts still need inspection against the PDF.

Before integration, run only from the isolated worktree, or pass `uv run --project <worktree> --extra documents ...`. Do not install an editable unmerged worktree into the shared runtime. After reviewed integration, synchronize the normal runtime dependencies with the optional `documents` extra; both entry points come from the same project package.

## Commands

```sh
# All pages, one Markdown file. Input is untouched; no overwrite.
uv run --extra documents pdf2md original.pdf -o complete.md --source-url https://example.com/original.pdf
# Equivalent namespaced command:
uv run --extra documents minerva documents pdf2md original.pdf -o complete.md

# Preserve an original PDF and produce its complete Markdown companion.
uv run --extra documents minerva documents pair original.pdf --from pdf --output new/source --source-url https://example.com/original.pdf
# Explicit HTTP(S) PDF URL is also accepted as the positional source.

# Complete agent-checked Markdown fallback; generated PDF is NOT publisher original.
uv run --extra documents minerva documents pair complete-transcript.md --from markdown --output new/call --source-url https://example.com/call

# SEC native full source, not selected items. Output is a NEW stem, not a filename.
uv run --extra documents minerva sec download EXAMPLE --form 10-Q --format pair --output new/filing
uv run --extra documents minerva sec download 123456 --form 13F-HR/A --accession 0000123456-26-000001 --format pair --output new/amendment

# Full 10-K/10-Q pairs; earnings require Item 2.02 + the same EX-99.1 source.
uv run --extra documents minerva sec bulk-download EXAMPLE --output new/library --annual 5 --quarters 4 --earnings 4 --no-financials
```

Pair output: `STEM.pdf`, `STEM.md`, `STEM.source.json`. Native SEC originals are archived under `STEM.sources/`; XML also has a readable YAML companion. The receipt records source URLs, hashes, converter, page counts, warnings and filing identities. One pair represents one complete filing/document, not a combined quarter. Generic SEC `--format` accepts only `html`, `markdown`, or `pair`; `pdf` is rejected, never silently treated as Markdown. The existing `sec 13f` remains an analytical comparison, not an archival collection command.

Existing complete **or partial** pairs fail clearly with a nonzero status; nothing is replaced or silently skipped. An existing `STEM.sources` path (including a symlink or unrelated directory) also reserves the stem. Choose a new stem, or inspect/move old files yourself. Files are staged before exclusive no-clobber publication; exceptions roll back newly published files. A process kill during publication can leave a partial pair; reruns detect it. This is not a transactional directory store.

## Completeness and limits

- PDF conversion checks the intact header/EOF, parser repairs and all page chunks. Before accepting each layout chunk, it compares that page's available native text using normalized word/number occurrence counts, native span/line sequences and numeric strings with attached punctuation/signs. If coverage cannot be established, it replaces the entire page with the exact native-text stream in a safely fenced block; it never appends a duplicate table. The Markdown header and receipt list fallback pages, reasons and limits. Conservative flags can reflect harmless word joining/formatting, not proven material omissions. Native extraction order is not a reconstructed table: the unchanged publisher PDF remains authoritative for column/cell associations, signs, units, dates and visual content. Blank/image pages retain anchors and notices; documents with no native text still require reviewed OCR. These checks do not prove raster/chart coverage, reading order, semantic equivalence or whether the publisher omitted content. PDF bytes and original hashes are unchanged.
- Generated PDFs must retain opening, closing and evenly spaced body-text samples after punctuation/layout normalization. This bounded check rejects title-only/obviously incomplete renders, not every omission; it does not verify charts, images, all text or table layout. Generated source tables can split across pages with repeated headers and kept rows. Publisher-original PDFs remain unchanged.
- Native full HTML is parsed once by edgartools directly into Markdown. Raw HTML is retained separately. Short/malformed inputs and converter failures fail. Markdown completeness remains an agent check against publisher opening, prepared remarks, Q&A and close; arbitrary truncation cannot be proven from plain text alone.
- 13F includes the cover/summary and every original information-table row/field in source order. It preserves duplicate CUSIPs, calls/puts, voting authority, manager and discretion fields. It archives full-row CSV, original XML and submission TXT. It checks declared row count, period, values and units; pre-2023 values use USD thousands. Each accession is independent: amendments are not silently merged or substituted. Use `--form 13F-HR/A --accession ...` explicitly. Multiple table attachments follow the submission's attachment order. Submission TYPE/FILENAME inventory is read before tables; missing declared information tables and any unreadable XML candidate fail, even if another table matches the cover count. Well-formed non-table XML is explicitly listed as skipped in the receipt.
- 13F discovery/validation follows the pure conventions in the separate research importer, without importing its database models or invoking ingestion. The small namespace/date/unit helpers are copied narrowly because the backend and root CLI are independently installed packages.
- Latest and bulk filing queries require the exact requested form, never a newer amendment in place of an original. Insufficient annual or quarterly availability reports requested/available counts and fails as incomplete; completed pairs remain available.
- Earnings search is bounded to ten times the requested count of recent 8-Ks; insufficient qualifying releases or any collection failure returns an incomplete error, not `Errors: 0`. Full native filing PDFs are generated, not SEC-original PDFs. To prefer a known official IR PDF, use the explicit PDF-pair command instead.
- Optional financial statement exports remain derived tables, not source documents. Legacy selected-section helper tests remain, but bulk collection no longer invokes that path.

## Notes

Downloaded public live-test documents and private receipts belong in ignored scratch, not the public repository. Tests use small project-owned sources. No production installation, canonical data replacement or publishing is part of these commands.
