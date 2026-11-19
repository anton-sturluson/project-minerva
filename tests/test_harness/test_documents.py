"""Behavior tests with small, project-owned PDF/XML/HTML fixtures."""
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from typer.testing import CliRunner
from harness.cli import app
from harness.commands import sec
from harness.config import HarnessSettings
from minerva import documents as d
from minerva.filing_documents import full_13f_markdown, collect_filing, collect_attachment


@pytest.fixture
def pdf_bytes():
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for text in ["FIRST PAGE project-owned test source.", "LAST PAGE complete document marker."]:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    return doc.tobytes()


def test_pdf_all_pages_original_hash_and_no_clobber(tmp_path, pdf_bytes):
    src = tmp_path / "source.pdf"
    src.write_bytes(pdf_bytes)
    stem = tmp_path / "pair.v1"
    receipt = d.create_pair(source=str(src), stem=stem, source_format="pdf", source_url="https://example.com/original.pdf")
    assert Path(str(stem) + ".pdf").read_bytes() == src.read_bytes()
    text = Path(str(stem) + ".md").read_text()
    assert 'id="page-1"' in text and 'id="page-2"' in text
    assert "FIRST PAGE" in text and "LAST PAGE" in text
    assert receipt["markdown_pages"] == receipt["pdf_pages"] == 2
    assert receipt["source_sha256"] == d.sha256(pdf_bytes)
    assert receipt["source"] == "https://example.com/original.pdf"
    assert "No OCR" in text and "Images" in text
    with pytest.raises(d.DocumentError, match="Existing"):
        d.create_pair(source=str(src), stem=stem, source_format="pdf")
    assert src.read_bytes() == pdf_bytes


def test_pdf2md_does_not_modify_input_or_existing_output(tmp_path, pdf_bytes):
    src, out = tmp_path / "input.pdf", tmp_path / "output.md"
    src.write_bytes(pdf_bytes)
    result = d.pdf2md(src, out)
    assert result["markdown_pages"] == 2
    before = out.read_bytes()
    with pytest.raises(d.DocumentError, match="overwrite"):
        d.pdf2md(src, out)
    assert out.read_bytes() == before
    assert src.read_bytes() == pdf_bytes
    with pytest.raises(d.DocumentError, match="differ"):
        d.pdf2md(src, src)


@pytest.mark.parametrize("payload", [b"", b"not pdf", b"%PDF-1.7\ntruncated"])
def test_bad_pdf_no_output(tmp_path, payload):
    source = tmp_path / "bad.pdf"
    source.write_bytes(payload)
    with pytest.raises(d.DocumentError):
        d.pdf2md(source, tmp_path / "bad.md")
    assert not (tmp_path / "bad.md").exists()


def test_partial_pair_clearly_fails_without_clobber(tmp_path):
    (tmp_path / "p.md").write_text("existing partial source")
    with pytest.raises(d.DocumentError, match="partial"):
        d.create_pair(source="does-not-exist", stem=tmp_path / "p", source_format="pdf")
    assert (tmp_path / "p.md").read_text() == "existing partial source"
    assert not (tmp_path / "p.pdf").exists()


def test_parser_failure_and_page_loss_are_errors(tmp_path, pdf_bytes, monkeypatch):
    class BadDoc:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def to_markdown(self, **kwargs): return [{"text": "only first"}]
    monkeypatch.setattr(d, "inspect_pdf", lambda data: (2, ["first", "last"]))
    monkeypatch.setattr(d, "_pymupdf", lambda **kwargs: SimpleNamespace(open=lambda **kw: BadDoc()))
    with pytest.raises(d.DocumentError, match="all 2 pages"):
        d.pdf_markdown(pdf_bytes, "source.pdf")
    monkeypatch.setattr(BadDoc, "to_markdown", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("parser broken")))
    with pytest.raises(d.DocumentError, match="parser failed"):
        d.pdf_markdown(pdf_bytes, "source.pdf")


