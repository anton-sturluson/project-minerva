"""Project-owned native PDF text regressions; no publisher or model fixtures."""
import json
import re

import pytest

from minerva import documents as d


@pytest.fixture
def pdf_module():
    return pytest.importorskip("pymupdf")


def make_pdf(module, texts):
    with module.open() as doc:
        for text in texts:
            page = doc.new_page()
            if text:
                page.insert_text((60, 80), text, fontsize=11)
        return doc.tobytes()


def fake_chunks(monkeypatch, module, texts):
    def convert(self, **kwargs):
        assert kwargs == {"page_chunks": True, "use_ocr": False}
        return [{"text": text} for text in texts]
    monkeypatch.setattr(module.Document, "to_markdown", convert)


def native_pages(module, data):
    with module.open(stream=data, filetype="pdf") as doc:
        return [page.get_text("text", sort=False) for page in doc]


def page_bodies(markdown):
    return re.split(r'<a id="page-\d+"></a>\n\n## Page \d+\n\n', markdown)[1:]


def fenced_native(body):
    match = re.search(r"^(`{3,})text\n", body, re.M)
    assert match
    return body[match.end():body.index("\n" + match[1], match.end())] + "\n"


def test_nonempty_layout_loses_cover_and_period_headers(tmp_path, monkeypatch, pdf_module):
    cover = "NORTH STAR EXAMPLE CORPORATION\nFORM 10-Q\nQuarter ended September 30, 2026\nRetained cover body."
    statement = ("STATEMENTS OF EXAMPLE OPERATIONS\nThree Months Ended September 30,\n2026     2025\n"
                 "Example revenue     12,341     7,825\nExample income     (1,001)     6,336")
    ending = "FINAL MODEL-OWNED CERTIFICATION\nI certify the complete ending."
    data = make_pdf(pdf_module, [cover, statement, ending])
    raw = native_pages(pdf_module, data)
    layout = ["FORM 10-Q\nRetained cover body.",
              "Example revenue     12,341     7,825\nExample income     (1,001)     6,336", raw[2]]
    fake_chunks(monkeypatch, pdf_module, layout)
    source = tmp_path / "original.pdf"
    source.write_bytes(data)
    stem = tmp_path / "pair"
    result = d.create_pair(source=str(source), stem=stem, source_format="pdf")
    markdown = stem.with_suffix(".md").read_text()
    bodies = page_bodies(markdown)
    assert result["native_fallback_pages"] == [1, 2]
    assert [fenced_native(body) for body in bodies[:2]] == raw[:2]
    assert "complete ending" in bodies[2]
    assert bodies[1].count("12,341") == 1  # replacement, not an appended duplicate table
    assert "Example revenue" in bodies[1] and "Three Months Ended" in bodies[1]
    assert "not a reconstructed table" in bodies[1]
    assert "PDF is authoritative" in markdown.split('<a id="page-1">')[0]
    assert "not proven material omissions" in result["native_coverage_limits"]
    assert source.read_bytes() == stem.with_suffix(".pdf").read_bytes() == data
    receipt = json.loads(stem.with_suffix(".source.json").read_text())
    assert receipt["source_sha256"] == receipt["files"]["pair.pdf"] == d.sha256(data)
    assert receipt["pdf_provenance"] == "original" and "native fallback" in receipt["converter"]
    assert re.findall(r'<a id="page-(\d+)"></a>', markdown) == ["1", "2", "3"]
    before = {p.name: p.read_bytes() for p in tmp_path.glob("pair.*")}
    with pytest.raises(d.DocumentError, match="Existing"):
        d.create_pair(source=str(source), stem=stem, source_format="pdf")
    assert before == {p.name: p.read_bytes() for p in tmp_path.glob("pair.*")}


@pytest.mark.parametrize("lost", ["2026", "12,341"])
def test_repeated_occurrences_must_be_present_on_same_page(monkeypatch, pdf_module, lost):
    source_text = f"Example {lost}\nExample {lost}\nRetained body"
    data = make_pdf(pdf_module, [source_text, source_text])
    raw = native_pages(pdf_module, data)
    fake_chunks(monkeypatch, pdf_module, [raw[0].replace(f"Example {lost}\n", "", 1), raw[1] + raw[1]])
    markdown, info = d.pdf_markdown(data, "example.pdf")
    assert info["native_fallback_pages"] == [1]
    assert fenced_native(page_bodies(markdown)[0]) == raw[0]
    assert info["native_fallback_reasons"][0]["reasons"]["native_token_occurrences_absent"] >= 1


@pytest.mark.parametrize("layout", ["", "  \n", "Retained body without headers"])
def test_all_native_chunks_empty_or_partial_get_complete_fallback(monkeypatch, pdf_module, layout):
    data = make_pdf(pdf_module, ["COMPLETE SOURCE HEADER\nRetained body without headers"])
    fake_chunks(monkeypatch, pdf_module, [layout])
    markdown, info = d.pdf_markdown(data, "example.pdf")
    assert info["native_fallback_pages"] == [1] and info["empty_pages"] == []
    assert fenced_native(page_bodies(markdown)[0]) == native_pages(pdf_module, data)[0]


def test_span_sequences_detect_reordered_or_joined_text_with_same_word_bag():
    native = "Quarter ended September 30 2026\nRevenue 123"
    layout = "September ended Quarter 2026 30\nRevenue 123"
    reasons = d._native_coverage_loss(native, layout, ["Quarter ended September 30 2026", "Revenue 123"], [])
    assert "native_token_occurrences_absent" not in reasons
    assert reasons["native_span_or_line_occurrences_unmatched"] == 1
    repeated = d._native_coverage_loss("Year 2026\nYear 2026", "Year 2026 Year Year 2026", ["Year 2026", "Year 2026"], [])
    assert not repeated  # both identical sequences really occur
    repeated = d._native_coverage_loss("Year 2026\nYear 2026", "Year 2026 2026 Year", ["Year 2026", "Year 2026"], [])
    assert repeated["native_span_or_line_occurrences_unmatched"] == 1


