"""Tests for V1 → V2 migration."""

import json
from pathlib import Path

from harness.commands import evidence
from harness.workflows.evidence.migration import migrate_v1_to_v2
from harness.workflows.evidence.paths import resolve_company_root


def test_migrate_v1_to_v2_dedupes_and_drops_html(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    v1_payload = {
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
            {
                "id": "bbb",
                "title": "HOOD 10-K 2025-02-18 (HTML)",
                "ticker": "HOOD",
                "bucket": "sec-filings-annual",
                "source_kind": "sec-10k-html",
                "status": "downloaded",
                "local_path": "data/sources/10-K/2025-02-18.html",
                "url": None,
                "notes": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "ccc",
                "title": "Industry report",
                "ticker": "HOOD",
                "bucket": "external-research",
                "source_kind": "industry-report",
                "status": "discovered",
                "local_path": None,
                "url": "https://example.com/report",
                "notes": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
        ],
        "last_updated": "2025-01-01T00:00:00+00:00",
    }
    paths.source_registry_json.write_text(json.dumps(v1_payload), encoding="utf-8")

    # Create the monolithic file so the ledger path validates.
    md_path = paths.sources_dir / "10-K" / "2025-02-18.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("# 10-K content", encoding="utf-8")

    result = migrate_v1_to_v2(paths)

    assert result["migrated_count"] == 2  # 10-K markdown + industry report; HTML dropped
    entries = [json.loads(line) for line in paths.evidence_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = {entry["category"] for entry in entries}
    assert categories == {"sec-annual", "industry-report"}
    # 10-K points to the existing monolithic file (not re-split)
    annual = next(entry for entry in entries if entry["category"] == "sec-annual")
    assert annual["local_path"] == "data/sources/10-K/2025-02-18.md"
    # Old registry archived
    assert (paths.source_registry_json.with_suffix(".archive.json")).exists()
