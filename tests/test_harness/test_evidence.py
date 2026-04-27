"""Tests for evidence workflow commands (V2 lean surface: init, add-source, audit)."""

from pathlib import Path

from harness.cli import dispatch_command
from harness.commands import evidence


def test_evidence_init_creates_tree_and_registry(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"

    result = evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    assert result.exit_code == 0
    assert (root / "data" / "meta" / "source-registry.json").exists()
    assert (root / "data" / "sources").exists()
    assert (root / "data" / "references").exists()
    assert (root / "INDEX.md").exists()


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
