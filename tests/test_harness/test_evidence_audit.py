"""Tests for the V2 evidence audit."""

from pathlib import Path

from harness.commands import evidence
from harness.workflows.evidence.audit import run_audit
from harness.workflows.evidence.ledger import upsert_evidence
from harness.workflows.evidence.paths import resolve_company_root


def test_run_audit_writes_memo_using_injected_llm(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    filing_dir = paths.sources_dir / "10-K" / "2025-02-18"
    filing_dir.mkdir(parents=True, exist_ok=True)
    (filing_dir / "01-business.md").write_text("# Business\nBody", encoding="utf-8")
    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(filing_dir.relative_to(paths.root)),
        url=None, date="2025-02-18", notes="1 section", collector="sec",
    )

    external = paths.references_dir / "market-report.md"
    external.write_text("# Market report\nCompetitors", encoding="utf-8")
    upsert_evidence(
        paths, ticker="HOOD", category="industry-report", status="downloaded",
        title="Industry report", local_path=str(external.relative_to(paths.root)),
        url=None, date=None, notes=None, collector="manual",
    )

    captured: dict = {}

    def fake_llm(*, prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "Readiness: ready\n\n## Summary\nLooks fine.\n\n## Recommended Actions\n1. Continue."

    result = run_audit(
        paths,
        categories=None,
        model="fake-audit-model",
        llm=fake_llm,
    )

    assert captured["model"] == "fake-audit-model"
    assert "HOOD 10-K 2025" in captured["prompt"]
    assert "# Market report" in captured["prompt"]
    assert "# Business" not in captured["prompt"]  # SEC bodies excluded; only metadata
    memo_text = Path(result["memo_path"]).read_text(encoding="utf-8")
    assert "# Evidence Audit — HOOD" in memo_text
    assert "Readiness: ready" in memo_text


def test_run_audit_filters_by_categories(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="discovered",
        title="A", local_path=None, url="https://a", date=None, notes=None, collector="manual",
    )
    upsert_evidence(
        paths, ticker="HOOD", category="industry-report", status="discovered",
        title="B", local_path=None, url="https://b", date=None, notes=None, collector="manual",
    )

    captured: dict = {}
    def fake_llm(*, prompt, model):
        captured["prompt"] = prompt
        return "Readiness: ready\n## Summary\nok\n## Recommended Actions\n1. go"

    result = run_audit(paths, categories=["industry-report"], model="m", llm=fake_llm)

    assert "industry-report" in captured["prompt"]
    assert " A " not in captured["prompt"]
    assert "audit-" in Path(result["memo_path"]).name
    assert "industry-report" in Path(result["memo_path"]).name
