"""V2 JSONL evidence ledger — one logical source per line."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.workflows.evidence.paths import CompanyPaths

LEDGER_VERSION = 2
EVIDENCE_STATUSES: frozenset[str] = frozenset({"downloaded", "discovered", "blocked"})


def make_evidence_id(
    *,
    ticker: str,
    category: str,
    title: str,
    local_path: str | None,
    url: str | None,
) -> str:
    """Deterministic 12-char hex: sha1(ticker|category|title|local_path|url)[:12]."""
    payload = "|".join([ticker.upper(), category, title, local_path or "", url or ""])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_ledger(paths: CompanyPaths) -> list[dict[str, Any]]:
    """Return the ledger as a list of dicts. Empty list when missing."""
    path = paths.evidence_jsonl
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        entries.append(json.loads(stripped))
    return entries


def upsert_evidence(
    paths: CompanyPaths,
    *,
    ticker: str,
    category: str,
    status: str,
    title: str,
    local_path: str | None,
    url: str | None,
    date: str | None,
    notes: str | None,
    collector: str | None,
) -> dict[str, Any]:
    """Insert-or-update an evidence record. Writes JSONL atomically + evidence.md."""
    if status not in EVIDENCE_STATUSES:
        raise ValueError(f"unsupported evidence status: {status}")
    if status == "downloaded" and not local_path:
        raise ValueError("status=downloaded requires local_path")

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    entries = load_ledger(paths)
    entry_id = make_evidence_id(
        ticker=ticker,
        category=category,
        title=title,
        local_path=local_path,
        url=url,
    )
    now = utc_now()
    existing = next((item for item in entries if item["id"] == entry_id), None)
    if existing is None:
        entry = {
            "id": entry_id,
            "version": LEDGER_VERSION,
            "title": title,
            "ticker": ticker.upper(),
            "category": category,
            "status": status,
            "local_path": local_path,
            "url": url,
            "date": date,
            "notes": notes,
            "collector": collector,
            "created_at": now,
            "updated_at": now,
        }
        entries.append(entry)
    else:
        existing.update(
            {
                "title": title,
                "ticker": ticker.upper(),
                "category": category,
                "status": status,
                "local_path": local_path,
                "url": url,
                "date": date,
                "notes": notes,
                "collector": collector,
                "updated_at": now,
            }
        )
        entry = existing

    _write_ledger_atomic(paths, entries)
    from harness.workflows.evidence.render import render_evidence_ledger_markdown

    paths.evidence_md.write_text(render_evidence_ledger_markdown(entries) + "\n", encoding="utf-8")
    return entry


def _write_ledger_atomic(paths: CompanyPaths, entries: list[dict[str, Any]]) -> None:
    paths.evidence_jsonl.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(
        json.dumps(entry, sort_keys=True, ensure_ascii=False) for entry in sorted(entries, key=lambda item: item["id"])
    )
    fd, tmp_name = tempfile.mkstemp(prefix="evidence-", suffix=".jsonl", dir=str(paths.evidence_jsonl.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            if serialized:
                handle.write("\n")
        os.replace(tmp_name, paths.evidence_jsonl)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
