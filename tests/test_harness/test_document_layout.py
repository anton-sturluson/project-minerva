"""Project-owned financial layout regressions; never use live issuer fixtures."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from harness.cli import app
from minerva import documents as d


@pytest.fixture
def pdf_module():
    return pytest.importorskip("pymupdf")


@pytest.fixture
def wide_markdown():
    # Currency/spacer columns and duplicated long headers are legitimate native
    # financial-table output. Neither the columns nor their labels may be lost.
    header = ["Financial metric"] + [f"Three Months Ended September 30 Class {i}" for i in range(16)]
    rows = [["Net income available to common stockholders"] + ["$", "1,222"] * 7 + ["$", "12,551"],
            ["Diluted earnings per common share"] + ["$", "2.89"] * 7 + ["$", "16.50"]]
    table = "\n".join("| " + " | ".join(row) + " |" for row in [header, ["---"] * 17, *rows])
    # The previous bag-of-words check passes despite losing the table's last
    # columns, since the same amounts appear in this legitimate prose summary.
    return ("# Complete financial source\n\nOpening body marker.\n\n"
            "Summary amounts: " + " ".join(["1,222"] * 14 + ["12,551"] + ["2.89"] * 14 + ["16.50"]) +
            "\n\n" + table + "\n\nClosing body marker.\n")


def require_renderer():
    if not shutil.which("md2pdf"):
        pytest.skip("integration requires md2pdf on PATH")


def old_render(tmp_path, markdown):
    require_renderer()
    md, pdf, css = (tmp_path / name for name in ("old.md", "old.pdf", "old.css"))
    md.write_text(markdown)
    css.write_text("table { break-inside: auto; page-break-inside: auto; }\n"
                   "thead { display: table-header-group; }\n"
                   "tr { break-inside: avoid; page-break-inside: avoid; }\n")
    subprocess.run([shutil.which("md2pdf"), str(md), "--output", str(pdf), "--extra-css", str(css)],
                   capture_output=True, text=True, check=True)
    return pdf.read_bytes()


def test_wide_financial_columns_readable_visible_and_complete(wide_markdown, pdf_module):
    require_renderer()
    data, count = d.render_pdf(wide_markdown)
    d._verify_rendered_layout(wide_markdown, data)
    with pdf_module.open(stream=data, filetype="pdf") as doc:
        assert count == len(doc)
        assert any(page.rect.width > 1100 for page in doc)
        text = "\n".join(page.get_text() for page in doc)
        assert "Complete financial source" in text and "Opening body marker" in text and "Closing body marker" in text
        assert text.count("12,551") >= 2 and text.count("16.50") >= 2
        for page in doc:
            for word in page.get_text("words", clip=pdf_module.INFINITE_RECT()):
                assert (page.rect + (-1, -1, 1, 1)).contains(word[:4])
            # Financial content stays at a real 9pt, not fit-to-page microtype.
            for span in page.get_texttrace():
                if "12,551" in "".join(chr(c[0]) for c in span["chars"]):
                    assert span["size"] >= 9


def test_previous_clipped_pdf_passes_wordbag_but_is_rejected(tmp_path, wide_markdown, pdf_module, monkeypatch):
    data = old_render(tmp_path, wide_markdown)
    _, pages = d.inspect_pdf(data)
    d._verify_rendered_text(wide_markdown, pages)
    with pytest.raises(d.DocumentError, match="outside page"):
        d._verify_rendered_layout(wide_markdown, data)
    # A converter exit 0 cannot publish the known-bad PDF or partial companions.
    def bad_converter(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_bytes(data)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(d.subprocess, "run", bad_converter)
    source = tmp_path / "source.md"
    source.write_text(wide_markdown)
    before = d.sha256(source.read_bytes())
    with pytest.raises(d.DocumentError, match="outside page"):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="markdown")
    assert not list(tmp_path.glob("pair.*"))
    assert d.sha256(source.read_bytes()) == before
    result = CliRunner().invoke(app, ["documents", "pair", str(source), "--from", "markdown",
                                     "--output", str(tmp_path / "cli-pair")])
    assert result.exit_code == 1 and "outside page" in result.output
    assert not list(tmp_path.glob("cli-pair.*"))


def test_missing_amount_occurrences_and_invisible_text_do_not_pass(pdf_module):
    with pdf_module.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Opening 12,551 Closing")
        page.insert_text((72, 100), "16.50", render_mode=3)
        data = doc.tobytes()
    with pytest.raises(d.DocumentError, match="financial amount coverage.*1"):
        d._verify_rendered_layout("Opening 12,551 16.50 Closing", data)
    with pytest.raises(d.DocumentError, match="financial amount coverage.*1"):
        d._verify_rendered_layout("12,551 12,551", data)
    # Invisible URL targets are not expected displayed financial values.
    d._verify_rendered_layout("[Opening](https://example.com/16.50) 12,551 Closing", data)


def test_financial_guard_separates_cells_in_one_paint_span(pdf_module):
    with pdf_module.open() as doc:
        page = doc.new_page()
        writer = pdf_module.TextWriter(page.rect)
        writer.append((72, 72), "12,551")
        writer.append((172, 72), "11,848")
        writer.append((72, 92), "16.50")
        writer.append((172, 92), "16.32")
        writer.write_text(page)
        d._verify_rendered_layout("12,551 11,848 16.50 16.32", doc.tobytes())


@pytest.mark.parametrize("kind", ["13f", "transcript"])
def test_narrow_sources_keep_portrait_and_full_body(kind, pdf_module):
    require_renderer()
    if kind == "13f":
        body = "| Field | Value |\n| --- | --- |\n| Issuer | Example Corp |\n| Shares | 12,345 |\n| Value | 67,890 |\n"
    else:
        body = "\n\n".join(f"Speaker {i}: Complete prepared remarks and questions. Earnings were 16.50 per share." for i in range(60))
    md = "# Complete source\n\nOPENING_MARKER\n\n" + body + "\n\nFINAL_CLOSE_MARKER\n"
    data, _ = d.render_pdf(md)
    with pdf_module.open(stream=data, filetype="pdf") as doc:
        assert all(page.rect.width == 612 for page in doc)
        text = "\n".join(page.get_text() for page in doc)
        assert "OPENING_MARKER" in text and "FINAL_CLOSE_MARKER" in text
        if kind == "transcript":
            assert "Speaker 59" in text and text.count("16.50") == 60
        else:
            assert "12,345" in text and "67,890" in text


def test_ragged_native_table_never_discards_extra_cells(tmp_path, pdf_module):
    require_renderer()
    md = ("# Native financial source\n\nOpening complete body marker.\n\n"
          "| Financial note caption |\n| --- |\n"
          "| Current period | $ | 29,166 | $ | 27,737 |\n"
          "| Ending balance | $ | 31,158 | $ | 28,812 |\n\nClosing body marker.\n")
    prepared = d._pdf_markdown(md)
    assert d._content_tokens(d._displayed_body(prepared)) == d._content_tokens(d._displayed_body(md))
    source = tmp_path / "source.md"
    source.write_text(md)
    receipt = d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="markdown")
    assert source.read_text() == md
    assert (tmp_path / "pair.md").read_text().endswith(md)
    assert receipt["source_sha256"] == d.sha256(md.encode())
    with pdf_module.open(tmp_path / "pair.pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        assert all(token in text for token in ["29,166", "27,737", "31,158", "28,812"])
    before = {p.name: p.read_bytes() for p in tmp_path.glob("pair.*")}
    with pytest.raises(d.DocumentError, match="no overwrite"):
        d.create_pair(source=str(source), stem=tmp_path / "pair", source_format="markdown")
    assert before == {p.name: p.read_bytes() for p in tmp_path.glob("pair.*")}


def test_oversized_exhibit_header_is_not_silently_omitted(pdf_module):
    require_renderer()
    description = "Full certification description and explanatory information. " * 12
    md = ("# Full exhibits\n\nOpening source marker.\n\n"
          "| Exhibit Number 31.1 32.1 | " + description + " | Form | File number | Exhibit | Date | Registrant |\n"
          "| --- | --- | --- | --- | --- | --- | --- |\n"
          "| 104 | Complete data file | 10-Q | 12345 | 104 | Today | Example |\n\nClosing source marker.\n")
    data, _ = d.render_pdf(md)
    with pdf_module.open(stream=data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        assert "31.1" in text and "32.1" in text
        assert d._content_tokens(text).count("certification") >= 12
        assert "Closing source marker" in text


def test_render_preparation_preserves_escaped_pipes_and_fenced_code():
    md = ("| Caption |\n| --- |\n| A \\| B | 12,551 |\n\n"
          "```markdown\n| Literal caption |\n| --- |\n| Untouched | 16.50 |\n```\n")
    prepared = d._pdf_markdown(md)
    assert "A \\| B | 12,551" in prepared
    assert prepared.split("```markdown", 1)[1] == md.split("```markdown", 1)[1]
    assert d._content_tokens(d._displayed_body(prepared)) == d._content_tokens(d._displayed_body(md))


@pytest.mark.parametrize("columns,minimum_width", [(8, 790), (11, 1190), (25, 1683)])
def test_table_page_width_adapts_without_shrinking_digits(columns, minimum_width, pdf_module):
    require_renderer()
    rows = [["Metric"] + [f"Accumulated Other Comprehensive Income Class {i}" for i in range(columns - 1)],
            ["---"] * columns,
            ["Complete financial value"] + ["12,551"] * (columns - 2) + ["16.32"]]
    md = "# Financial source\n\n" + "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
    data, _ = d.render_pdf(md)
    with pdf_module.open(stream=data, filetype="pdf") as doc:
        assert max(page.rect.width for page in doc) >= minimum_width
        text = "\n".join(page.get_text() for page in doc)
        assert text.count("12,551") == columns - 2 and text.count("16.32") == 1
        assert all(span["size"] >= 9 for page in doc for span in page.get_texttrace()
                   if "16.32" in "".join(chr(c[0]) for c in span["chars"]))


def test_paragraph_fused_to_pipe_header_keeps_financial_amounts(pdf_module):
    require_renderer()
    prose = "Full cash flow explanation and financing details. " * 30 + "Cash inflows were 23.1 billion and outflows were 28.5 billion."
    md = ("# Complete source\n\n" + prose + " | Period | Period | Change | Change | Prior | Prior | Unit | Extra |\n"
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
          "| Cash flow | $ | 23,103 | 184% | $ | 8,140 | USD | Complete | |\n\nFinal source marker.\n")
    prepared = d._pdf_markdown(md)
    assert d._content_tokens(d._displayed_body(prepared)) == d._content_tokens(d._displayed_body(md))
    data, _ = d.render_pdf(md)
    with pdf_module.open(stream=data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        assert all(token in text for token in ["23.1", "28.5", "23,103", "8,140", "Final source marker"])


def test_layout_normalization_never_repairs_broken_financial_digits():
    assert d._content_tokens("Compre\u2010\nhensive in\u00ad\ncome") == ["comprehensive", "income"]
    assert not d._financial_amounts("12,\n551 16.\n50")
    assert d._financial_amounts("12,551, 16.50. 16.32") == {"12,551": 1, "16.50": 1, "16.32": 1}


@pytest.mark.parametrize("spaces", range(4))
def test_valid_indented_table_never_gains_a_header_cell(spaces):
    indent = " " * spaces
    md = "".join(indent + row + "\n" for row in ["| Label | 2026 | 2025 |", "| --- | --- | --- |", "| Revenue | 100 | 90 |"])
    assert d._pdf_markdown(md) == md


@pytest.mark.parametrize("spaces", range(4))
def test_indented_ragged_table_pads_without_shifting_cells(spaces):
    indent = " " * spaces
    md = "".join(indent + row + "\n" for row in ["| Caption |", "| --- |", "| Revenue | 12,551 | 16.50 |"])
    prepared = d._pdf_markdown(md)
    cells = [[cell.strip() for cell in row.strip()[1:-1].split("|")] for row in prepared.splitlines()]
    assert cells == [["Caption", "", ""], ["---", "---", "---"], ["Revenue", "12,551", "16.50"]]
    assert all(row.startswith(indent + "|") for row in prepared.splitlines())
    assert d._content_tokens(d._displayed_body(prepared)) == d._content_tokens(d._displayed_body(md))


@pytest.mark.parametrize("indent", ["    ", "     ", "\t", " \t", "\t ", "   \t"])
def test_indented_code_is_not_reinterpreted_as_a_table(indent):
    rows = ["| Caption |", "| --- |", "| Revenue | 12,551 | 16.50 |", "", "Fused prose | 2026 | 2025 |", "| --- | --- | --- |", "| Value | 100 | 90 |"]
    md = "".join(indent + row + "\n" for row in rows)
    assert d._pdf_markdown(md) == md


@pytest.mark.parametrize("spaces", range(4))
def test_actual_indented_fused_paragraph_header_still_rescued(spaces):
    indent = " " * spaces
    md = (indent + "Fused cash flow explanation | 2026 | 2025 |\n" +
          indent + "| --- | --- | --- |\n" + indent + "| Revenue | 12,551 | 16.50 |\n")
    prepared = d._pdf_markdown(md)
    assert prepared == "|" + md
    assert d._content_tokens(d._displayed_body(prepared)) == d._content_tokens(d._displayed_body(md))


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_indented_tables_inside_fences_remain_literal(fence):
    md = "  " + fence + "markdown\n  | Caption |\n  | --- |\n  | Value | 12,551 | 16.50 |\n  " + fence + "\n"
    assert d._pdf_markdown(md) == md


def test_mixed_legal_indentation_and_long_header_keep_first_cell():
    long_cell = "Full model-owned financial explanation. " * 9
    md = "  | " + long_cell + "|\n | --- |\n   | Value | 12,551 | 16.50 |\n"
    prepared = d._pdf_markdown(md)
    assert prepared.startswith('  | <span class="minerva-long-cell"></span> ' + long_cell)
    assert [row.count("|") for row in prepared.splitlines()] == [4, 4, 4]
    assert d._content_tokens(d._displayed_body(prepared)) == d._content_tokens(d._displayed_body(md))


def test_indented_code_separator_does_not_create_fused_table():
    md = "Normal prose | 2026 | 2025 |\n    | --- | --- | --- |\n    | Value | 100 | 90 |\n"
    assert d._pdf_markdown(md) == md