def test_markdown_fallback_generated_label_and_tail(tmp_path, monkeypatch, pdf_bytes):
    source = tmp_path / "transcript.md"
    body = "# Complete call\n\n" + "Prepared remarks and full questions.\n" * 20 + "FINAL OPERATOR CLOSE\n"
    source.write_text(body)
    captured = []
    def render(text):
        captured.append(text)
        return pdf_bytes, 2
    monkeypatch.setattr(d, "render_pdf", render)
    receipt = d.create_pair(source=str(source), stem=tmp_path / "fallback", source_format="markdown", source_url="https://example.com/call")
    assert receipt["pdf_provenance"].startswith("generated")
    assert "NOT a publisher-original PDF" in captured[0]
    assert captured[0].endswith(body)
    assert source.read_text() == body


def test_missing_md2pdf_clean_no_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "call.md"
    source.write_text("Complete transcript body. " * 10)
    monkeypatch.setattr(d.shutil, "which", lambda name: None)
    with pytest.raises(d.DocumentError, match="md2pdf is required"):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="markdown")
    assert not list(tmp_path.glob("pair.*"))


@pytest.mark.parametrize("body", ["short", "", "<html><body>" + "Not Markdown. " * 20 + "</body></html>"])
def test_short_or_html_disguised_markdown_rejected(tmp_path, body):
    source = tmp_path / "call.md"
    source.write_text(body)
    with pytest.raises(d.DocumentError):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="markdown")


def xml_fixture(count=3, total=None):
    primary = f'''<edgarSubmission><submissionType>13F-HR/A</submissionType><coverPage><reportCalendarOrQuarter>09-30-2026</reportCalendarOrQuarter><isAmendment>true</isAmendment><amendmentType>NEW HOLDINGS</amendmentType></coverPage><tableEntryTotal>{count}</tableEntryTotal><tableValueTotal>{count * 10 if total is None else total}</tableValueTotal><signature>Original signed cover</signature></edgarSubmission>'''.encode()
    rows = []
    for i in range(count):
        option = "<putCall>Call</putCall>" if i % 2 else ""
        rows.append(f'''<infoTable><nameOfIssuer>Issuer {i}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>123456789</cusip><value>10</value><shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>{option}<investmentDiscretion>DEFINED</investmentDiscretion><otherManager>1</otherManager><otherManager>2</otherManager><votingAuthority><Sole>1</Sole><Shared>2</Shared><None>2</None></votingAuthority></infoTable>''')
    return primary, ("<informationTable>" + "".join(rows) + "</informationTable>").encode()


def test_13f_no_aggregation_all_fields_csv_no_head_cap():
    primary, table = xml_fixture(65)
    text, info, csv_text = full_13f_markdown(primary, [table], filed_date="2026-11-16", report_period="2026-09-30")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows) == info["table_rows"] == 65
    assert len({r["cusip"] for r in rows}) == 1
    assert len([r for r in rows if r.get("putCall")]) == 32
    assert rows[-1]["nameOfIssuer"] == "Issuer 64"
    assert rows[-1]["otherManager"] == "1; 2"
    assert rows[-1]["votingAuthority/None"] == "2"
    assert "Source row 65" in text and "Original signed cover" in text
    assert info["amendment_type"] == "NEW HOLDINGS"
    assert info["table_value_usd"] == "650"
    assert info["reported_value_unit"] == "USD"


def test_13f_historical_units_and_completeness():
    primary, table = xml_fixture()
    _, info, _ = full_13f_markdown(primary, [table], filed_date="2022-11-16")
    assert info["reported_value_unit"] == "USD thousands" and info["table_value_usd"] == "30000"
    with pytest.raises(d.DocumentError, match="declared"):
        full_13f_markdown(primary.replace(b">3<", b">4<"), [table], filed_date="2026-11-16")
    with pytest.raises(d.DocumentError, match="value differs"):
        full_13f_markdown(primary.replace(b">30<", b">999<"), [table], filed_date="2026-11-16")
    with pytest.raises(d.DocumentError, match="period differs"):
        full_13f_markdown(primary, [table], filed_date="2026-11-16", report_period="2026-06-30")


