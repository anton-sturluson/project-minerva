"""Workspace-scoped filesystem commands."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from harness.config import HarnessSettings, get_settings
from harness.context import estimate_tokens, is_binary
from harness.output import CommandResult


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path filesystem commands."""
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "fs",
            "Usage: <cat|ls|write|stat|rm|grep> ...",
            ["ls", "cat <path>", "grep <pattern> [file]"],
        )

    command: str = args[0]
    if command == "cat":
        if len(args) != 2:
            return _usage_error("cat", "Usage: cat <path>", ["stat <path>", "ls"])
        return cat_file(args[1], settings=active_settings)
    if command == "ls":
        if len(args) > 2:
            return _usage_error("ls", "Usage: ls [dir]", ["stat <path>", "cat <file>"])
        return list_files(args[1] if len(args) == 2 else None, settings=active_settings)
    if command == "write":
        if len(args) < 3:
            return _usage_error("write", "Usage: write <path> <content>", ["cat <path>", "ls"])
        return write_file(args[1], " ".join(args[2:]), settings=active_settings)
    if command == "stat":
        if len(args) != 2:
            return _usage_error("stat", "Usage: stat <path>", ["ls", "cat <file>"])
        return stat_path(args[1], settings=active_settings)
    if command == "rm":
        if len(args) != 2:
            return _usage_error("rm", "Usage: rm <path>", ["ls", "stat <path>"])
        return remove_path(args[1], settings=active_settings)
    if command == "grep":
        if len(args) not in {2, 3}:
            return _usage_error(
                "grep",
                "Usage: grep <pattern> [file]",
                ["cat <file> | grep <pattern>", "grep <pattern> <file>"],
            )
        return grep_text(args[1], path=args[2] if len(args) == 3 else None, stdin=stdin, settings=active_settings)

    return _usage_error(
        "fs",
        f"Unknown filesystem command: {command}",
        ["cat <path>", "ls", "write <path> <content>", "grep <pattern> [file]"],
    )


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


def grep_text(
    pattern: str,
    *,
    path: str | None = None,
    stdin: bytes = b"",
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Filter matching lines from a workspace file or piped stdin."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        text: str = _read_grep_input(path, stdin=stdin, settings=active_settings)
    except Exception as exc:
        return _error_result(str(exc), start)

    matches: list[str] = [line for line in text.splitlines() if pattern in line]
    if not matches:
        return CommandResult.from_text(
            "",
            stderr=f"No matches for pattern: {pattern}",
            exit_code=1,
            duration_ms=_elapsed_ms(start),
        )
    return CommandResult.from_text("\n".join(matches), duration_ms=_elapsed_ms(start))


def _error_result(message: str, start: float) -> CommandResult:
    return CommandResult.from_text("", stderr=message, exit_code=1, duration_ms=_elapsed_ms(start))


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _read_grep_input(path: str | None, *, stdin: bytes, settings: HarnessSettings) -> str:
    if path:
        result: CommandResult = cat_file(path, settings=settings)
        if result.exit_code != 0:
            raise ValueError(result.stderr.decode("utf-8", errors="replace") or f"Failed to read {path}")
        return result.stdout.decode("utf-8", errors="replace")
    if stdin:
        return stdin.decode("utf-8", errors="replace")
    raise ValueError(
        "What went wrong: grep needs a file path or piped stdin.\n"
        "What to do instead: pass `grep <pattern> <file>` or pipe text into `grep <pattern>`.\n"
        "Available alternatives: `cat <file> | grep <pattern>`, `grep <pattern> <file>`"
    )


def _usage_error(command: str, usage: str, alternatives: list[str]) -> CommandResult:
    return CommandResult.from_text(
        "",
        stderr=(
            f"Invalid invocation for `{command}`.\n"
            f"What to do instead: {usage}\n"
            f"Available alternatives: {', '.join(alternatives)}"
        ),
        exit_code=1,
    )
