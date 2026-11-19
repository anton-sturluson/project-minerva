"""Minimal local document pairs: retain originals, use existing converters, never overwrite."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx


class DocumentError(ValueError):
    """A source could not be collected completely and safely."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source(source: str) -> bytes:
    """Read an explicit path/URL, rejecting failed or short HTTP transfers."""
    if urlsplit(source).scheme in {"http", "https"}:
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            response = client.get(source)
            response.raise_for_status()
            data = response.content
            length = response.headers.get("content-length")
            if length and not response.headers.get("content-encoding") and len(data) != int(length):
                raise DocumentError("Incomplete HTTP transfer (Content-Length mismatch)")
    else:
        data = Path(source).read_bytes()
    if not data:
        raise DocumentError("Source is empty")
    return data


def _pymupdf(*, markdown: bool = False):
    try:
        import pymupdf
        version = importlib.metadata.version("pymupdf")
    except ImportError as exc:
        raise DocumentError("PDF support requires: uv sync --extra documents") from exc
    if markdown and version not in {"2.1.0", "2.1"}:
        raise DocumentError("pdf2md requires pymupdf==2.1; run uv sync --extra documents")
    return pymupdf


def inspect_pdf(data: bytes) -> tuple[int, list[str]]:
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
        raise DocumentError("Not a complete PDF (missing PDF header or final EOF marker)")
    try:
        with _pymupdf().open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or doc.is_repaired or not doc.page_count:
                raise DocumentError("Encrypted, repaired/truncated, or empty PDF; obtain an intact source")
            return doc.page_count, [page.get_text() for page in doc]
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Cannot parse PDF: {exc}") from exc


def provenance(source: str, digest: str, kind: str, pages: int | None = None, warnings=()) -> str:
    lines = ["<!-- document-pair provenance -->", f"- Source: {source}", f"- Source SHA-256: {digest}",
             f"- PDF provenance: {kind}", f"- Collected (UTC): {datetime.now(timezone.utc).isoformat()}"]
    if pages is not None:
        lines.append(f"- PDF pages: {pages}")
    lines.extend(f"- Warning: {warning}" for warning in warnings)
    return "\n".join(lines)


def _native_tokens(text: str) -> list[str]:
    # Independent of generated-PDF normalization: never weaken render guards.
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    return re.findall(r"[^\W_]+", text.casefold())


def _native_numbers(text: str) -> Counter:
    # Preserve punctuation and attached signs; this is not financial interpretation.
    return Counter(re.findall(r"(?<![\w])\(?[-−+]?\$?\d[\d,]*(?:\.\d+)?%?\)?", text))


def _native_coverage_loss(native: str, layout: str, spans: list[str], words: list[str]) -> dict:
    """Conservative page-local evidence, never a count of proven material defects."""
    compact = lambda text: "".join(_native_tokens(text))
    expected = Counter(_native_tokens(native)) | Counter(_native_tokens(" ".join(words)))
    missing_tokens = expected - Counter(_native_tokens(layout))
    # Count repeated identical spans/lines too, rather than accepting one occurrence.
    sequences = Counter(filter(None, map(compact, spans))) | Counter(filter(None, map(compact, native.splitlines())))
    flat = compact(layout)
    missing_sequences = sum(max(0, count - flat.count(sequence)) for sequence, count in sequences.items())
    missing_numbers = _native_numbers(native) - _native_numbers(layout)
    reasons = {}
    if native.strip() and not layout.strip():
        reasons["all_native_text_absent"] = 1
    if missing_tokens:
        reasons["native_token_occurrences_absent"] = missing_tokens.total()
    if missing_sequences:
        reasons["native_span_or_line_occurrences_unmatched"] = missing_sequences
    if missing_numbers:
        reasons["native_numeric_string_occurrences_absent"] = missing_numbers.total()
    return reasons


def _native_page_fallback(native: str) -> str:
    # A longer fence prevents publisher text from closing the literal block.
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", native)), default=0))
    warning = ("> Extraction warning: native-text coverage could not be established for the layout output. "
               "This entire page was replaced with the exact publisher PDF native-text stream, in native extraction order. "
               "This is not a reconstructed table: do not infer column or cell associations. "
               "The unchanged PDF is authoritative for layout, signs, units, dates and visual content. No OCR or paraphrase was used.")
    return f"{warning}\n\n{fence}text\n{native}{'' if native.endswith(chr(10)) else chr(10)}{fence}"


