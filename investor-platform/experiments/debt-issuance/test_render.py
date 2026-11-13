"""Verify validation and safe JSON embedding at the standalone report boundary."""

import json
import re
from pathlib import Path
from typing import cast

import pytest
from jsonschema import ValidationError
from render import JsonValue, render


def snapshot(name: str) -> dict[str, JsonValue]:
    """Return a minimal valid synthetic snapshot with no external dependencies."""
    return {
        "schema_version": 1,
        "cutoff_date": "2026-10-20",
        "entities": [
            {"id": "EXM", "ticker": "EXM", "name": name, "cik": None, "category": "neocloud"}
        ],
        "fiscal_periods": [],
        "bond_events": [],
        "other_financings": [],
        "spgi_periods": [],
        "coverage": [],
        "sources": [],
    }


@pytest.mark.parametrize(
    "name",
    [
        "</script><script>window.injected=true</script>",
        '<img src="x" onerror="window.injected=true"> & partners',
        "Example\u2028Cloud\u2029Research",
    ],
)
def test_untrusted_text_remains_inert_json(tmp_path: Path, name: str) -> None:
    """Filing text cannot terminate its JSON script, and its exact value is retained."""
    source: Path = tmp_path / "snapshot.json"
    payload: dict[str, JsonValue] = snapshot(name)
    source.write_text(json.dumps(payload), encoding="utf-8")
    destination: Path = render(source)
    html: str = destination.read_text(encoding="utf-8")
    match: re.Match[str] | None = re.search(
        r'<script\s+id="snapshot"\s+type="application/json"\s*>(.*?)</script>', html, re.S
    )
    assert match is not None
    embedded: str = match.group(1)
    assert "<" not in embedded and "\u2028" not in embedded and "\u2029" not in embedded
    assert cast(dict[str, JsonValue], json.loads(embedded)) == payload
    assert destination == source.with_name("index.html")
    assert html.count("<script>") == 1


def test_invalid_snapshot_is_rejected_before_output(tmp_path: Path) -> None:
    """Missing contract fields cannot produce an apparently valid research report."""
    source: Path = tmp_path / "snapshot.json"
    payload: dict[str, JsonValue] = snapshot("Example Cloud")
    del payload["cutoff_date"]
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        render(source)
    assert not source.with_name("index.html").exists()
