"""Offline coverage, validation, and CLI tests for the weekly ideas pipeline."""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness import hf_ideas
from harness.cli import app, dispatch_command
from harness.commands import ideas
from harness.config import HarnessSettings
from harness.output import CommandResult

runner = CliRunner()

ISSUE_TEXT = """HF Best Ideas weekly roster

🔹 5N Plus Inc. (VNP CN) by Critical Minerals Fund
🔹 Advanced Micro Devices (AMD US) by Guinness Global Innovators Fund
🔹 Amrize by Alpine Fund
🔹 QV Investors by QV Investors Due Diligence

5N Plus Inc. ($VNP CN) Fund: Critical Minerals Fund
Thesis: critical-minerals exposure can support growth.
Analysis: The company has critical-minerals exposure and expanding capacity.

Advanced Micro Devices ($AMD US) Fund: Guinness Global Innovators Fund
Thesis: product execution supports share gains.
Analysis: Product execution supports share gains. Valuation remains a risk.
"""


def test_roster_parsing_keeps_stable_identities_and_issue_analyses() -> None:
    pitches = hf_ideas.parse_pitches(ISSUE_TEXT)
    analyses = hf_ideas.parse_issue_analyses(ISSUE_TEXT)

    assert len(pitches) == 4
    assert len({pitch["roster_id"] for pitch in pitches}) == 4
    assert sum(len(items) for items in analyses.values()) == 2
    assert sum(
        hf_ideas.find_issue_analysis(pitch, analyses) is not None
        for pitch in pitches
    ) == 2

    amrize = next(pitch for pitch in pitches if pitch["company"] == "Amrize")
    assert amrize["ticker"] == ""
    assert amrize["company_id"] == "amrize--no-symbol"
    qv = next(pitch for pitch in pitches if pitch["company"] == "QV Investors")
    assert qv["entity_type"] == "non-stock"
    assert qv["ticker"] == ""
    assert qv["company_id"] == "qv-investors--non-stock"


def test_public_fetch_records_foreign_missing_and_mismatch(tmp_path: Path) -> None:
    pitches = hf_ideas.parse_pitches(ISSUE_TEXT)
    groups = hf_ideas.group_pitches(pitches)
    calls: list[str] = []

    def getter(url: str) -> str:
        calls.append(url)
        if url.endswith("/VNP"):
            raise urllib.error.HTTPError(url, 404, "not found", None, None)
        return (
            "<html><body><h1>Advanced Micro Devices (AMD): the hedge fund thesis, "
            "in their own words</h1><p>Guinness Global Innovators Fund June 2026 "
            "AMD has named evidence. Read the full thesis →</p></body></html>"
        )

    records = hf_ideas.fetch_public_sources(
        groups, tmp_path, getter=getter, sleep_seconds=0
    )

    assert calls == [
        "https://www.hfbestideas.com/stock/VNP",
        "https://www.hfbestideas.com/stock/AMD",
    ]
    assert records["5n-plus-inc--vnp-cn"]["status"] == "http-error"
    assert "HTTP 404" in records["5n-plus-inc--vnp-cn"]["reason"]
    assert records["advanced-micro-devices--amd-us"]["status"] == "fetched"
    assert records["amrize--no-symbol"]["status"] == "not-requested"
    assert "no ticker" in records["amrize--no-symbol"]["reason"]
    assert records["qv-investors--non-stock"]["status"] == "not-requested"
    assert "non-stock" in records["qv-investors--non-stock"]["reason"]
    assert (tmp_path / "raw-public" / "advanced-micro-devices--amd-us.html").exists()
    assert (tmp_path / "public" / "advanced-micro-devices--amd-us.md").exists()


def test_foreign_source_document_retains_excerpt_and_resolution_reason() -> None:
    pitches = hf_ideas.parse_pitches(ISSUE_TEXT)
    analyses = hf_ideas.parse_issue_analyses(ISSUE_TEXT)
    pitch = next(item for item in pitches if item["company"] == "5N Plus Inc.")
    group = hf_ideas.group_pitches([pitch])[0]
    reason = (
        "HTTP 404 for the exact published ticker at "
        "https://www.hfbestideas.com/stock/VNP"
    )
    document = hf_ideas.render_source_document(
        group,
        analyses,
        {
            "status": "http-error",
            "reason": reason,
            "url": "https://www.hfbestideas.com/stock/VNP",
            "named_context": {},
        },
        issue_title="Issue",
        issue_url="https://example.test/issue",
        issue_date="2026-09-16",
    )

    assert pitch["issue_excerpt"] in document
    assert "critical-minerals exposure" in document
    assert reason in document
    assert "all foreign" not in document.lower()