def test_invalid_formats_cli_exit_and_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "Company", lambda *a: pytest.fail("invalid format must not fetch"))
    result = sec.download_filing_command("EXAMPLE", file_format="pdf", settings=HarnessSettings(workspace_root=tmp_path))
    assert result.exit_code == 1 and b"--format" in result.stderr
    result = CliRunner().invoke(app, ["documents", "pair", "x", "--from", "html", "--output", str(tmp_path / "p")])
    assert result.exit_code == 1 and "--from must" in result.output


def test_exact_html_native_conversion_and_exhibit_identity(tmp_path, monkeypatch, pdf_bytes):
    monkeypatch.setattr(d, "render_pdf", lambda text: (pdf_bytes, 2))
    html = "<html><body><h1>Full native source</h1><p>" + "Complete source content. " * 20 + "</p><p>FINAL NATIVE MARKER</p></body></html>"
    filing = SimpleNamespace(form="10-Q", html=lambda: html, accession_no="0001", filing_date="2026-11-01", document=SimpleNamespace(url="https://example.com/full.htm"))
    collect_filing(filing, tmp_path / "full")
    assert "FINAL NATIVE MARKER" in (tmp_path / "full.md").read_text()
    assert (tmp_path / "full.sources/original.html").read_text() == html
    exhibit = SimpleNamespace(content=html.replace("FINAL NATIVE", "FINAL EXHIBIT"), url="https://example.com/ex99.htm")
    receipt = collect_attachment(exhibit, tmp_path / "release", accession="0001")
    assert receipt["source"] == exhibit.url
    assert "FINAL EXHIBIT MARKER" in (tmp_path / "release.md").read_text()


def test_bulk_full_pairs_does_not_skip_partial_or_hide_errors(tmp_path, monkeypatch):
    filing = SimpleNamespace(form="10-K", accession_no="0001", filing_date="2026-11-01")
    monkeypatch.setattr(sec, "Company", lambda ticker: object())
    monkeypatch.setattr(sec, "_configure_edgar", lambda settings: None)
    monkeypatch.setattr(sec, "_list_filings", lambda company, form, limit: [filing] if form == "10-K" else [])
    monkeypatch.setattr(sec, "collect_filing", lambda *a: (_ for _ in ()).throw(d.DocumentError("partial pair exists")))
    result = sec.bulk_download_command(ticker="EXAMPLE", output_dir=str(tmp_path), annual=1, quarters=0, earnings=0, include_financials=False, settings=HarnessSettings(workspace_root=tmp_path))
    assert result.exit_code == 1 and b"partial pair exists" in result.stderr
    assert b"Errors: 0" not in result.stdout


def test_amendment_exact_accession_selection_and_identity_mismatch():
    original = SimpleNamespace(form="13F-HR", accession_no="original")
    amended = SimpleNamespace(form="13F-HR/A", accession_no="amended")
    class Company:
        def get_filings(self, *, form, accession_number):
            return [row for row in [original, amended] if row.form == form and row.accession_no == accession_number]
    assert sec._filing_for_accession(Company(), form="13F-HR/A", accession="amended") is amended
    with pytest.raises(ValueError, match="exactly one"):
        sec._filing_for_accession(Company(), form="13F-HR", accession="amended")


def test_renderer_failure_no_partial_pair(tmp_path, monkeypatch):
    source = tmp_path / "call.md"
    source.write_text("Full call text. " * 20)
    monkeypatch.setattr(d.shutil, "which", lambda name: "md2pdf")
    monkeypatch.setattr(d.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=2, stderr="bad converter", stdout=""))
    with pytest.raises(d.DocumentError, match="md2pdf failed"):
        d.create_pair(source=str(source), stem=tmp_path / "p", source_format="markdown")
    assert not list(tmp_path.glob("p.*"))


