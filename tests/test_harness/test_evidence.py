"""Tests for evidence and analysis workflow commands."""

import json
from pathlib import Path

import pandas as pd

from harness.cli import dispatch_command
from harness.commands import analysis, evidence, sec as sec_commands
from harness.config import HarnessSettings
from harness.workflows.analysis.status import run_status
from harness.workflows.evidence.extraction import structured_output_base
from harness.workflows.evidence.paths import resolve_company_root


def test_evidence_init_creates_tree_and_registry(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"

    result = evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    assert result.exit_code == 0
    assert (root / "data" / "meta" / "source-registry.json").exists()
    assert (root / "data" / "sources").exists()
    assert (root / "data" / "references").exists()
    assert (root / "data" / "structured").exists()
    assert (root / "analysis" / "bundles").exists()
    assert (root / "INDEX.md").exists()


def test_evidence_collect_sec_registers_downloaded_sources_and_inventory(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="Minerva Research minerva@example.com")

    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    def fake_bulk_download_one(
        *,
        ticker: str,
        base_output: Path,
        annual: int,
        quarters: int,
        earnings: int,
        include_financials: bool,
        include_html: bool = True,
        nest_ticker: bool = True,
    ) -> list[str]:
        assert include_html is True
        company_root = base_output / ticker.upper() if nest_ticker else base_output
        for relative_path, body in {
            "10-K/2025-12-31.md": "# Annual filing",
            "10-K/2025-12-31.html": "<html><body>Annual filing</body></html>",
            "10-Q/2025-09-30.md": "# Quarterly filing",
            "10-Q/2025-09-30.html": "<html><body>Quarterly filing</body></html>",
            "earnings/2025-11-05.md": "# Earnings filing",
            "earnings/2025-11-05.html": "<html><body>Earnings filing</body></html>",
            "financials/income.md": "# Income",
            "financials/income.csv": "concept,label,FY 2025\nRevenue,Revenue,100\n",
            "financials/balance.md": "# Balance",
            "financials/balance.csv": "concept,label,FY 2025\nCash,Cash,50\n",
            "financials/cash.md": "# Cash",
            "financials/cash.csv": "concept,label,FY 2025\nOperatingCashFlow,Operating Cash Flow,25\n",
        }.items():
            target = company_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        return ["ok"]

    monkeypatch.setattr("harness.commands.sec._bulk_download_one", fake_bulk_download_one)

    result = evidence.collect_sec_command(
        root=str(root),
        ticker="HOOD",
        annual=1,
        quarters=1,
        earnings=1,
        include_financials=True,
        include_html=True,
        settings=settings,
    )

    assert result.exit_code == 0
    registry_payload = json.loads((root / "data" / "meta" / "source-registry.json").read_text(encoding="utf-8"))
    source_kinds = {entry["source_kind"] for entry in registry_payload["sources"]}
    inventory_text = (root / "data" / "meta" / "inventory.md").read_text(encoding="utf-8")
    assert "sec-10k" in source_kinds
    assert "sec-10k-html" in source_kinds
    assert "sec-8k-earnings-html" in source_kinds
    assert "sec-financials-income" in source_kinds
    assert "sec-financials-income-csv" in source_kinds
    assert "downloaded" in inventory_text
    assert (root / "data" / "sources" / "10-K" / "2025-12-31.md").exists()
    assert (root / "data" / "sources" / "10-K" / "2025-12-31.html").exists()
    csv_text = (root / "data" / "sources" / "financials" / "income.csv").read_text(encoding="utf-8")
    assert "concept,label,FY 2025" in csv_text
    assert not (root / "data" / "sources" / "HOOD").exists()


def test_bulk_download_one_saves_html_csv_and_exhibit_99_1_markdown(tmp_path: Path, monkeypatch) -> None:
    class FakeAttachment:
        def __init__(self, *, document_type: str, markdown_text: str) -> None:
            self.document_type = document_type
            self._markdown_text = markdown_text

        def markdown(self) -> str:
            return self._markdown_text

    class FakeFiling:
        def __init__(
            self,
            *,
            filing_date: str,
            markdown_text: str,
            html_text: str,
            exhibits: list[FakeAttachment] | None = None,
        ) -> None:
            self.filing_date = filing_date
            self._markdown_text = markdown_text
            self._html_text = html_text
            self.exhibits = exhibits or []

        def markdown(self) -> str:
            return self._markdown_text

        def save(self, target: Path) -> None:
            target.write_text(self._html_text, encoding="utf-8")

    filings_by_form = {
        "10-K": [
            FakeFiling(
                filing_date="2025-12-31",
                markdown_text="# 10-K wrapper",
                html_text="<html><body>10-K html</body></html>",
            )
        ],
        "10-Q": [
            FakeFiling(
                filing_date="2025-09-30",
                markdown_text="# 10-Q wrapper",
                html_text="<html><body>10-Q html</body></html>",
            )
        ],
        "8-K": [
            FakeFiling(
                filing_date="2025-11-05",
                markdown_text="# 8-K wrapper\nNo earnings details here.",
                html_text="<html><body>8-K html</body></html>",
                exhibits=[FakeAttachment(document_type="EX-99.1", markdown_text="# Press release\nRevenue grew 20%.")],
            ),
            FakeFiling(
                filing_date="2025-08-07",
                markdown_text="# 8-K wrapper\nFallback filing content.",
                html_text="<html><body>8-K fallback html</body></html>",
                exhibits=[],
            ),
        ],
    }

    monkeypatch.setattr(sec_commands, "Company", lambda ticker: object())
    monkeypatch.setattr(
        sec_commands,
        "_list_filings",
        lambda company, *, form, limit: filings_by_form[form][:limit],
    )
    monkeypatch.setattr(
        sec_commands,
        "_fetch_financials_frame",
        lambda ticker, *, periods, statement_type: pd.DataFrame(
            [
                {
                    "concept": f"{statement_type}_revenue",
                    "label": f"{statement_type.title()} Revenue",
                    "FY 2025": 100,
                    "FY 2024": 90,
                }
            ]
        ).set_index("concept"),
    )

    sec_commands._bulk_download_one(
        ticker="HOOD",
        base_output=tmp_path,
        annual=1,
        quarters=1,
        earnings=2,
        include_financials=True,
        include_html=True,
        nest_ticker=False,
    )

    # 10-K/10-Q are now per-section directories (fallback mode since FakeFiling has no obj()).
    assert (tmp_path / "10-K" / "2025-12-31").is_dir()
    assert (tmp_path / "10-K" / "2025-12-31" / "filing.md").read_text(encoding="utf-8") == "# 10-K wrapper"
    assert (tmp_path / "10-K" / "2025-12-31" / "_sections.md").exists()
    assert (tmp_path / "10-Q" / "2025-09-30").is_dir()
    assert (tmp_path / "10-Q" / "2025-09-30" / "filing.md").exists()
    # Earnings and financials remain unchanged (flat files).
    assert (tmp_path / "earnings" / "2025-11-05.md").read_text(encoding="utf-8") == "# Press release\nRevenue grew 20%."
    assert "Fallback filing content." in (tmp_path / "earnings" / "2025-08-07.md").read_text(encoding="utf-8")
    assert (tmp_path / "earnings" / "2025-11-05.html").read_text(encoding="utf-8") == "<html><body>8-K html</body></html>"
    csv_text = (tmp_path / "financials" / "income.csv").read_text(encoding="utf-8")
    assert "concept,label,FY 2025,FY 2024" in csv_text


def test_evidence_extract_coverage_status_and_context_round_trip(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    settings = HarnessSettings(
        workspace_root=tmp_path,
        edgar_identity="Minerva Research minerva@example.com",
        gemini_api_key="test-key",
    )

    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    def fake_bulk_download_one(
        *,
        ticker: str,
        base_output: Path,
        annual: int,
        quarters: int,
        earnings: int,
        include_financials: bool,
        include_html: bool = True,
        nest_ticker: bool = True,
    ) -> list[str]:
        company_root = base_output / ticker.upper() if nest_ticker else base_output
        filing_bodies: dict[str, str] = {
            "10-K/2025-12-31.md": "# Annual filing\nBusiness details 2025",
            "10-K/2024-12-31.md": "# Annual filing\nBusiness details 2024",
            "10-K/2023-12-31.md": "# Annual filing\nBusiness details 2023",
            "10-Q/2025-09-30.md": "# Quarterly filing\nRecent details Q3",
            "10-Q/2025-06-30.md": "# Quarterly filing\nRecent details Q2",
            "10-Q/2025-03-31.md": "# Quarterly filing\nRecent details Q1",
            "10-Q/2024-12-31.md": "# Quarterly filing\nRecent details Q4 prior year",
            "earnings/2025-11-05.md": "# Earnings filing\nGuidance details Q3",
            "earnings/2025-08-07.md": "# Earnings filing\nGuidance details Q2",
            "earnings/2025-05-08.md": "# Earnings filing\nGuidance details Q1",
            "earnings/2025-02-13.md": "# Earnings filing\nGuidance details Q4",
            "financials/income.md": "# Income",
            "financials/balance.md": "# Balance",
            "financials/cash.md": "# Cash",
        }
        for relative_path, body in filing_bodies.items():
            target = company_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        if include_html:
            for relative_path in [
                "10-K/2025-12-31.html",
                "10-K/2024-12-31.html",
                "10-K/2023-12-31.html",
                "10-Q/2025-09-30.html",
                "10-Q/2025-06-30.html",
                "10-Q/2025-03-31.html",
                "10-Q/2024-12-31.html",
                "earnings/2025-11-05.html",
                "earnings/2025-08-07.html",
                "earnings/2025-05-08.html",
                "earnings/2025-02-13.html",
            ]:
                target = company_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("<html><body>Human review</body></html>", encoding="utf-8")
        return ["ok"]

    monkeypatch.setattr("harness.commands.sec._bulk_download_one", fake_bulk_download_one)
    collect_result = evidence.collect_sec_command(
        root=str(root),
        ticker="HOOD",
        annual=3,
        quarters=4,
        earnings=4,
        include_financials=True,
        include_html=False,
        settings=settings,
    )
    assert collect_result.exit_code == 0

    external_file = root / "data" / "references" / "industry-report.md"
    external_file.parent.mkdir(parents=True, exist_ok=True)
    external_file.write_text("# External research\nCompetitive market", encoding="utf-8")
    register_result = evidence.register_command(
        root=str(root),
        status="downloaded",
        bucket="external-research",
        source_kind="external-research",
        title="Industry report",
        path=str(external_file),
        url="https://example.com/report",
        notes="Third-party industry report.",
    )
    assert register_result.exit_code == 0

    inventory_result = evidence.inventory_command(root=str(root), write_index=True)
    assert inventory_result.exit_code == 0

    monkeypatch.setattr(
        "harness.commands.extract._generate_answer",
        lambda **kwargs: "\n\n".join(
            [
                "## business-overview\nOverview answer",
                "## financial-highlights\nFinancial highlights answer",
                "## growth-drivers\nGrowth drivers answer",
                "## competition\nCompetition answer",
                "## management\nManagement answer",
                "## risks\nRisk answer",
                "## recent-update\nQuarter answer",
                "## financial-update\nQuarter financials answer",
                "## earnings-takeaways\nEarnings answer",
                "## kpi-summary\nKPI answer",
                "## guidance\nGuidance answer",
                "## income-statement\nIncome answer",
                "## balance-sheet\nBalance answer",
                "## cash-flow\nCash answer",
                "## external-evidence\nExternal answer",
            ]
        ),
    )

    coverage_result = evidence.coverage_command(root=str(root), profile="test-minimal")
    status_before_extract = analysis.status_command(root=str(root))
    extract_result = evidence.extract_command(
        root=str(root),
        profile="default",
        source_prefix=None,
        match=None,
        force=False,
        model="fake-model",
        settings=settings,
    )
    assert coverage_result.exit_code == 0
    assert status_before_extract.exit_code == 0
    assert extract_result.exit_code == 0
    assert "ready_for_analysis: True" in coverage_result.stdout.decode("utf-8")
    assert "stage: extracting" in status_before_extract.stdout.decode("utf-8")

    status_result = analysis.status_command(root=str(root))
    assert status_result.exit_code == 0
    assert "stage: analysis-ready" in status_result.stdout.decode("utf-8")

    context_result = analysis.context_command(root=str(root), profile="default")
    assert context_result.exit_code == 0
    bundle_text = (root / "analysis" / "bundles" / "competition.md").read_text(encoding="utf-8")
    assert "Competition answer" in bundle_text

    status_after_context = analysis.status_command(root=str(root))
    assert "stage: analysis-in-progress" in status_after_context.stdout.decode("utf-8")


def test_structured_output_base_does_not_match_legacy_01_data_prefix(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    target = structured_output_base(
        paths,
        {
            "id": "legacy-entry",
            "local_path": "01-data/sources/10-K/2025-12-31.md",
        },
    )

    assert target == paths.structured_dir / "registered" / "legacy-entry"


def test_analysis_status_ignores_generated_indexes_when_advancing_stages(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    paths.inventory_json.write_text(json.dumps({"counts": {"extracted_files": 3}}), encoding="utf-8")
    paths.coverage_json.write_text(json.dumps({"ready_for_analysis": True, "bucket_results": []}), encoding="utf-8")

    ready_payload = run_status(paths)
    ready_milestones = {item["name"]: item for item in ready_payload["milestones"]}

    assert ready_payload["stage"] == "analysis-ready"
    assert ready_milestones["analysis-context"]["detail"] == "bundle_count=0"
    assert ready_milestones["notes"]["detail"] == "note_count=0"
    assert ready_milestones["provenance"]["detail"] == "record_count=0"

    (paths.bundles_dir / "competition.md").write_text("# Competition\n\nReal bundle.", encoding="utf-8")
    assert run_status(paths)["stage"] == "analysis-in-progress"

    (paths.notes_dir / "2026-04-09-robinhood-deep-dive-v1.md").write_text("# Deep Dive\n\nReal note.", encoding="utf-8")
    assert run_status(paths)["stage"] == "memo-in-progress"

    (paths.provenance_dir / "2026-04-09-robinhood-deep-dive-v1.json").write_text("{}", encoding="utf-8")
    assert run_status(paths)["stage"] == "complete"


def test_evidence_init_creates_v2_dirs(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    assert (root / "audits").exists()
    assert (root / "plans").exists()
    assert (root / "research").exists()


def test_company_paths_exposes_v2_paths(tmp_path: Path) -> None:
    from harness.workflows.evidence.paths import resolve_company_root

    paths = resolve_company_root(tmp_path / "reports" / "00-companies" / "12-robinhood")

    assert paths.evidence_jsonl == paths.data_dir / "evidence.jsonl"
    assert paths.evidence_md == paths.data_dir / "evidence.md"
    assert paths.audits_dir == paths.root / "audits"
    assert paths.plans_dir == paths.root / "plans"
    assert paths.ledger_md == paths.root / "LEDGER.md"


def test_run_dispatch_supports_evidence_and_analysis_workflow_commands(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    init_result = dispatch_command(
        [
            "evidence",
            "init",
            "--root",
            str(root),
            "--ticker",
            "HOOD",
            "--name",
            "Robinhood",
            "--slug",
            "robinhood",
        ]
    )
    status_result = dispatch_command(["analysis", "status", "--root", str(root)])

    assert init_result.exit_code == 0
    assert status_result.exit_code == 0
    assert "stage: initialized" in status_result.stdout.decode("utf-8")
