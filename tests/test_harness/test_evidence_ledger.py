"""Tests for the V2 evidence ledger."""

from pathlib import Path

from harness.workflows.evidence.ledger import (
    load_ledger,
    make_evidence_id,
    upsert_evidence,
)
from harness.workflows.evidence.paths import resolve_company_root


def test_make_evidence_id_is_deterministic_12_char_hex() -> None:
    a = make_evidence_id(ticker="HOOD", category="sec-annual", title="HOOD 10-K FY2025", local_path="data/sources/10-K/2025-02-18", url="https://sec.gov/x")
    b = make_evidence_id(ticker="HOOD", category="sec-annual", title="HOOD 10-K FY2025", local_path="data/sources/10-K/2025-02-18", url="https://sec.gov/x")
    c = make_evidence_id(ticker="HOOD", category="sec-annual", title="HOOD 10-K FY2024", local_path="data/sources/10-K/2024-02-18", url="https://sec.gov/y")

    assert a == b
    assert len(a) == 12
    assert all(ch in "0123456789abcdef" for ch in a)
    assert a != c


def test_load_ledger_returns_empty_list_when_missing(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    assert load_ledger(paths) == []


import json


def test_upsert_evidence_creates_then_updates(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)

    created = upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url="https://sec.gov/x",
        date="2025-02-18",
        notes="9 sections",
        collector="sec",
    )

    assert created["id"] == make_evidence_id(
        ticker="HOOD",
        category="sec-annual",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url="https://sec.gov/x",
    )
    assert created["version"] == 2
    assert created["status"] == "downloaded"
    assert created["created_at"] == created["updated_at"]

    updated = upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url="https://sec.gov/x",
        date="2025-02-18",
        notes="updated",
        collector="sec",
    )

    ledger = load_ledger(paths)
    assert len(ledger) == 1
    assert ledger[0]["notes"] == "updated"
    assert updated["updated_at"] >= created["updated_at"]


def test_upsert_evidence_rejects_unknown_status(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        upsert_evidence(
            paths,
            ticker="HOOD",
            category="sec-annual",
            status="weird",
            title="x",
            local_path=None,
            url=None,
            date=None,
            notes=None,
            collector=None,
        )
    except ValueError as exc:
        assert "status" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_upsert_evidence_writes_jsonl_and_markdown(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)

    upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url=None,
        date="2025-02-18",
        notes=None,
        collector="sec",
    )

    jsonl_lines = [json.loads(line) for line in paths.evidence_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(jsonl_lines) == 1
    md_text = paths.evidence_md.read_text(encoding="utf-8")
    assert "HOOD 10-K FY2025" in md_text
    assert "sec-annual" in md_text
