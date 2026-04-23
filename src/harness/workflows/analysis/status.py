"""Deterministic workflow status for deep-dive analysis."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from harness.workflows.evidence.ledger import load_ledger, utc_now
from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.render import render_analysis_status_markdown, write_json

FOLDER_INDEX_STEMS: frozenset[str] = frozenset({"index", "readme"})


def run_status(paths: CompanyPaths) -> dict[str, Any]:
    """Compute and persist the current analysis workflow status."""
    ledger = load_ledger(paths)
    inventory = _load_json(paths.inventory_json)
    context_manifest = _load_json(paths.context_manifest_json)

    notes = _list_stage_artifacts(paths.notes_dir, suffixes={".md"})
    provenance = _list_stage_artifacts(paths.provenance_dir)
    bundles = _list_stage_artifacts(paths.bundles_dir, suffixes={".md"})
    extracted_count = inventory.get("counts", {}).get("extracted_files", 0) if inventory else 0
    audit_ready = _audit_says_ready(paths)
    source_count = len(ledger)

    if provenance:
        stage = "complete"
    elif notes:
        stage = "memo-in-progress"
    elif bundles or context_manifest:
        stage = "analysis-in-progress"
    elif audit_ready and extracted_count > 0:
        stage = "analysis-ready"
    elif audit_ready:
        stage = "extracting"
    elif source_count > 0:
        stage = "collecting"
    else:
        stage = "initialized"

    payload = {
        "stage": stage,
        "next_step": _next_step(paths, ledger=ledger, inventory=inventory, audit_ready=audit_ready, extracted_count=extracted_count, bundles=bundles),
        "milestones": [
            {"name": "ledger", "status": "done" if paths.evidence_jsonl.exists() else "missing", "detail": str(paths.evidence_jsonl.relative_to(paths.root))},
            {"name": "inventory", "status": "done" if paths.inventory_json.exists() else "missing", "detail": str(paths.inventory_json.relative_to(paths.root))},
            {"name": "audit", "status": "done" if audit_ready else "missing", "detail": "audit memo with Readiness: ready" if audit_ready else "run: minerva evidence audit"},
            {"name": "structured-extraction", "status": "done" if extracted_count > 0 else "missing", "detail": f"extracted_files={extracted_count}"},
            {"name": "analysis-context", "status": "done" if bundles else "missing", "detail": f"bundle_count={len(bundles)}"},
            {"name": "notes", "status": "done" if notes else "missing", "detail": f"note_count={len(notes)}"},
            {"name": "provenance", "status": "done" if provenance else "missing", "detail": f"record_count={len(provenance)}"},
        ],
        "last_updated": utc_now(),
    }
    write_json(paths.status_json, payload)
    paths.status_md.write_text(render_analysis_status_markdown(payload) + "\n", encoding="utf-8")
    return payload


def _audit_says_ready(paths: CompanyPaths) -> bool:
    """Return True if any audit-*.md in audits_dir contains 'Readiness: ready'."""
    if not paths.audits_dir.exists():
        return False
    pattern = re.compile(r"readiness\s*:\s*ready", re.IGNORECASE)
    for audit_file in paths.audits_dir.glob("audit-*.md"):
        text = audit_file.read_text(encoding="utf-8")
        if pattern.search(text):
            return True
    return False


def _next_step(
    paths: CompanyPaths,
    *,
    ledger: list[dict[str, Any]],
    inventory: dict[str, Any] | None,
    audit_ready: bool,
    extracted_count: int,
    bundles: list[Path],
) -> str:
    ticker = (ledger[0].get("ticker") if ledger else None) or paths.root.name.upper()
    if not ledger:
        return f"minerva evidence add-source --root {paths.root} --ticker {ticker} --category sec-annual --title \"Add source\""
    if not audit_ready:
        return f"minerva evidence audit --root {paths.root}"
    if not inventory:
        return f"minerva evidence inventory --root {paths.root}"
    if extracted_count == 0:
        return f"minerva evidence extract --root {paths.root} --profile default"
    if not bundles:
        return f"minerva analysis context --root {paths.root} --profile default"
    return f"minerva extract \"What matters most and why?\" --file {paths.bundles_dir / 'business-overview.md'}"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _list_stage_artifacts(directory: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    """List stage-driving files, excluding generated folder indexes and hidden files."""
    if not directory.exists():
        return []

    artifacts: list[Path] = []
    for item in sorted(directory.iterdir(), key=lambda candidate: candidate.name.lower()):
        if not item.is_file() or item.name.startswith(".") or _is_folder_index_artifact(item):
            continue
        if suffixes is not None and item.suffix.lower() not in suffixes:
            continue
        artifacts.append(item)
    return artifacts


def _is_folder_index_artifact(path: Path) -> bool:
    """Return True for common generated folder index files like INDEX.md."""
    return path.stem.lower() in FOLDER_INDEX_STEMS