def pdf_markdown(data: bytes, source: str) -> tuple[str, dict]:
    """Convert every PDF page with the pinned parser, retaining explicit anchors."""
    pages, native = inspect_pdf(data)
    parser = _pymupdf(markdown=True)
    warnings = ["Images, charts and complex table layout may not survive conversion; inspect the PDF.",
                "No OCR is performed; image-only pages need a separate reviewed OCR workflow."]
    try:
        with parser.open(stream=data, filetype="pdf") as doc:
            chunks = doc.to_markdown(page_chunks=True, use_ocr=False)
            if not isinstance(chunks, list) or len(chunks) != pages:
                raise DocumentError(f"Parser did not return all {pages} pages")
            # Read native units, not layout-model boxes (which can omit real text).
            units = []
            for page in doc:
                spans = [span["text"] for block in page.get_text("dict")["blocks"] if block["type"] == 0
                         for line in block["lines"] for span in line["spans"] if span["text"].strip()]
                units.append((page.get_text("text", sort=False), spans, [word[4] for word in page.get_text("words")]))
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"PDF Markdown parser failed: {exc}") from exc
    if len(units) != pages:
        raise DocumentError(f"Native extraction did not return all {pages} pages")
    if not any(t.strip() for t in native):
        raise DocumentError("PDF has no native text; reviewed OCR is required")
    body, empty, fallbacks = [], [], []
    for index, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "")
        raw, spans, words = units[index - 1]
        if raw != native[index - 1]:
            raise DocumentError(f"Native text changed during layout parsing on page {index}; nothing was published")
        reasons = _native_coverage_loss(raw, text, spans, words)
        if reasons:
            text = _native_page_fallback(raw)
            fallbacks.append({"page": index, "reasons": reasons})
        elif not raw.strip():
            empty.append(index)
            text = "[No extractable text on this page; inspect the source PDF.]"
        body.append(f'<a id="page-{index}"></a>\n\n## Page {index}\n\n{text.strip()}')
    if empty:
        warnings.append("Pages without extractable text: " + ", ".join(map(str, empty)))
    limits = ("Checks cover available native text only, not raster glyphs, charts, reading order or semantic/table equivalence. "
              "Conservative flags can reflect harmless word joining or formatting, not proven material omissions. "
              "Numeric-string checks retain attached punctuation/signs but do not interpret financial meaning. Inspect the PDF.")
    warnings.append(limits)
    if fallbacks:
        warnings.append("Whole-page native-text fallback (not reconstructed tables), pages: " +
                        ", ".join(str(row["page"]) for row in fallbacks) +
                        ". Native extraction order only; the PDF is authoritative for layout, signs, units and dates.")
    info = {"pdf_pages": pages, "markdown_pages": len(chunks), "empty_pages": empty,
            "converter": "pymupdf==2.1; page-local native-text coverage with whole-page native fallback",
            "native_fallback_pages": [row["page"] for row in fallbacks], "native_fallback_reasons": fallbacks,
            "native_coverage_check": "Per-page normalized word/number occurrence counts, native span/line sequences and numeric strings",
            "native_coverage_limits": limits, "warnings": warnings}
    return provenance(source, sha256(data), "Original PDF preserved byte-for-byte", pages, warnings) + "\n\n" + "\n\n".join(body) + "\n", info


def publish_files(files: dict[Path, bytes]) -> None:
    """Stage bytes first; exclusive hard links publish without replacing existing files."""
    for path in files:
        if path.exists() or path.is_symlink():
            raise DocumentError(f"Refusing to overwrite {path.name}; choose a new output stem")
    staged, published = [], []
    try:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
                temp.write(data)
                staged.append((Path(temp.name), path))
        for temp, path in staged:
            os.link(temp, path)
            published.append(path)
    except Exception:
        for path in published:
            path.unlink()
        raise
    finally:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)


