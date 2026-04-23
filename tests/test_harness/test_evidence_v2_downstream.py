"""Downstream integration tests for V2 ledger."""

from pathlib import Path

from harness.commands import analysis, evidence
from harness.workflows.evidence.ledger import upsert_evidence
from harness.workflows.evidence.paths import resolve_company_root
from harness.workflows.analysis.context import run_context


def test_analysis_context_v2_filters_by_category(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    filing_dir = paths.sources_dir / "10-K" / "2025-02-18"
    filing_dir.mkdir(parents=True, exist_ok=True)
    (filing_dir / "01-business.md").write_text("# biz", encoding="utf-8")

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(filing_dir.relative_to(paths.root)),
        url=None, date="2025-02-18", notes=None, collector="sec",
    )

    manifest = run_context(paths, profile_name="default")
    assert {bundle["name"] for bundle in manifest["bundles"]} >= {"business-overview", "competition", "management", "risks", "valuation"}


def test_analysis_status_v2_uses_audit_memo_for_readiness(tmp_path: Path) -> None:
    from harness.workflows.analysis.status import run_status

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    # Add some evidence
    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path="data/sources/10-K/2025-02-18",
        url=None, date="2025-02-18", notes=None, collector="sec",
    )
    (paths.sources_dir / "10-K" / "2025-02-18").mkdir(parents=True, exist_ok=True)

    status = run_status(paths)
    assert status["stage"] == "collecting"  # no audit yet
    assert "add-source" in status["next_step"] or "audit" in status["next_step"]
    # Milestones should reference ledger, not registry
    milestone_names = {m["name"] for m in status["milestones"]}
    assert "ledger" in milestone_names
    assert "audit" in milestone_names
    assert "registry" not in milestone_names
    assert "coverage" not in milestone_names

    # Write an audit memo
    paths.audits_dir.mkdir(parents=True, exist_ok=True)
    (paths.audits_dir / "audit-2026-04-22.md").write_text(
        "# Evidence Audit — HOOD\n\nReadiness: ready\n", encoding="utf-8"
    )
    status2 = run_status(paths)
    # With audit ready + sources, should advance past collecting
    assert status2["stage"] != "collecting"