@pytest.mark.parametrize("source,layout", [("(1,001)", "1,001"), ("-123", "123"), ("12.34%", "12.34"), ("1,234", "1234")])
def test_numeric_strings_retain_punctuation_and_attached_signs(source, layout):
    assert d._native_coverage_loss(source, layout, [], [])["native_numeric_string_occurrences_absent"] == 1


def test_dynamic_fence_does_not_interpret_or_escape_native_facts(monkeypatch, pdf_module):
    data = make_pdf(pdf_module, ["Example `code` and ```` fence\n<not-markup> **literal** | 12,341"])
    raw = native_pages(pdf_module, data)[0]
    fake_chunks(monkeypatch, pdf_module, [""])
    markdown, _ = d.pdf_markdown(data, "example.pdf")
    body = page_bodies(markdown)[0]
    assert "`````text\n" in body
    assert fenced_native(body) == raw
    assert "<not-markup> **literal**" in body


def test_blank_pages_keep_anchors_and_empty_fields(monkeypatch, pdf_module):
    data = make_pdf(pdf_module, ["OPENING", "", "FULL ENDING CERTIFICATION"])
    raw = native_pages(pdf_module, data)
    fake_chunks(monkeypatch, pdf_module, raw)
    markdown, info = d.pdf_markdown(data, "example.pdf")
    assert info["empty_pages"] == [2] and info["native_fallback_pages"] == []
    assert len(page_bodies(markdown)) == 3
    assert "No extractable text" in page_bodies(markdown)[1]
    assert markdown.rstrip().endswith("FULL ENDING CERTIFICATION")


def test_real_raster_page_with_tiny_native_transcript(pdf_module):
    transcript = ("MODEL OWNED EXHIBIT FINANCING AGREEMENT DATED AUGUST 25, 2026. "
                  "Example Borrower owes Example Lender $123,456. Next payment September 30, 2026.")
    with pdf_module.open() as image_doc, pdf_module.open() as doc:
        image_page = image_doc.new_page()
        image_page.insert_textbox(pdf_module.Rect(60, 80, 530, 650), transcript, fontsize=12)
        page = doc.new_page()
        page.insert_image(pdf_module.Rect(24, 24, 583, 748), stream=image_page.get_pixmap().tobytes("png"))
        page.insert_text((25, 749), transcript, fontsize=.5)
        data = doc.tobytes()
    with pdf_module.open(stream=data, filetype="pdf") as doc:
        assert not doc.to_markdown(page_chunks=True, use_ocr=False)[0]["text"].strip()
    markdown, info = d.pdf_markdown(data, "example.pdf")
    assert info["native_fallback_pages"] == [1] and info["empty_pages"] == []
    assert fenced_native(page_bodies(markdown)[0]) == native_pages(pdf_module, data)[0]
    assert "$123,456" in markdown and "No OCR or paraphrase" in markdown


@pytest.mark.parametrize("image_only", [False, True])
def test_no_native_document_still_requires_reviewed_ocr(tmp_path, pdf_module, image_only):
    data = make_pdf(pdf_module, [""])
    if image_only:
        with pdf_module.open() as picture, pdf_module.open() as doc:
            picture.new_page().insert_text((60, 80), "MODEL OWNED SCANNED SOURCE")
            doc.new_page().insert_image(pdf_module.Rect(0, 0, 595, 842), stream=picture[0].get_pixmap().tobytes("png"))
            data = doc.tobytes()
    source = tmp_path / "blank.pdf"
    source.write_bytes(data)
    with pytest.raises(d.DocumentError, match="no native text; reviewed OCR"):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="pdf")
    assert not list(tmp_path.glob("pair.*"))


@pytest.mark.parametrize("invalid", ["truncated", "encrypted", "repaired"])
def test_unsupported_pdf_never_publishes(tmp_path, pdf_module, invalid):
    data = make_pdf(pdf_module, ["Original protected source"])
    if invalid == "truncated":
        data = data[:len(data) // 2]
    elif invalid == "encrypted":
        with pdf_module.open(stream=data, filetype="pdf") as doc:
            data = doc.tobytes(encryption=pdf_module.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="example")
    else:
        # Corrupt startxref while retaining EOF: MuPDF can repair it, our guard must refuse.
        data = re.sub(rb"startxref\s+\d+", b"startxref\n0", data)
        with pdf_module.open(stream=data, filetype="pdf") as doc:
            assert doc.is_repaired
    source = tmp_path / "bad.pdf"
    source.write_bytes(data)
    with pytest.raises(d.DocumentError):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="pdf")
    assert not list(tmp_path.glob("pair.*"))
    assert source.read_bytes() == data


def test_failed_publication_rolls_back_complete_native_fallback(tmp_path, monkeypatch, pdf_module):
    data = make_pdf(pdf_module, ["Complete model-owned native source 2026"])
    fake_chunks(monkeypatch, pdf_module, [""])
    source = tmp_path / "original.pdf"
    source.write_bytes(data)
    link = d.os.link
    calls = 0
    def fail_second(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publication failure")
        link(src, dst)
    monkeypatch.setattr(d.os, "link", fail_second)
    with pytest.raises(OSError, match="simulated"):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="pdf")
    assert set(tmp_path.iterdir()) == {source}
    assert source.read_bytes() == data
