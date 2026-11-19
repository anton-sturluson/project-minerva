"""Audit reader behavior with project-owned PDF/Markdown evidence only."""

import builtins
import json
import re

import pytest

from harness.workflows.evidence.audit import _read_source_text
from minerva import documents as d


@pytest.fixture
def pdf_module():
    return pytest.importorskip("pymupdf")


def make_pdf(module, texts):
    with module.open() as doc:
        for text in texts:
            page = doc.new_page()
            if text:
                page.insert_text((60, 80), text)
        return doc.tobytes()


def write_pair(source, data, markdown):
    source.write_bytes(data)
    _, md, receipt, _ = d.pair_files(source.with_suffix(""))
    md.write_bytes(markdown.encode())
    payload = {"source_format": "html", "source_sha256": d.sha256(b"raw HTML, not PDF"),
               "files": {source.name: d.sha256(data), md.name: d.sha256(markdown.encode())}}
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    return md, receipt, payload


def block_pdf_imports(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"pymupdf", "fitz", "pymupdf4llm"}:
            pytest.fail("This reader path must not import optional PDF dependencies")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_legacy_pdf_all_pages_full_ending_and_warnings(tmp_path, pdf_module):
    source = tmp_path / "legacy.PDF"
    texts = ["FIRST PAGE model-owned opening.", "SECOND PAGE complete body.",
             "FINAL PAGE full ending certification 12,341."]
    data = make_pdf(pdf_module, texts)
    source.write_bytes(data)
    text = _read_source_text(source)
    assert re.findall(r'<a id="page-(\d+)"></a>', text) == ["1", "2", "3"]
    assert all(value in text for value in texts)
    assert text.index(texts[0]) < text.index(texts[1]) < text.index(texts[2])
    assert "Images, charts" in text and "No OCR" in text
    assert "not raster glyphs" in text
    assert source.read_bytes() == data
    assert set(tmp_path.iterdir()) == {source}


def test_verified_companion_exact_bytes_without_parser_or_pdf_import(tmp_path, monkeypatch, pdf_module):
    source = tmp_path / "reviewed.v1.pdf"
    markdown = "# Reviewed complete OCR\r\n\r\nRaster-only detail: 12,341.\r\nFULL ENDING\r\n"
    data = make_pdf(pdf_module, [""])
    md, receipt, _ = write_pair(source, data, markdown)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    block_pdf_imports(monkeypatch)
    monkeypatch.setattr(d, "pdf_markdown", lambda *a: pytest.fail("Do not reparse a verified pair"))
    assert _read_source_text(source) == markdown
    assert before == {p.name: p.read_bytes() for p in (source, md, receipt)}


@pytest.mark.parametrize("damage", ["pdf", "md", "missing-md", "bad-json", "invalid-utf8-json",
                                    "invalid-utf8-md", "no-files", "no-pdf-hash", "no-md-hash",
                                    "files-list", "null", "list", "receipt-directory"])
def test_present_broken_receipt_or_companion_refuses_without_reparse(tmp_path, monkeypatch, damage):
    source = tmp_path / "pair.pdf"
    md, receipt, payload = write_pair(source, b"model-owned PDF bytes", "Reviewed source ending")
    if damage == "pdf":
        source.write_bytes(b"changed original")
    elif damage == "md":
        md.write_text("stale companion")
    elif damage == "missing-md":
        md.unlink()
    elif damage == "bad-json":
        receipt.write_text("{not JSON")
    elif damage == "invalid-utf8-json":
        receipt.write_bytes(b"\xff")
    elif damage == "invalid-utf8-md":
        md.write_bytes(b"\xff")
        payload["files"][md.name] = d.sha256(b"\xff")
        receipt.write_text(json.dumps(payload))
    elif damage == "receipt-directory":
        receipt.unlink()
        receipt.mkdir()
    else:
        if damage == "no-files":
            del payload["files"]
        elif damage == "no-pdf-hash":
            del payload["files"][source.name]
        elif damage == "no-md-hash":
            del payload["files"][md.name]
        elif damage == "files-list":
            payload["files"] = []
        elif damage == "null":
            payload = None
        elif damage == "list":
            payload = []
        receipt.write_text(json.dumps(payload))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    monkeypatch.setattr(d, "pdf_markdown", lambda *a: pytest.fail("Integrity failures cannot reparse"))
    with pytest.raises(d.DocumentError, match="integrity"):
        _read_source_text(source)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}