def test_bulk_rejects_unrelated_8k_and_pairs_only_matching_release(tmp_path, monkeypatch):
    wrong = SimpleNamespace(accession_no="unrelated", filing_date="2026-11-01", obj=lambda: SimpleNamespace(items=["Item 8.01"]), exhibits=[])
    exhibit = SimpleNamespace(document_type="EX-99.1", url="https://example.com/ex.htm")
    right = SimpleNamespace(accession_no="earnings", filing_date="2026-10-23", obj=lambda: SimpleNamespace(items=["Item 2.02"]), exhibits=[exhibit])
    monkeypatch.setattr(sec, "Company", lambda ticker: object())
    monkeypatch.setattr(sec, "_list_filings", lambda company, form, limit: [wrong, right] if form == "8-K" else [])
    seen = []
    monkeypatch.setattr(sec, "collect_attachment", lambda attachment, stem, accession: seen.append((attachment, accession)))
    sec._bulk_download_one(ticker="EXAMPLE", base_output=tmp_path, annual=0, quarters=0, earnings=1, include_financials=False)
    assert seen == [(exhibit, "earnings")]


def test_filename_contract_rejects_extensions_and_output_pdf(tmp_path, pdf_bytes):
    src = tmp_path / "source.pdf"
    src.write_bytes(pdf_bytes)
    with pytest.raises(d.DocumentError, match="stem"):
        d.create_pair(source=str(src), stem=tmp_path / "ambiguous.pdf", source_format="pdf")
    with pytest.raises(d.DocumentError, match=".md extension"):
        d.pdf2md(src, tmp_path / "other.pdf")
    assert src.read_bytes() == pdf_bytes


def test_13f_rejects_malformed_xml_and_invalid_numeric_identity():
    from xml.etree import ElementTree as ET
    primary, table = xml_fixture()
    with pytest.raises(ET.ParseError):
        full_13f_markdown(primary, [table[:-20]], filed_date="2026-11-16")
    with pytest.raises(d.DocumentError, match="value or share quantity"):
        full_13f_markdown(primary, [table.replace(b"<value>10</value>", b"<value>NaN</value>", 1)], filed_date="2026-11-16")
    with pytest.raises(d.DocumentError, match="identity"):
        full_13f_markdown(primary, [table.replace(b"<cusip>123456789</cusip>", b"<cusip>123</cusip>", 1)], filed_date="2026-11-16")


@pytest.mark.parametrize("form", ["13F-HR", "10-K", "10-Q"])
def test_latest_and_bulk_limit_exclude_newer_amendment_real_entity_filings(form):
    import pyarrow as pa
    from datetime import date
    from edgar.entity.filings import EntityFilings
    rows = []
    for amended, day in [(False, 16), (True, 17)]:
        rows.append(dict(form=form + ("/A" if amended else ""),
                         filing_date=date(2026, 11, day), reportDate="2026-09-30",
                         acceptanceDateTime=None, accession_number="amended" if amended else "original",
                         fileNumber="028-00000", items="", size=100, primaryDocument="primary.xml",
                         primaryDocDescription="", isXBRL=False, isInlineXBRL=False))
    filings = EntityFilings(pa.Table.from_pylist(rows), cik=123456, company_name="Example Fund")
    class Company:
        def get_filings(self, *, form, amendments=True):
            return filings.filter(form=form, amendments=amendments)
    assert sec._filing_for_accession(Company(), form=form, accession=None).accession_no == "original"
    assert [f.accession_no for f in sec._list_filings(Company(), form=form, limit=5)] == ["original"]
    assert sec._latest_filing(Company(), form=form + "/A").accession_no == "amended"