def make_duplicate_report(
    tmp_path: Path, *, issue_analysis: bool = False
) -> tuple[Path, dict]:
    folder = tmp_path / "05-weekly-ideas" / "2026-01-02"
    (folder / "content").mkdir(parents=True)
    (folder / "extractions").mkdir()
    company_id = "example-co--ex-us"
    entries: list[dict] = []
    for number, fund in enumerate(("Named Fund A", "Named Fund B"), 1):
        entries.append(
            {
                "roster_id": f"{company_id}--named-fund-{number}",
                "company_id": company_id,
                "company": "Example Co.",
                "ticker": "EX",
                "exchange": "US",
                "symbol_as_published": "EX US",
                "fund": fund,
                "entity_type": "equity",
                "issue_excerpt": f"🔹 Example Co. (EX US) by {fund}",
                "issue_analysis": issue_analysis,
            }
        )
    group = {
        "company_id": company_id,
        "company": "Example Co.",
        "ticker": "EX",
        "exchange": "US",
        "entity_type": "equity",
        "roster_entries": entries,
    }
    issue_url = "https://example.test/issue"
    public_url = "https://example.test/stock/EX"
    contexts = {
        entry["roster_id"]: [f"{entry['fund']} June 2026 Named evidence {index}."]
        for index, entry in enumerate(entries, 1)
    }
    public = {
        "status": "fetched",
        "reason": "identity matched",
        "url": public_url,
        "named_context": contexts,
        "readable_file": f"public/{company_id}.md",
        "raw_file": f"raw-public/{company_id}.html",
    }
    manifest = {
        "schema_version": 2,
        "issue_title": "Two named funds",
        "issue_url": issue_url,
        "issue_date": "2026-01-02T12:00:00+00:00",
        "paywalled": False,
        "pitch_count": 2,
        "company_count": 1,
        "pitches": entries,
        "companies": [group],
        "public_sources": {company_id: public},
        "extraction_files": [f"content/{company_id}.md"],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "extraction-files.txt").write_text(
        f"content/{company_id}.md\n", encoding="utf-8"
    )
    write_source_document(folder, manifest)
    extraction_manifest = {
        "entries": [
            {
                "source": str(
                    (folder / "content" / f"{company_id}.md").resolve()
                ),
                "output": str(
                    (folder / "extractions" / f"{company_id}.md").resolve()
                ),
                "status": "ok",
                "error": None,
            }
        ]
    }
    (folder / "extractions" / "manifest.json").write_text(
        json.dumps(extraction_manifest), encoding="utf-8"
    )
    data = {
        "schema_version": 1,
        "company_id": company_id,
        "company": "Example Co.",
        "ticker": "EX",
        "exchange": "US",
        "entity_type": "equity",
        "company_summary": (
            "Named Fund A and Named Fund B both cite the published evidence, and "
            "both views remain separately attributed."
        ),
        "fund_views": [
            {
                "roster_id": entry["roster_id"],
                "featured_fund": entry["fund"],
                "commentary_date": "June 2026",
                "stance": "bull",
                "core_thesis": (
                    f"The fund cites named evidence {number}. "
                    "It treats that evidence as supportive."
                ),
                "source_basis": "issue" if issue_analysis else "public synopsis",
                "source_url": issue_url if issue_analysis else public_url,
                "supporting_quote": f"Named evidence {number}.",
                "unresolved_reason": "",
            }
            for number, entry in enumerate(entries, 1)
        ],
    }
    return folder, data


def write_source_document(
    folder: Path,
    manifest: dict,
    contexts: dict[str, list[str]] | None = None,
) -> Path:
    """Render the real per-fund source document the validator reads.

    Quote validation is scoped to one roster entry's evidence section, so the
    fixture must carry that structure instead of a flat blob of text.
    """
    group = manifest["companies"][0]
    public = dict(manifest["public_sources"][group["company_id"]])
    if contexts is not None:
        public["named_context"] = contexts
    document = hf_ideas.render_source_document(
        group,
        {},
        public,
        issue_title=manifest["issue_title"],
        issue_url=manifest["issue_url"],
        issue_date=manifest["issue_date"],
    )
    path = folder / "content" / f"{group['company_id']}.md"
    path.write_text(document, encoding="utf-8")
    return path


