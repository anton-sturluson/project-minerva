"""Rendering helpers for workflow metadata and directory indexes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from minerva.formatting import build_markdown_table


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist indented JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_source_registry_markdown(registry: dict[str, Any]) -> str:
    """Render the registry to a compact markdown summary."""
    rows: list[list[str]] = []
    for entry in registry.get("sources", []):
        rows.append(
            [
                entry["id"],
                entry["status"],
                entry["bucket"],
                entry["source_kind"],
                entry["title"],
                entry.get("local_path") or "",
                entry.get("url") or "",
            ]
        )
    table = build_markdown_table(
        ["id", "status", "bucket", "source_kind", "title", "local_path", "url"],
        rows or [["(none)", "", "", "", "", "", ""]],
        alignment=["l", "l", "l", "l", "l", "l", "l"],
    )
    return "\n".join(
        [
            "# Source Registry",
            "",
            f"- ticker: {registry.get('ticker') or '(unknown)'}",
            f"- company_name: {registry.get('company_name') or '(unknown)'}",
            f"- slug: {registry.get('slug') or '(unknown)'}",
            f"- source_count: {len(registry.get('sources', []))}",
            f"- last_updated: {registry.get('last_updated') or '(unknown)'}",
            "",
            "## Sources",
            "",
            table,
        ]
    )


def render_inventory_markdown(inventory: dict[str, Any]) -> str:
    """Render inventory counts and disk-health summary."""
    counts = inventory.get("counts", {})
    rows = [[key, str(value)] for key, value in sorted(counts.items())]
    missing_rows = [[path] for path in inventory.get("downloaded_missing_on_disk", [])]
    return "\n".join(
        [
            "# Evidence Inventory",
            "",
            f"- root: {inventory.get('root')}",
            f"- last_updated: {inventory.get('last_updated')}",
            "",
            "## Counts",
            "",
            build_markdown_table(["metric", "value"], rows or [["(none)", "0"]], alignment=["l", "r"]),
            "",
            "## Downloaded Missing On Disk",
            "",
            build_markdown_table(["path"], missing_rows or [["(none)"]], alignment=["l"]),
        ]
    )


def render_extraction_run_markdown(run: dict[str, Any]) -> str:
    """Render an extraction run manifest."""
    rows = [
        [
            item["source_id"],
            item["status"],
            item.get("structured_json") or "",
            item.get("structured_markdown") or "",
        ]
        for item in run.get("artifacts", [])
    ]
    return "\n".join(
        [
            "# Extraction Run",
            "",
            f"- profile: {run.get('profile')}",
            f"- model: {run.get('model')}",
            f"- processed: {run.get('processed_count', 0)}",
            f"- skipped_existing: {run.get('skipped_existing_count', 0)}",
            f"- total_matches: {run.get('matched_count', 0)}",
            f"- created_at: {run.get('created_at')}",
            "",
            build_markdown_table(
                ["source_id", "status", "structured_json", "structured_markdown"],
                rows or [["(none)", "skipped", "", ""]],
                alignment=["l", "l", "l", "l"],
            ),
        ]
    )


def render_evidence_ledger_markdown(entries: list[dict[str, Any]]) -> str:
    """Render the V2 ledger as a compact markdown summary."""
    rows: list[list[str]] = []
    for entry in sorted(entries, key=lambda item: (item.get("category") or "", item.get("date") or "", item["id"])):
        rows.append(
            [
                entry["id"],
                entry.get("status", ""),
                entry.get("category", ""),
                entry.get("title", ""),
                entry.get("date") or "",
                entry.get("local_path") or "",
                entry.get("url") or "",
            ]
        )
    table = build_markdown_table(
        ["id", "status", "category", "title", "date", "local_path", "url"],
        rows or [["(none)", "", "", "", "", "", ""]],
        alignment=["l", "l", "l", "l", "l", "l", "l"],
    )
    return "\n".join(
        [
            "# Evidence Ledger (V2)",
            "",
            f"- source_count: {len(entries)}",
            "",
            table,
        ]
    )


def refresh_indexes(root: Path) -> None:
    """Write a simple directory listing index for every non-hidden directory under root."""
    for directory in sorted(_iter_directories(root)):
        index_path = directory / "INDEX.md"
        lines: list[str] = [f"# Index: {directory.name}", ""]
        children = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        directories = [item for item in children if item.is_dir() and not item.name.startswith(".")]
        files = [item for item in children if item.is_file() and item.name != "INDEX.md" and not item.name.startswith(".")]
        lines.append("## Directories")
        lines.append("")
        if directories:
            lines.extend([f"- {item.name}/" for item in directories])
        else:
            lines.append("- (none)")
        lines.extend(["", "## Files", ""])
        if files:
            lines.extend([f"- {item.name}" for item in files])
        else:
            lines.append("- (none)")
        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _iter_directories(root: Path) -> list[Path]:
    directories: list[Path] = []
    if not root.exists():
        return directories
    for directory in root.rglob("*"):
        if directory.is_dir() and not any(part.startswith(".") for part in directory.relative_to(root).parts):
            directories.append(directory)
    directories.append(root)
    return directories
