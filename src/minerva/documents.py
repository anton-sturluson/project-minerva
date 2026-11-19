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


def pdf_markdown(data: bytes, source: str) -> tuple[str, dict]:
    """Convert every PDF page with the pinned parser, retaining explicit anchors."""
    pages, native = inspect_pdf(data)
    parser = _pymupdf(markdown=True)
    warnings = ["Images, charts and complex table layout may not survive conversion; inspect the PDF.",
                "No OCR is performed; image-only pages need a separate reviewed OCR workflow."]
    try:
        with parser.open(stream=data, filetype="pdf") as doc:
            chunks = doc.to_markdown(page_chunks=True, use_ocr=False)
    except Exception as exc:
        raise DocumentError(f"PDF Markdown parser failed: {exc}") from exc
    if not isinstance(chunks, list) or len(chunks) != pages:
        raise DocumentError(f"Parser did not return all {pages} pages")
    body, empty = [], []
    for index, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "")
        if not text.strip():
            empty.append(index)
            if native[index - 1].strip():
                raise DocumentError(f"Parser lost native text on page {index}; refusing incomplete Markdown")
            text = "[No extractable text on this page; inspect the source PDF.]"
        body.append(f'<a id="page-{index}"></a>\n\n## Page {index}\n\n{text.strip()}')
    if not any(t.strip() for t in native):
        raise DocumentError("PDF has no native text; reviewed OCR is required")
    if empty:
        warnings.append("Pages without extractable text: " + ", ".join(map(str, empty)))
    info = {"pdf_pages": pages, "markdown_pages": len(chunks), "empty_pages": empty,
            "converter": "pymupdf==2.1", "warnings": warnings}
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
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    return re.findall(r"[^\W_]+", text.casefold())


def _verify_rendered_text(markdown: str, pages: list[str]) -> None:
    """Bounded text evidence, not a claim of visual or semantic equivalence."""
    # Provenance must not make a title-only PDF look complete.
    body = markdown.split("\n\n", 1)[1] if markdown.startswith("<!-- document-pair provenance -->") else markdown
    # Match displayed link/image labels, not invisible targets or HTML attributes.
    body = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"<[^>]*>", " ", body)
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


def render_pdf(markdown: str) -> tuple[bytes, int]:
    executable = shutil.which("md2pdf")
    if not executable:
        raise DocumentError("md2pdf is required on PATH; nothing was published")
    with tempfile.TemporaryDirectory(prefix="minerva-pair-") as directory:
        md, pdf = Path(directory) / "document.md", Path(directory) / "document.pdf"
        css = Path(directory) / "source.css"
        # Local override only: long native-source tables must paginate, not move
        # the entire cover (and its kept headings) onto a new page.
        css.write_text("table { break-inside: auto; page-break-inside: auto; }\n"
                       "thead { display: table-header-group; }\n"
                       "tr { break-inside: avoid; page-break-inside: avoid; }\n")
        md.write_text(markdown, encoding="utf-8")
        result = subprocess.run([executable, str(md), "--output", str(pdf), "--extra-css", str(css)], capture_output=True, text=True)
        if result.returncode or not pdf.exists():
            raise DocumentError(f"md2pdf failed: {(result.stderr or result.stdout)[-2000:]}")
        data = pdf.read_bytes()
        count, pages = inspect_pdf(data)
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
                "render_check": "Opening/body/close text samples; not full visual or semantic equivalence",
                "warnings": ["Generated PDF, not publisher original",
                             "Bounded text checks do not verify all text, charts, images or table layout; inspect the PDF."]}
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