def load_manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def write_extraction(folder: Path, data: dict) -> Path:
    output = folder / "extractions" / "example-co--ex-us.md"
    output.write_text(json.dumps(data), encoding="utf-8")
    return output


def test_json_wrapper_duplicate_fund_coverage_and_attribution(tmp_path: Path) -> None:
    folder, data = make_duplicate_report(tmp_path)
    output = folder / "extractions" / "example-co--ex-us.md"
    output.write_text(
        "# Minerva answer\n\n```json\n" + json.dumps(data) + "\n```\n",
        encoding="utf-8",
    )

    coverage = hf_ideas.build_report(folder)

    assert coverage["roster_validated"] == 2
    assert coverage["companies_validated"] == 1
    assert coverage["warnings"] == []
    summary = (folder / "summary.md").read_text(encoding="utf-8")
    assert summary.count("### Example Co. (EX US)") == 1
    assert "Named Fund A" in summary and "Named Fund B" in summary
    assert "2/2 roster entries" in summary

    data["fund_views"][1]["featured_fund"] = "Wrong Fund"
    output.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(hf_ideas.PipelineError, match="fund attribution mismatch"):
        hf_ideas.build_report(folder)


def test_issue_analysis_cannot_be_replaced_by_public_history(tmp_path: Path) -> None:
    folder, data = make_duplicate_report(tmp_path, issue_analysis=True)
    data["fund_views"][0]["source_basis"] = "public synopsis"
    data["fund_views"][0]["source_url"] = "https://example.test/stock/EX"
    write_extraction(folder, data)

    with pytest.raises(
        hf_ideas.PipelineError,
        match="conflicts with available named-fund sources",
    ):
        hf_ideas.build_report(folder)


def test_empty_malformed_and_missing_extractions_fail_visibly(tmp_path: Path) -> None:
    with pytest.raises(hf_ideas.PipelineError, match="empty"):
        hf_ideas.parse_extraction_json("", source_name="empty.md")
    with pytest.raises(hf_ideas.PipelineError, match="no structured extraction JSON"):
        hf_ideas.parse_extraction_json(
            "**Bull case**\nThis legacy answer must not become a blank summary."
        )
    with pytest.raises(hf_ideas.PipelineError, match="malformed fenced JSON"):
        hf_ideas.parse_extraction_json("```json\n{not valid}\n```")

    folder, _ = make_duplicate_report(tmp_path)
    with pytest.raises(hf_ideas.PipelineError, match="reports success.*missing"):
        hf_ideas.build_report(folder)


def test_soft_validation_warnings_do_not_abort_and_year_month_is_accepted(
    tmp_path: Path,
) -> None:
    folder, data = make_duplicate_report(tmp_path)
    long_quote = "Named evidence 1. " + ("supporting detail " * 31)
    write_source_document(
        folder,
        load_manifest(folder),
        contexts={
            "example-co--ex-us--named-fund-1": [long_quote],
            "example-co--ex-us--named-fund-2": ["Named evidence 2."],
        },
    )
    data["company_summary"] = "First line.\nSecond line."
    data["fund_views"][0]["commentary_date"] = "2026-06"
    data["fund_views"][0]["core_thesis"] = "Only one sentence."
    data["fund_views"][0]["supporting_quote"] = long_quote
    data["fund_views"][1]["commentary_date"] = "2026/06"
    write_extraction(folder, data)

    coverage = hf_ideas.build_report(folder)

    warnings = coverage["warnings"]
    assert coverage["roster_validated"] == 2
    assert any("company_summary contains newlines" in warning for warning in warnings)
    assert any("should contain 2-4 sentences" in warning for warning in warnings)
    assert any("over 500 characters" in warning for warning in warnings)
    assert any("unexpected commentary_date format '2026/06'" in warning for warning in warnings)
    assert not any("'2026-06'" in warning for warning in warnings)
    persisted = json.loads((folder / "coverage.json").read_text(encoding="utf-8"))
    assert persisted["warnings"] == warnings