@pytest.mark.parametrize("available", [0, 1])
def test_bulk_missing_annual_quarterly_counts_are_incomplete(tmp_path, monkeypatch, available):
    monkeypatch.setattr(sec, "Company", lambda ticker: object())
    monkeypatch.setattr(sec, "_configure_edgar", lambda settings: None)
    def filings(company, *, form, limit):
        return [SimpleNamespace(form=form, accession_no="original", filing_date="2026-11-16")] if available and limit else []
    monkeypatch.setattr(sec, "_list_filings", filings)
    monkeypatch.setattr(sec, "collect_filing", lambda *args: None)
    result = sec.bulk_download_command(ticker="EXAMPLE", output_dir=str(tmp_path), annual=5, quarters=4,
                                      earnings=0, include_financials=False, settings=HarnessSettings(workspace_root=tmp_path))
    assert result.exit_code == 1
    assert f"Requested 5 10-K filings; available {available}".encode() in result.stderr
    assert f"Requested 4 10-Q filings; available {available}".encode() in result.stderr
    assert b"Errors: 0" not in result.stdout


def test_bulk_financials_rerun_preserves_existing_and_earlier_errors(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.setattr(sec, "Company", lambda ticker: object())
    monkeypatch.setattr(sec, "_list_filings", lambda *a, **kw: [])
    monkeypatch.setattr(sec, "_fetch_financials_frame", lambda *a, **kw: pd.DataFrame({"2026": [10]}, index=["Revenue"]))
    args = dict(ticker="EXAMPLE", base_output=tmp_path, annual=0, quarters=0, earnings=0, include_financials=True)
    sec._bulk_download_one(**args)
    before = {p.name: p.read_bytes() for p in (tmp_path / "financials").iterdir()}
    monkeypatch.setattr(sec, "_fetch_financials_frame", lambda *a, **kw: pytest.fail("existing exports must not fetch"))
    assert "  Errors: 0" in sec._bulk_download_one(**args)
    with pytest.raises(d.DocumentError, match="Requested 5 10-K"):
        sec._bulk_download_one(**{**args, "annual": 5})
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "financials").iterdir()}


@pytest.mark.parametrize("symlink", [False, True])
def test_archive_path_reserves_entire_pair_before_read_or_conversion(tmp_path, monkeypatch, symlink):
    archive = tmp_path / "p.sources"
    outside = tmp_path / "outside"
    outside.mkdir()
    if symlink:
        archive.symlink_to(outside, target_is_directory=True)
    else:
        archive.mkdir()
        (archive / "stale.txt").write_text("unrelated")
    monkeypatch.setattr(d, "read_source", lambda *a: pytest.fail("must fail before reading/converting"))
    with pytest.raises(d.DocumentError, match="partial pair"):
        d.create_pair(source="unused", stem=tmp_path / "p", source_format="markdown", raw_files={"new.xml": b"<root/>"})
    assert not list(outside.iterdir())
    assert not (tmp_path / "p.pdf").exists() and not (tmp_path / "p.md").exists()
    assert not (tmp_path / "p.source.json").exists()
    if not symlink:
        assert (archive / "stale.txt").read_text() == "unrelated"


