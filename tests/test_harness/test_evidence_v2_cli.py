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


def test_migrate_cli_command(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    # Seed a minimal source-registry.json under data/meta/.
    registry_path = root / "data" / "meta" / "source-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({
            "root": str(root),
            "ticker": "HOOD",
            "company_name": "Robinhood",
            "slug": "robinhood",
            "sources": [
                {
                    "id": "aaa",
                    "title": "HOOD 10-K 2025-02-18",
                    "ticker": "HOOD",
                    "bucket": "sec-filings-annual",
                    "source_kind": "sec-10k",
                    "status": "downloaded",
                    "local_path": "data/sources/10-K/2025-02-18.md",
                    "url": None,
                    "notes": None,
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "updated_at": "2025-01-01T00:00:00+00:00",
                },
            ],
            "last_updated": "2025-01-01T00:00:00+00:00",
        }),
        encoding="utf-8",
    )

    # Create the monolithic file so upsert_evidence doesn't reject it.
    md_path = root / "data" / "sources" / "10-K" / "2025-02-18.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("# 10-K content", encoding="utf-8")

    result = dispatch_command(["evidence", "migrate", "--root", str(root)])
    assert result.exit_code == 0, result.stderr.decode("utf-8")

    # evidence.jsonl must exist with the migrated entry.
    assert (root / "data" / "evidence.jsonl").exists()

    # source-registry.json must be archived.
    assert not registry_path.exists()
    assert (registry_path.parent / "source-registry.archive.json").exists()


def test_v2_full_flow_smoke(tmp_path: Path, monkeypatch) -> None:
    """End-to-end smoke test: init → collect sec → audit → status.

    Uses monkeypatches to avoid real network calls and real LLM calls.
    Asserts that the readiness stage transitions correctly across the workflow.
    """
    from harness.commands import analysis as analysis_cmd
    from harness.workflows.evidence.paths import resolve_company_root

    root = tmp_path / "reports" / "00-companies" / "42-acme"

    # --- Step 1: init ---
    init_result = evidence.init_command(
        root=str(root),
        ticker="ACME",
        company_name="Acme Corp",
        slug="acme",
    )
    assert init_result.exit_code == 0, init_result.stderr.decode("utf-8")

    paths = resolve_company_root(root)
    # evidence.jsonl is created lazily on first upsert; audits/ and plans/ are created by init
    assert paths.audits_dir.exists()
    assert paths.plans_dir.exists()

    # --- Step 2: collect sec (monkeypatched to simulate per-section files) ---

    def _fake_bulk_download(
        *,
        ticker: str,
        base_output: Path,
        annual: int,
        quarters: int,
        earnings: int,
        include_financials: bool,
        include_html: bool,
        nest_ticker: bool,
    ) -> None:
        """Simulate edgartools writing per-section 10-K files."""
        # Create a 10-K per-section directory
        filing_dir = base_output / "10-K" / "2025-02-18"
        filing_dir.mkdir(parents=True, exist_ok=True)
        (filing_dir / "01-business.md").write_text("## Business\nAcme sells widgets.", encoding="utf-8")
        (filing_dir / "07-mdna.md").write_text("## MD&A\nRevenue up 12%.", encoding="utf-8")
        # Create an earnings release
        earnings_dir = base_output / "earnings"
        earnings_dir.mkdir(parents=True, exist_ok=True)
        (earnings_dir / "2025-02-18.md").write_text("## Earnings\nQ4 beat by 3%.", encoding="utf-8")

    monkeypatch.setattr(
        "harness.workflows.evidence.collector.sec._bulk_download_one",
        _fake_bulk_download,
    )

    # Also monkeypatch _configure_edgar to avoid needing env vars
    monkeypatch.setattr(
        "harness.workflows.evidence.collector.sec._configure_edgar",
        lambda settings: None,
    )

    collect_result = dispatch_command(
        [
            "evidence", "collect", "sec",
            "--root", str(root),
            "--ticker", "ACME",
            "--annual", "1",
            "--quarters", "0",
            "--earnings", "1",
        ]
    )
    assert collect_result.exit_code == 0, collect_result.stderr.decode("utf-8")

    # Ledger should now have entries for 10-K and earnings
    ledger_lines = [
        json.loads(line)
        for line in paths.evidence_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(ledger_lines) >= 2
    categories = {e["category"] for e in ledger_lines}
    assert "sec-annual" in categories
    assert "sec-earnings" in categories

    # Status should be "collecting" before audit
    status_result_pre = dispatch_command(["analysis", "status", "--root", str(root)])
    assert status_result_pre.exit_code == 0, status_result_pre.stderr.decode("utf-8")
    pre_status = json.loads(paths.status_json.read_text(encoding="utf-8"))
    assert pre_status["stage"] == "collecting"

    # --- Step 3: audit (monkeypatched LLM) ---

    def _fake_llm(*, prompt: str, model: str) -> str:
        return "## Evidence Assessment\n\nReadiness: ready\n\nAll key SEC filings present."

    monkeypatch.setattr(
        "harness.commands.evidence.default_audit_llm",
        lambda **kwargs: _fake_llm,
    )

    audit_result = dispatch_command(["evidence", "audit", "--root", str(root)])
    assert audit_result.exit_code == 0, audit_result.stderr.decode("utf-8")
    memo_files = list(paths.audits_dir.glob("audit-*.md"))
    assert len(memo_files) == 1
    memo_text = memo_files[0].read_text(encoding="utf-8")
    assert "Evidence Assessment" in memo_text
    assert "Readiness: ready" in memo_text

    # --- Step 4: status after audit → should advance past "collecting" ---
    status_result_post = dispatch_command(["analysis", "status", "--root", str(root)])
    assert status_result_post.exit_code == 0, status_result_post.stderr.decode("utf-8")
    post_status = json.loads(paths.status_json.read_text(encoding="utf-8"))
    assert post_status["stage"] != "collecting", (
        f"Expected stage to advance past 'collecting' after audit; got {post_status['stage']!r}"
    )
    # Milestones should show ledger and audit as done
    milestone_map = {m["name"]: m["status"] for m in post_status["milestones"]}
    assert milestone_map.get("ledger") == "done"
    assert milestone_map.get("audit") == "done"


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