def test_merged_ticker_exchange_is_normalized_with_a_warning(tmp_path: Path) -> None:
    """Models often emit the roster display form 'EX US' and leave exchange blank."""
    folder, data = make_duplicate_report(tmp_path)
    data["ticker"] = "EX US"
    data["exchange"] = ""
    write_extraction(folder, data)

    coverage = hf_ideas.build_report(folder)

    assert coverage["roster_validated"] == 2
    assert any("normalized merged ticker 'EX US'" in w for w in coverage["warnings"])


def test_wrong_ticker_is_still_a_hard_error(tmp_path: Path) -> None:
    """Normalization must not become a blanket ticker-mismatch bypass."""
    folder, data = make_duplicate_report(tmp_path)
    data["ticker"] = "WRONG"
    data["exchange"] = ""
    write_extraction(folder, data)

    with pytest.raises(hf_ideas.PipelineError, match="ticker must be"):
        hf_ideas.build_report(folder)


def test_merged_ticker_not_repointed_when_exchange_already_set(tmp_path: Path) -> None:
    folder, data = make_duplicate_report(tmp_path)
    data["ticker"] = "EX US"
    data["exchange"] = "US"
    write_extraction(folder, data)

    with pytest.raises(hf_ideas.PipelineError, match="ticker must be"):
        hf_ideas.build_report(folder)


def test_fabricated_source_url_remains_a_hard_error(tmp_path: Path) -> None:
    """A URL this run never archived must never be accepted."""
    folder, data = make_duplicate_report(tmp_path)
    data["fund_views"][0]["source_url"] = "https://evil.example.com/fabricated"
    write_extraction(folder, data)

    with pytest.raises(hf_ideas.PipelineError, match="not an archived supporting source"):
        hf_ideas.build_report(folder)


def test_split_symbol_handles_real_roster_shapes() -> None:
    """Shapes observed across all 9 roster issues in the live feed (401 rows)."""
    assert hf_ideas.split_symbol("AAPL US") == ("AAPL", "US")
    assert hf_ideas.split_symbol("6146 JP") == ("6146", "JP")
    assert hf_ideas.split_symbol("") == ("", "")
    # punctuation inside tickers is legitimate and must survive
    assert hf_ideas.split_symbol("BA/ LN") == ("BA/", "LN")
    assert hf_ideas.split_symbol("UHAL/B US") == ("UHAL/B", "US")
    assert hf_ideas.split_symbol("WALMEX* MM") == ("WALMEX*", "MM")
    # publisher uncertainty markers must not leak into exchange
    assert hf_ideas.split_symbol("INOXCVA IN? N/A") == ("INOXCVA", "")
    assert hf_ideas.split_symbol("DATAPATTNS IN? N/A") == ("DATAPATTNS", "")
    # single token: no exchange claimed
    assert hf_ideas.split_symbol("NURS.V") == ("NURS.V", "")


def test_unknown_exchange_does_not_leak_into_company_id() -> None:
    rows = hf_ideas.parse_pitches("\U0001f539 Inox India (INOXCVA IN? N/A) by Some Fund\n")
    assert len(rows) == 1
    assert rows[0]["exchange"] == ""
    assert rows[0]["symbol_as_published"] == "INOXCVA IN? N/A"
    assert rows[0]["company_id"] == "inox-india--inoxcva-no-exchange"


def test_supporting_quote_mismatch_remains_a_hard_error(tmp_path: Path) -> None:
    folder, data = make_duplicate_report(tmp_path)
    data["fund_views"][0]["supporting_quote"] = "Invented source quote."
    write_extraction(folder, data)

    with pytest.raises(hf_ideas.PipelineError, match="not an exact excerpt"):
        hf_ideas.build_report(folder)


def test_real_quote_from_another_fund_is_a_hard_error(tmp_path: Path) -> None:
    """A verbatim quote is only valid inside the quoting fund's own evidence."""
    folder, data = make_duplicate_report(tmp_path)
    # Fund A cites text that exists in the document, but belongs to Fund B.
    data["fund_views"][0]["supporting_quote"] = "Named Fund B June 2026 Named evidence 2."
    write_extraction(folder, data)

    with pytest.raises(hf_ideas.PipelineError, match="not an exact excerpt"):
        hf_ideas.build_report(folder)


