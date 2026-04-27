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