def test_no_receipt_ignores_unverified_md_and_uses_existing_converter(tmp_path, monkeypatch, pdf_module):
    source = tmp_path / "legacy.pdf"
    data = make_pdf(pdf_module, ["AUTHORITATIVE PDF OPENING", "AUTHORITATIVE PDF ENDING"])
    source.write_bytes(data)
    source.with_suffix(".md").write_text("STALE UNVERIFIED COMPANION")
    converter, calls = d.pdf_markdown, []

    def checked_converter(actual, label):
        calls.append((actual, label))
        return converter(actual, label)

    monkeypatch.setattr(d, "pdf_markdown", checked_converter)
    text = _read_source_text(source)
    assert calls == [(data, source.name)]
    assert "AUTHORITATIVE PDF ENDING" in text and "STALE UNVERIFIED" not in text
    assert "No OCR" in text and "Images, charts" in text


def test_legacy_pdf_keeps_pinned_version_requirement(tmp_path, monkeypatch, pdf_module):
    source = tmp_path / "legacy.pdf"
    source.write_bytes(make_pdf(pdf_module, ["Complete model-owned body"]))
    original = d.importlib.metadata.version
    monkeypatch.setattr(d.importlib.metadata, "version", lambda name: "0.0" if name == "pymupdf" else original(name))
    with pytest.raises(d.DocumentError, match="pymupdf==2.1"):
        _read_source_text(source)


@pytest.mark.parametrize("invalid", ["image-only", "truncated", "encrypted", "repaired"])
def test_unverified_companion_cannot_bypass_converter_guards(tmp_path, pdf_module, invalid):
    source = tmp_path / "legacy.pdf"
    data = make_pdf(pdf_module, ["MODEL OWNED SOURCE"])
    if invalid == "image-only":
        with pdf_module.open() as picture, pdf_module.open() as doc:
            picture.new_page().insert_text((60, 80), "MODEL OWNED SCANNED SOURCE")
            doc.new_page().insert_image(pdf_module.Rect(0, 0, 595, 842), stream=picture[0].get_pixmap().tobytes("png"))
            data = doc.tobytes()
        message = "no native text; reviewed OCR"
    elif invalid == "truncated":
        data = data[:len(data) // 2]
        message = "complete PDF"
    elif invalid == "encrypted":
        with pdf_module.open(stream=data, filetype="pdf") as doc:
            data = doc.tobytes(encryption=pdf_module.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="example")
        message = "Encrypted, repaired/truncated"
    else:
        data = re.sub(rb"startxref\s+\d+", b"startxref\n0", data)
        with pdf_module.open(stream=data, filetype="pdf") as doc:
            assert doc.is_repaired
        message = "Encrypted, repaired/truncated"
    source.write_bytes(data)
    source.with_suffix(".md").write_text("UNVERIFIED COMPANION must never bypass PDF guards")
    with pytest.raises(d.DocumentError, match=message):
        _read_source_text(source)
    assert source.read_bytes() == data


@pytest.mark.parametrize("suffix", [".md", ".txt", ""])
def test_plain_text_unchanged_without_pdf_dependencies(tmp_path, monkeypatch, suffix):
    block_pdf_imports(monkeypatch)
    source = tmp_path / f"source{suffix}"
    source.write_text("# Complete text\nNon-ASCII: café.\n", encoding="utf-8")
    assert _read_source_text(source) == source.read_text(encoding="utf-8")


def test_directory_sorting_exclusions_and_empty_marker_unchanged(tmp_path, monkeypatch):
    block_pdf_imports(monkeypatch)
    assert _read_source_text(tmp_path) == "(directory exists but no markdown files found)"
    for name, text in {"b.md": "SECOND", "a.md": "FIRST", "_sections.md": "INDEX", "ignored.txt": "TEXT"}.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "child.md").write_text("NESTED")
    assert _read_source_text(tmp_path) == "FIRST\n\nSECOND"


@pytest.mark.parametrize("name", ["absent.pdf", "absent.md", "absent"])
def test_missing_source_marker_unchanged(tmp_path, monkeypatch, name):
    block_pdf_imports(monkeypatch)
    source = tmp_path / name
    assert _read_source_text(source) == f"(file not found: {source})"