def _content_tokens(text: str) -> list[str]:
    # Ignore layout/punctuation, normalize ligatures and soft hyphens. No prose edits.
    text = unicodedata.normalize("NFKC", text)
    # WeasyPrint emits U+2010 at automatic alphabetic header line breaks.
    text = re.sub(r"(?<=[^\W\d_])[\u00ad\u2010]\s*\n\s*(?=[^\W\d_])", "", text)
    text = text.replace("\u00ad", "")
    return re.findall(r"[^\W_]+", text.casefold())


def _displayed_body(markdown: str) -> str:
    # Provenance must not make a title-only PDF look complete.
    body = markdown.split("\n\n", 1)[1] if markdown.startswith("<!-- document-pair provenance -->") else markdown
    # Match displayed link/image labels, not invisible targets or HTML attributes.
    body = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"<[^>]*>", " ", body)
    return re.sub(r"\\([\\`*{}\[\]()#+\-.!_|>])", r"\1", body)


def _verify_rendered_text(markdown: str, pages: list[str]) -> None:
    """Bounded text evidence, not a claim of visual or semantic equivalence."""
    body = _displayed_body(markdown)
    expected = _content_tokens(body)
    actual = Counter(_content_tokens("\n".join(pages)))
    if not expected:
        raise DocumentError("Generated PDF source has no verifiable body text")
    # Opening/close plus evenly spread body windows, bounded for long filings.
    starts = sorted({0, max(0, len(expected) - 32),
                     *(int(i * max(0, len(expected) - 32) / 19) for i in range(20))})
    samples = [Counter(expected[start:start + 32]) for start in starts]
    coverage = [sum((sample & actual).values()) / sample.total() for sample in samples]
    if min(coverage) < 0.75 or sum(coverage) / len(coverage) < 0.90:
        raise DocumentError("Generated PDF body text coverage unverified (opening/body/close samples missing); nothing was published")


def _financial_amounts(text: str) -> Counter:
    # Keep the entire comma/decimal value, not a bag of disconnected digits.
    # Integers, signs, percentages and accounting semantics are not proved here.
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    return Counter(re.findall(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)(?!\w|[.,]\d)", text))


def _verify_rendered_layout(markdown: str, data: bytes) -> None:
    """Reject off-page painted text and missing comma/decimal amount occurrences.

    This is a generated-PDF guard, never a restriction on publisher originals.
    It does not prove table associations, image fidelity, overlap, arbitrary PDF
    clipping paths or semantic equivalence. A 1pt box tolerance permits font
    metric rounding and small superscript overhangs, not missing columns.
    """
    visible = []
    with _pymupdf().open(stream=data, filetype="pdf") as doc:
        for page in doc:
            bounds = page.rect + (-1, -1, 1, 1)
            for span in page.get_texttrace():
                if span["type"] == 3 or span["opacity"] <= 0:
                    continue  # Invisible PDF text must not satisfy coverage.
                chars, previous = [], None
                for code, _, origin, box in span["chars"]:
                    char = chr(code) if code >= 0 else "\ufffd"
                    if not char.isspace() and not bounds.contains(box):
                        raise DocumentError(f"Generated PDF text outside page {page.number + 1}; nothing was published")
                    # A paint span can cover multiple table cells/lines without
                    # spaces. Do not merge their adjacent financial amounts.
                    if previous is not None and (abs(origin[1] - previous[1]) > 1
                                                 or box[0] - previous[0] > span["size"] * 0.15
                                                 or box[0] < previous[0] - 1):
                        chars.append(" ")
                    chars.append(char)
                    previous = (box[2], origin[1])
                visible.append("".join(chars))
    expected = _financial_amounts(_displayed_body(markdown))
    missing = expected - _financial_amounts("\n".join(visible))
    if missing:
        raise DocumentError(f"Generated PDF financial amount coverage unverified ({sum(missing.values())} comma/decimal occurrences missing); nothing was published")


def _pdf_markdown(markdown: str) -> str:
    """Prepare only the temporary reading copy; retain every source cell.

    Native converters can join a narrow caption and a wider table into one
    ragged pipe block. Pandoc silently discards cells beyond the header width.
    Extend with empty cells, never truncate/reorder data or edit the saved MD.
    Long prose/exhibit cells also need a wider page, not an oversized repeated
    header that the PDF engine can silently omit in its entirety.
    """
    lines, output, index, fence = markdown.splitlines(keepends=True), [], 0, None
    while index < len(lines):
        line = lines[index]
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        # A native paragraph can be fused to a header without its opening pipe.
        # Pandoc still treats it as a table; retain that first cell in preflight.
        if (not fence and not re.match(r"^ {0,3}\|", line) and re.match(r"^ {0,3}\S", line)
                and "|" in line and index + 1 < len(lines)
                and re.fullmatch(r" {0,3}\|(?:\s*:?-{3,}:?\s*\|)+\s*", lines[index + 1])):
            line = "|" + line
            lines[index] = line
        if fence or not re.match(r"^ {0,3}\|", line):
            output.append(line)
            index += 1
            continue
        block = []
        while index < len(lines) and re.match(r"^ {0,3}\|", lines[index]):
            block.append(lines[index])
            index += 1
        # Count only unescaped pipes (even backslashes leave a pipe unescaped).
        positions = [[m.end() - 1 for m in re.finditer(r"(?<!\\)(?:\\\\)*\|", row.rstrip())] for row in block]
        if len(block) < 2 or any(len(p) < 2 or p[0] != len(row) - len(row.lstrip(" "))
                                 or p[-1] != len(row.rstrip()) - 1
                                 for row, p in zip(block, positions)):
            output.extend(block)
            continue
        cells = [[row[a + 1:b].strip() for a, b in zip(p, p[1:])] for row, p in zip(block, positions)]
        if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells[1]):
            output.extend(block)
            continue
        width = max(map(len, cells))
        longest_cell = max(len(cell) for row in cells for cell in row)
        for n, (row, p) in enumerate(zip(block, positions)):
            padding = (" --- |" if n == 1 else " |") * (width - len(cells[n]))
            row = row[:p[-1] + 1] + padding + row[p[-1] + 1:]
            if n == 0 and longest_cell > 250:
                layout = "minerva-very-long-cell" if longest_cell > 1000 else "minerva-long-cell"
                row = row[:p[0] + 1] + f' <span class="{layout}"></span>' + row[p[0] + 1:]
            output.append(row)
    return "".join(output)


