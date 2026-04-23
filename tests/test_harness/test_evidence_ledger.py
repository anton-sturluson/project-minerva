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
