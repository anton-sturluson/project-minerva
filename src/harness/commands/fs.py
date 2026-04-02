"""Workspace-scoped filesystem commands."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from harness.config import HarnessSettings, get_settings
from harness.context import estimate_tokens, is_binary
from harness.output import CommandResult


def resolve_workspace_path(raw_path: str, settings: HarnessSettings | None = None) -> Path:
    """Resolve a path under the configured workspace root and reject escapes."""
    active_settings: HarnessSettings = settings or get_settings()
    workspace_root: Path = active_settings.ensure_workspace_root()
    candidate: Path = Path(raw_path)
    resolved: Path = (workspace_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()

    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(
            f"Path escapes the workspace root: {raw_path}\n"
            f"What to do instead: use a path inside {workspace_root}\n"
            "Available alternatives: `ls`, `stat <path>`, `write <path> <content>`"
        ) from exc

    return resolved


def cat_file(path: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Read a text file from the workspace."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()

    try:
        target: Path = resolve_workspace_path(path, active_settings)
    except ValueError as exc:
        return _error_result(str(exc), start)

    if not target.exists():
        return _error_result(
            f"File not found: {path}\n"
            "What to do instead: confirm the path with `ls` or `stat <path>`.\n"
            "Available alternatives: `ls`, `stat <path>`, `write <path> <content>`",
            start,
        )
    if target.is_dir():
        return _error_result(
            f"Cannot read a directory: {path}\n"
            "What to do instead: use `ls <dir>` to inspect directory contents.\n"
            "Available alternatives: `ls`, `stat <path>`",
            start,
        )

    data: bytes = target.read_bytes()
    if is_binary(data):
        return _error_result(
            f"Binary file detected: {path}\n"
            "What to do instead: use `stat <file>` to inspect file info or convert it to text first.\n"
            "Available alternatives: `stat <file>`, `ls`, `write <path> <content>`",
            start,
        )

    content_type: str = "csv" if target.suffix.lower() == ".csv" else "text"
    return CommandResult(
        stdout=data,
        exit_code=0,
        duration_ms=_elapsed_ms(start),
        content_type=content_type,
    )


def list_files(directory: str | None = None, settings: HarnessSettings | None = None) -> CommandResult:
    """List files from the workspace root or a subdirectory."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    raw_path: str = directory or "."
    try:
        target: Path = resolve_workspace_path(raw_path, active_settings)
    except ValueError as exc:
        return _error_result(str(exc), start)

    if not target.exists():
        return _error_result(
            f"Directory not found: {raw_path}\n"
            "What to do instead: run `ls` to inspect the workspace root first.\n"
            "Available alternatives: `ls`, `stat <path>`",
            start,
        )
    if not target.is_dir():
        return _error_result(
            f"Not a directory: {raw_path}\n"
            "What to do instead: use `stat <path>` for file details or `cat <file>` for text content.\n"
            "Available alternatives: `stat <path>`, `cat <file>`",
            start,
        )

    entries: list[str] = []
    for child in sorted(target.iterdir()):
        suffix: str = "/" if child.is_dir() else ""
        entries.append(f"{child.relative_to(active_settings.resolved_workspace_root)}{suffix}")
    if not entries:
        entries.append("(empty)")

    return CommandResult.from_text("\n".join(entries), duration_ms=_elapsed_ms(start))


def write_file(path: str, content: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Write UTF-8 text into a workspace-scoped file."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()

    try:
        target: Path = resolve_workspace_path(path, active_settings)
    except ValueError as exc:
        return _error_result(str(exc), start)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    relative_path: Path = target.relative_to(active_settings.resolved_workspace_root)
    return CommandResult.from_text(
        f"Wrote {len(content.encode('utf-8'))} bytes to {relative_path}",
        duration_ms=_elapsed_ms(start),
    )


def stat_path(path: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Show file type, size, token estimate, and large-file guidance."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target: Path = resolve_workspace_path(path, active_settings)
    except ValueError as exc:
        return _error_result(str(exc), start)

    if not target.exists():
        return _error_result(
            f"Path not found: {path}\n"
            "What to do instead: inspect the workspace with `ls` and retry with an existing path.\n"
            "Available alternatives: `ls`, `write <path> <content>`",
            start,
        )

    stat_result = target.stat()
    lines: list[str] = [
        f"path: {target.relative_to(active_settings.resolved_workspace_root)}",
        f"type: {'directory' if target.is_dir() else 'file'}",
        f"size_bytes: {stat_result.st_size}",
    ]

    if target.is_file():
        data: bytes = target.read_bytes()
        if is_binary(data):
            lines.append("content: binary")
            lines.append("recommendation: Use a text export before reading this file in the harness.")
        else:
            text: str = data.decode("utf-8", errors="replace")
            line_count: int = text.count("\n") + (1 if text else 0)
            lines.append("content: text")
            lines.append(f"line_count: {line_count}")
            lines.append(f"estimated_tokens: {estimate_tokens(text)}")
            if stat_result.st_size > 50 * 1024 or line_count > 200:
                lines.append("recommendation: Large file. Prefer targeted reads or filtering before sending to the LLM.")

    return CommandResult.from_text("\n".join(lines), duration_ms=_elapsed_ms(start))


def remove_path(path: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Remove a file or directory inside the workspace."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target: Path = resolve_workspace_path(path, active_settings)
    except ValueError as exc:
        return _error_result(str(exc), start)

    if not target.exists():
        return _error_result(
            f"Path not found: {path}\n"
            "What to do instead: use `ls` or `stat <path>` to confirm the target before removing it.\n"
            "Available alternatives: `ls`, `stat <path>`",
            start,
        )

    relative_path: Path = target.relative_to(active_settings.resolved_workspace_root)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    return CommandResult.from_text(f"Removed {relative_path}", duration_ms=_elapsed_ms(start))


def _error_result(message: str, start: float) -> CommandResult:
    return CommandResult.from_text("", stderr=message, exit_code=1, duration_ms=_elapsed_ms(start))


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))