_SOURCE_PDF_CSS = """
table { break-inside: auto; page-break-inside: auto; }
/* Do not force currency/spacer columns to the same width as row labels. */
col { width: auto !important; }
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
/* Preserve every source column, including EDGAR currency/spacer columns.
   Compact padding, not digits or tiny fonts; headers wrap at word boundaries. */
th, td { padding: 2pt; font-size: 9pt; line-height: 1.25; }
/* Alphabetic cell hyphenation only; never break financial digits. */
th, td { -weasy-lang: "en"; hyphens: auto; }
@page financial-landscape { size: letter landscape; }
@page financial-long { size: A3 portrait; margin: 0.5in; }
@page financial-very-long { size: A2 portrait; margin: 0.5in; }
@page financial-wide { size: A3 landscape; margin: 0.5in; }
@page financial-extra-wide { size: A2 landscape; margin: 0.5in; }
table:has(tr > :nth-child(8)) { page: financial-landscape; }
table:has(th .minerva-long-cell) { page: financial-long; }
table:has(th .minerva-very-long-cell) { page: financial-very-long; }
table:has(tr > :nth-child(11)) { page: financial-wide; }
table:has(tr > :nth-child(20)) { page: financial-extra-wide; }
"""


def render_pdf(markdown: str) -> tuple[bytes, int]:
    executable = shutil.which("md2pdf")
    if not executable:
        raise DocumentError("md2pdf is required on PATH; nothing was published")
    with tempfile.TemporaryDirectory(prefix="minerva-pair-") as directory:
        md, pdf = Path(directory) / "document.md", Path(directory) / "document.pdf"
        css = Path(directory) / "source.css"
        # Source-local only; no changes to the global md2pdf helper or source MD.
        css.write_text(_SOURCE_PDF_CSS)
        md.write_text(_pdf_markdown(markdown), encoding="utf-8")
        result = subprocess.run([executable, str(md), "--output", str(pdf), "--extra-css", str(css)], capture_output=True, text=True)
        if result.returncode or not pdf.exists():
            raise DocumentError(f"md2pdf failed: {(result.stderr or result.stdout)[-2000:]}")
        data = pdf.read_bytes()
        count, pages = inspect_pdf(data)
        _verify_rendered_layout(markdown, data)
        _verify_rendered_text(markdown, pages)
        return data, count