def test_build_command_reports_warnings_and_marks_hard_failures(
    tmp_path: Path,
) -> None:
    folder, data = make_duplicate_report(tmp_path)
    data["company_summary"] = "First line.\nSecond line."
    data["fund_views"][0]["commentary_date"] = "2026/06"
    output = write_extraction(folder, data)
    settings = HarnessSettings(workspace_root=tmp_path)

    success = ideas.build_command(path=folder, settings=settings)

    assert success.exit_code == 0
    assert b"2 warnings" in success.stdout
    assert b"warning:" in success.stdout

    data["fund_views"][0]["supporting_quote"] = "Invented source quote."
    output.write_text(json.dumps(data), encoding="utf-8")
    failure = ideas.build_command(path=folder, settings=settings)

    assert failure.exit_code == 1
    marker = folder / "PIPELINE_FAILED.md"
    assert marker.is_file()
    assert "not an exact excerpt" in marker.read_text(encoding="utf-8")


def test_fetch_latest_issue_dry_run_only_fetches_feed(tmp_path: Path) -> None:
    html_body = ISSUE_TEXT.replace("&", "&amp;").replace("→", "-&gt;")
    feed = (
        "<rss><channel><item><title><![CDATA[Test issue]]></title>"
        "<link>https://example.test/issue</link>"
        "<pubDate>Mon, 21 Sep 2026 12:00:00 +0000</pubDate>"
        f"<content:encoded><![CDATA[<p>{html_body}</p>]]></content:encoded>"
        "</item></channel></rss>"
    )
    calls: list[str] = []

    def getter(url: str) -> str:
        calls.append(url)
        return feed

    result = hf_ideas.fetch_latest_issue(
        tmp_path, dry_run=True, getter=getter, sleep_seconds=0
    )

    assert calls == [hf_ideas.FEED_URL]
    assert result.output_dir == tmp_path / "2026-09-21"
    assert len(result.pitches) == 4
    assert not result.output_dir.exists()


def test_weekly_uses_registered_in_process_extract_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "reports" / "05-weekly-ideas" / "2026-09-21"
    folder.mkdir(parents=True)
    (folder / "extraction-files.txt").write_text(
        "content/example.md\n", encoding="utf-8"
    )
    fetched = hf_ideas.FetchResult(
        output_dir=folder,
        issue_title="Test issue",
        issue_date="2026-09-21",
        pitches=[],
        groups=[],
        analysis_count=0,
        manifest={"public_sources": {}},
    )
    seen: list[str] = []

    monkeypatch.setattr(ideas, "fetch_latest_issue", lambda *args, **kwargs: fetched)
    monkeypatch.setattr(
        ideas,
        "build_report",
        lambda path: {
            "roster_validated": 0,
            "roster_expected": 0,
            "companies_validated": 0,
            "companies_expected": 0,
            "gap_count": 0,
            "warnings": [],
        },
    )

    def fake_dispatch(
        argv: list[str], settings: HarnessSettings | None = None, stdin: bytes = b""
    ) -> CommandResult:
        del settings, stdin
        seen.extend(argv)
        prompt_path = Path(argv[argv.index("--questions-file") + 1])
        assert prompt_path.is_file()
        assert "Weekly featured-fund extraction" in prompt_path.read_text(encoding="utf-8")
        return CommandResult.from_text("wrote extractions")

    monkeypatch.setattr("harness.cli.dispatch_command", fake_dispatch)
    result = ideas.weekly_command(
        dry_run=False,
        sleep_seconds=0,
        out=str(tmp_path / "reports" / "05-weekly-ideas"),
        settings=HarnessSettings(workspace_root=tmp_path),
    )

    assert result.exit_code == 0
    assert seen[0] == "extract-files"
    assert "--force" in seen
    assert str(folder / "extraction-files.txt") in seen


def test_ideas_cli_registration_help_and_dispatch(tmp_path: Path) -> None:
    root_help = runner.invoke(app, ["--help"])
    group_help = runner.invoke(app, ["ideas", "--help"])
    weekly_help = runner.invoke(app, ["ideas", "weekly", "--dry-run", "--help"])

    assert root_help.exit_code == 0
    assert "ideas" in root_help.stdout
    assert group_help.exit_code == 0
    assert "weekly" in group_help.stdout and "fetch" in group_help.stdout
    assert weekly_help.exit_code == 0
    assert "--sleep" in weekly_help.stdout and "--out" in weekly_help.stdout

    dispatched = dispatch_command(
        ["ideas", "build"], settings=HarnessSettings(workspace_root=tmp_path)
    )
    assert dispatched.exit_code == 1
    assert b"requires exactly one" in dispatched.stderr