@pytest.mark.parametrize("case", ["declared-malformed", "unknown-malformed", "declared-missing", "unrelated-valid", "ordered-parts"])
def test_13f_attachment_inventory_and_unreadable_candidates(tmp_path, monkeypatch, case):
    import httpx
    import minerva.filing_documents as fd
    import time
    monkeypatch.setattr(time, "sleep", lambda *a: None)
    primary, table = xml_fixture(23)
    accession = "0000000000-26-000001"
    kind = "XML" if case in {"unknown-malformed", "unrelated-valid"} else "INFORMATION TABLE"
    submission = (f"<DOCUMENT>\n<TYPE>13F-HR\n<FILENAME>primary.xml\n<TEXT>cover</TEXT></DOCUMENT>\n"
                  f"<DOCUMENT>\n<TYPE>{kind}\n<FILENAME>part2.xml\n<TEXT>second</TEXT></DOCUMENT>\n"
                  "<DOCUMENT>\n<TYPE>INFORMATION TABLE\n<FILENAME>table.xml\n<TEXT>first</TEXT></DOCUMENT>").encode()
    names = ["primary.xml", "table.xml"] + ([] if case == "declared-missing" else ["part2.xml"])
    payloads = {"index.json": json.dumps({"directory": {"item": [{"name": n} for n in names]}}).encode(),
                accession + ".txt": submission, "primary.xml": primary, "table.xml": table,
                "part2.xml": b"<metadata>unrelated</metadata>" if case == "unrelated-valid" else b"<informationTable>truncated"}
    if case == "ordered-parts":
        payloads["primary.xml"], payloads["table.xml"] = xml_fixture(24)
        _, first = xml_fixture(23)
        _, second = xml_fixture(1)
        payloads["table.xml"], payloads["part2.xml"] = first, second
    requests = []
    def get(self, url):
        name = url.rsplit("/", 1)[-1]
        requests.append(name)
        return SimpleNamespace(content=payloads[name], raise_for_status=lambda: None)
    monkeypatch.setattr(httpx.Client, "get", get)
    monkeypatch.setattr(fd, "_native_pair", lambda data, text, stem, fmt, url, raw, metadata: (raw, metadata))
    filing = SimpleNamespace(accession_no=accession, cik=123456, form="13F-HR", filing_date="2026-11-16",
                             period_of_report="2026-09-30", document=SimpleNamespace(document="primary.xml"))
    if case in {"unrelated-valid", "ordered-parts"}:
        raw, metadata = fd.collect_13f(filing, tmp_path / "p")
        if case == "unrelated-valid":
            assert metadata["skipped_non_table_xml"] == ["part2.xml"]
            assert metadata["table_rows"] == 23
        else:
            assert metadata["table_rows"] == 24
            assert [u.rsplit("/", 1)[-1] for u in metadata["table_urls"]] == ["part2.xml", "table.xml"]
            assert raw["part2.xml"] == payloads["part2.xml"] and raw["table.xml"] == payloads["table.xml"]
    else:
        with pytest.raises(d.DocumentError, match="Missing required|Unreadable"):
            fd.collect_13f(filing, tmp_path / "p")
    assert requests.index(accession + ".txt") < (requests.index("table.xml") if "table.xml" in requests else len(requests))
    assert not list(tmp_path.iterdir())


def test_title_only_valid_pdf_renderer_rejected_before_publication(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    source = tmp_path / "source.md"
    source.write_text("# Call title\n\nOPENING introduction\n\n" + "\n\n".join(f"Prepared remarks phrase {i} business results growth." for i in range(20)) + "\n\nFINAL_CLOSE operator goodbye")
    monkeypatch.setattr(d.shutil, "which", lambda *a: "md2pdf")
    def run(command, **kwargs):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "Only a title")
        doc.save(command[command.index("--output") + 1])
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(d.subprocess, "run", run)
    with pytest.raises(d.DocumentError, match="body text coverage unverified"):
        d.create_pair(source=str(source), stem=tmp_path / "p", source_format="markdown")
    assert not list(tmp_path.glob("p.*"))


def test_render_check_tolerates_formatting_but_requires_close():
    source = "# Opening **business** remarks\n\n" + "Continued growth and results. " * 50 + "\n\nUnique final closing statement operator goodbye."
    d._verify_rendered_text(source, ["Opening business remarks " + "Continued growth and results. " * 50, "Unique final closing statement operator goodbye."])
    with pytest.raises(d.DocumentError, match="coverage unverified"):
        d._verify_rendered_text(source, ["Opening business remarks Continued growth and results."])


def test_financials_cash_uses_current_edgartools_api(monkeypatch):
    expected = object()
    class Company:
        def cash_flow_statement(self, *, periods, period, as_dataframe):
            assert (periods, period, as_dataframe) == (5, "annual", True)
            return expected
    monkeypatch.setattr(sec, "Company", lambda ticker: Company())
    assert sec._fetch_financials_frame("EXAMPLE", periods=5, statement_type="cash") is expected