def pair_files(stem: Path) -> list[Path]:
    return [Path(str(stem) + suffix) for suffix in (".pdf", ".md", ".source.json", ".sources")]


def create_pair(*, source: str, stem: Path, source_format: str, source_url: str | None = None,
                markdown: str | None = None, raw_files: dict[str, bytes] | None = None,
                metadata: dict | None = None) -> dict:
    """One PDF + one complete MD + receipt; archive optional native sources separately."""
    if stem.suffix.lower() in {".pdf", ".md", ".json"}:
        raise DocumentError("--output is a stem, not a .pdf/.md/.json filename")
    pdf_path, md_path, receipt_path, raw_dir = pair_files(stem)
    for target in (pdf_path, md_path, receipt_path, raw_dir):
        if target.exists() or target.is_symlink():
            raise DocumentError(f"Existing complete or partial pair at {stem.name}; choose a new stem (no overwrite)")
    if source_format not in {"pdf", "markdown", "html", "xml"}:
        raise DocumentError("source format must be pdf, markdown, html, or xml")
    data = read_source(source)
    label = source_url or (source if urlsplit(source).scheme else Path(source).name)
    digest = sha256(data)
    if source_format == "pdf":
        text, info = pdf_markdown(data, label)
        pdf, kind = data, "original"
    else:
        text = markdown if markdown is not None else data.decode("utf-8")
        if source_format in {"html", "xml"} and markdown is None:
            raise DocumentError("Native HTML/XML needs complete source-to-Markdown conversion, not a PDF roundtrip")
        if len(text.strip()) < 80:
            raise DocumentError("Source Markdown is empty or suspiciously short (<80 characters)")
        if "<html" in text[:500].lower() or "<!doctype html" in text[:500].lower():
            raise DocumentError("Expected Markdown, received HTML")
        kind = f"generated from complete {source_format}; NOT a publisher-original PDF"
        text = provenance(label, digest, kind, warnings=["Check native-source completeness against the publisher; no page-count equivalence is implied."]) + "\n\n" + text.rstrip() + "\n"
        pdf, count = render_pdf(text)
        info = {"pdf_pages": count, "converter": "md2pdf",
                "render_check": "Opening/body/close samples; painted text page bounds (1pt tolerance); comma/decimal amount occurrence counts",
                "warnings": ["Generated PDF, not publisher original",
                             "Render checks do not prove all text, table associations, overlap, charts, images or semantic equivalence; inspect the PDF."]}
    receipt = {"source": label, "source_sha256": digest, "source_format": source_format,
               "pdf_provenance": kind, **info, **(metadata or {}),
               "files": {pdf_path.name: sha256(pdf), md_path.name: sha256(text.encode())}}
    files = {pdf_path: pdf, md_path: text.encode()}
    if raw_files:
        for name, payload in raw_files.items():
            if Path(name).name != name:
                raise DocumentError("Raw source names must be simple filenames")
            files[raw_dir / name] = payload
        receipt["raw_sources"] = {name: sha256(payload) for name, payload in raw_files.items()}
    files[receipt_path] = (json.dumps(receipt, indent=2) + "\n").encode()
    publish_files(files)
    return receipt


def pdf2md(source: Path, output: Path, source_url: str | None = None) -> dict:
    if source.resolve() == output.resolve():
        raise DocumentError("Input and output must differ")
    if output.suffix.lower() != ".md":
        raise DocumentError("pdf2md output must have a .md extension")
    if output.exists() or output.is_symlink():
        raise DocumentError("Refusing to overwrite Markdown output")
    data = read_source(str(source))
    text, info = pdf_markdown(data, source_url or source.name)
    publish_files({output: text.encode()})
    return {"source_sha256": sha256(data), **info}
