"""Tests for evidence and analysis workflow commands."""

import json
from pathlib import Path

import pandas as pd
import pytest

from harness.cli import dispatch_command
from harness.commands import evidence, sec as sec_commands
from harness.config import HarnessSettings
from harness.workflows.evidence.collector import collect_sec_sources
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





def test_evidence_collect_sec_v2_writes_ledger_and_per_section_files(tmp_path: Path, monkeypatch) -> None:
    import json as _json
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="x x@y.com")
    paths = resolve_company_root(root)

    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda s: None)

    def fake_bulk_download_one(*, ticker, base_output, annual, quarters, earnings, include_financials, include_html=True, nest_ticker=True):
        # Simulate per-section download result: a directory with section files.
        company_root = base_output / ticker.upper() if nest_ticker else base_output
        section_dir = company_root / "10-K" / "2025-02-18"
        section_dir.mkdir(parents=True, exist_ok=True)
        (section_dir / "01-business.md").write_text("## ITEM 1. BUSINESS\nBusiness.", encoding="utf-8")
        (section_dir / "02-risk-factors.md").write_text("## ITEM 1A. RISK FACTORS\nRisk.", encoding="utf-8")
        (section_dir / "_sections.md").write_text("# Sections\n- [ITEM 1. Business](./01-business.md)\n", encoding="utf-8")
        (company_root / "earnings" / "2025-11-05.md").parent.mkdir(parents=True, exist_ok=True)
        (company_root / "earnings" / "2025-11-05.md").write_text("# Earnings", encoding="utf-8")
        return ["ok"]

    monkeypatch.setattr("harness.commands.sec._bulk_download_one", fake_bulk_download_one)

    summary = collect_sec_sources(
        paths,
        ticker="HOOD",
        annual=1,
        quarters=0,
        earnings=1,
        include_financials=False,
        include_html=False,
        settings=settings,
    )

    assert summary["collected_count"] > 0

    ledger_path = root / "data" / "evidence.jsonl"
    lines = [_json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = {entry["category"] for entry in lines}
    assert categories == {"sec-annual", "sec-earnings"}
    annual = [e for e in lines if e["category"] == "sec-annual"]
    assert len(annual) == 1
    assert annual[0]["local_path"] == "data/sources/10-K/2025-02-18"
    assert (root / "data" / "sources" / "10-K" / "2025-02-18" / "01-business.md").exists()


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


def test_inventory_v2_reads_ledger(tmp_path: Path) -> None:
    from harness.workflows.evidence.ledger import upsert_evidence
    from harness.workflows.evidence.inventory import run_inventory
    from harness.workflows.evidence.paths import resolve_company_root

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    target = paths.sources_dir / "10-K" / "2025-02-18"
    target.mkdir(parents=True, exist_ok=True)
    (target / "01-business.md").write_text("x", encoding="utf-8")

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(target.relative_to(paths.root)),
        url=None, date="2025-02-18", notes=None, collector="sec",
    )
    upsert_evidence(
        paths, ticker="HOOD", category="industry-report", status="discovered",
        title="Market report", local_path=None, url="https://example.com", date=None, notes=None, collector="web_fetch",
    )
    upsert_evidence(
        paths, ticker="HOOD", category="news", status="blocked",
        title="Paywalled news", local_path=None, url="https://paywall.example.com", date=None, notes="paywall", collector="web_fetch",
    )

    inv = run_inventory(paths)
    assert inv["counts"]["downloaded"] == 1
    assert inv["counts"]["discovered"] == 1
    assert inv["counts"]["blocked"] == 1
    assert inv["counts"]["downloaded_missing_on_disk"] == 0


def test_extract_v2_uses_ledger_and_categories(tmp_path: Path, monkeypatch) -> None:
    from harness.workflows.evidence.ledger import upsert_evidence
    from harness.workflows.evidence.extraction import run_extraction
    from harness.workflows.evidence.paths import resolve_company_root

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="fake-key")

    filing_dir = paths.sources_dir / "10-K" / "2025-02-18"
    filing_dir.mkdir(parents=True, exist_ok=True)
    (filing_dir / "01-business.md").write_text("# Business\nProse", encoding="utf-8")
    (filing_dir / "02-risk-factors.md").write_text("# Risks", encoding="utf-8")

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(filing_dir.relative_to(paths.root)),
        url=None, date="2025-02-18", notes=None, collector="sec",
    )

    monkeypatch.setattr(
        "harness.commands.extract._generate_answer",
        lambda **kwargs: "## business-overview\nA\n## financial-highlights\nB\n## growth-drivers\nC\n## competition\nD\n## management\nE\n## risks\nF",
    )

    run = run_extraction(
        paths, profile_name="default", source_prefix=None, match=None, force=True, model="fake", settings=settings,
    )
    assert run["processed_count"] == 1


def test_structured_output_base_with_directory_backed_local_path(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    target = structured_output_base(
        paths,
        {
            "id": "abc123",
            "local_path": "data/sources/10-K/2025-02-18",
        },
    )

    # Directory-backed path: no suffix to strip, so output is structured/10-K/2025-02-18
    assert target == paths.structured_dir / "10-K" / "2025-02-18"


def test_run_dispatch_supports_evidence_workflow_commands(tmp_path: Path) -> None:
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

    assert init_result.exit_code == 0
