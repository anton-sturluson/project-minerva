"""CLI wiring tests for V2 evidence commands."""

import json
from pathlib import Path

from harness.cli import dispatch_command
from harness.commands import evidence


def test_add_source_writes_ledger_entry(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    ref = root / "data" / "references" / "market.md"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text("body", encoding="utf-8")

    result = dispatch_command(
        [
            "evidence", "add-source",
            "--root", str(root),
            "--title", "Market report",
            "--category", "industry-report",
            "--status", "downloaded",
            "--path", str(ref),
            "--url", "https://example.com/report",
            "--date", "2026-03-01",
            "--collector", "manual",
        ]
    )
    assert result.exit_code == 0, result.stderr.decode("utf-8")
    ledger = [json.loads(line) for line in (root / "data" / "evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(ledger) == 1
    assert ledger[0]["category"] == "industry-report"
    assert ledger[0]["status"] == "downloaded"


def test_add_source_rejects_downloaded_without_path(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    result = dispatch_command(
        [
            "evidence", "add-source",
            "--root", str(root),
            "--title", "X",
            "--category", "news",
            "--status", "downloaded",
        ]
    )
    assert result.exit_code == 1
    assert "requires --path" in result.stderr.decode("utf-8")


def test_add_source_warns_on_unknown_category(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    result = dispatch_command(
        [
            "evidence", "add-source",
            "--root", str(root),
            "--title", "X",
            "--category", "wierd-typo",
            "--status", "discovered",
            "--url", "https://example.com",
        ]
    )
    assert result.exit_code == 0
    assert "unrecognized category" in result.stderr.decode("utf-8").lower()


def test_audit_command_produces_memo(tmp_path: Path, monkeypatch) -> None:
    from harness.workflows.evidence.ledger import upsert_evidence
    from harness.workflows.evidence.paths import resolve_company_root

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    # Seed a downloaded SEC entry so the audit has something to work with.
    target = paths.sources_dir / "10-K" / "2025-02-18"
    target.mkdir(parents=True, exist_ok=True)
    (target / "01-business.md").write_text("Business content.", encoding="utf-8")
    upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K 2025",
        local_path=str(target.relative_to(paths.root)),
        url=None,
        date="2025-02-18",
        notes=None,
        collector="sec",
    )

    # Monkeypatch default_audit_llm to avoid real API calls.
    def fake_llm(*, prompt: str, model: str) -> str:
        return "## Evidence Assessment\n\nAll looks good."

    monkeypatch.setattr("harness.commands.evidence.default_audit_llm", lambda **kwargs: fake_llm)

    result = dispatch_command(
        [
            "evidence", "audit",
            "--root", str(root),
        ]
    )
    assert result.exit_code == 0, result.stderr.decode("utf-8")
    memo_files = list(paths.audits_dir.glob("audit-*.md"))
    assert len(memo_files) == 1
    assert "Evidence Assessment" in memo_files[0].read_text(encoding="utf-8")
