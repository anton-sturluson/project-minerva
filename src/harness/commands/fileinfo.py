"""File metadata and routing guidance."""

from __future__ import annotations

import os
import time
from pathlib import Path

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, relative_display_path, resolve_path, show_help_if_bare
from harness.context import detect_file_format, estimate_tokens, is_binary
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

FILEINFO_HELP = (
    "Inspect files and directories to decide the right handling path.\n\n"
    "Examples:\n"
    "  minerva fileinfo ./aapl-filings/AAPL/10-K/2025-11-01.md\n"
    "  minerva fileinfo ./aapl-filings/AAPL/\n"
)

app = typer.Typer(help=FILEINFO_HELP, no_args_is_help=False, invoke_without_command=True)


def dispatch(args: list[str], settings: HarnessSettings, stdin: bytes = b"") -> CommandResult:
    """Dispatch fileinfo for `minerva run`."""
    _ = settings
    _ = stdin
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no path was provided for `fileinfo`",
                "pass a file or directory path",
                ["`fileinfo ./aapl-filings/AAPL/`", "`fileinfo ./aapl-filings/AAPL/10-K/2025-11-01.md`"],
                FILEINFO_HELP,
            ),
            exit_code=1,
        )
    return inspect_path_command(args[0])


def inspect_path_command(path: str) -> CommandResult:
    start = time.perf_counter()
    try:
        target = resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"{path} does not exist")
        if target.is_dir():
            body = _directory_inventory(target)
        else:
            body = _file_inventory(target)
    except Exception as exc:
        return error_result(
            f"failed to inspect `{path}`: {exc}",
            "pass an existing file or directory path",
            ["`fileinfo ./aapl-filings/AAPL/`", "`fileinfo ./aapl-filings/AAPL/10-K/2025-11-01.md`"],
            start,
        )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


@app.callback()
def fileinfo_cli_command(
    ctx: typer.Context,
    path: str | None = typer.Argument(None, help="Path to a file or directory."),
) -> None:
    """Inspect a file or directory and recommend how to handle it.

    Example:
      minerva fileinfo ./aapl-filings/AAPL/10-K/2025-11-01.md
    """
    show_help_if_bare(ctx, path=path)
    if not path:
        abort_with_help(
            ctx,
            what_went_wrong="no path was provided for `fileinfo`",
            what_to_do="pass a file or directory path",
            alternatives=["`minerva fileinfo ./aapl-filings/AAPL/`", "`minerva fileinfo ./aapl-filings/AAPL/10-K/2025-11-01.md`"],
        )
    _print(inspect_path_command(path))


def _file_inventory(path: Path) -> str:
    sample = path.read_bytes()[:8192]
    binary = is_binary(sample)
    format_name = detect_file_format(path, sample)
    size_bytes = path.stat().st_size
    estimated = estimate_tokens(path.read_text(encoding="utf-8", errors="replace")) if not binary else max(1, size_bytes // 4)
    line_count = "N/A (binary)" if binary else str(path.read_text(encoding="utf-8", errors="replace").count("\n") + 1)
    recommendation = _recommendation(binary=binary, format_name=format_name, estimated_tokens=estimated)
    return "\n".join(
        [
            f"path: {relative_display_path(path)}",
            "type: file",
            f"format: {format_name}",
            f"size_bytes: {size_bytes}",
            f"estimated_tokens: ~{estimated}",
            f"line_count: {line_count}",
            f"recommendation: {recommendation}",
        ]
    )


def _directory_inventory(path: Path) -> str:
    entries = sorted(path.iterdir(), key=lambda item: item.name.lower())
    lines = [
        f"path: {relative_display_path(path)}",
        "type: directory",
        "contents:",
    ]
    total_files = 0
    total_bytes = 0
    total_tokens = 0
    for entry in entries:
        if entry.is_dir():
            file_count, size_bytes, tokens = _directory_totals(entry)
            lines.append(f"  {entry.name}/  {file_count} files  {_human_size(size_bytes)}  ~{tokens} tokens")
        else:
            size_bytes = entry.stat().st_size
            sample = entry.read_bytes()[:8192]
            tokens = max(1, size_bytes // 4) if is_binary(sample) else estimate_tokens(entry.read_text(encoding='utf-8', errors='replace'))
            lines.append(f"  {entry.name}  1 file  {_human_size(size_bytes)}  ~{tokens} tokens")
            file_count = 1
        total_files += file_count
        total_bytes += size_bytes
        total_tokens += tokens
    lines.extend(
        [
            f"total: {total_files} files, {_human_size(total_bytes)}, ~{total_tokens} tokens",
            "recommendation: Use `minerva extract` for one file or `minerva extract-files` for many files.",
        ]
    )
    return "\n".join(lines)


def _directory_totals(path: Path) -> tuple[int, int, int]:
    total_files = 0
    total_bytes = 0
    total_tokens = 0
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        total_files += 1
        size_bytes = candidate.stat().st_size
        total_bytes += size_bytes
        sample = candidate.read_bytes()[:8192]
        total_tokens += max(1, size_bytes // 4) if is_binary(sample) else estimate_tokens(candidate.read_text(encoding="utf-8", errors="replace"))
    return total_files, total_bytes, total_tokens


def _recommendation(*, binary: bool, format_name: str, estimated_tokens: int) -> str:
    lowered = format_name.lower()
    if binary and "pdf" in lowered:
        return "Use OpenClaw's `pdf` tool with a targeted prompt."
    if binary and lowered.startswith("image/"):
        return "Use OpenClaw's `image` tool to analyze."
    if binary:
        return "Binary file. Convert to text before processing."
    if estimated_tokens < 5_000:
        return "Small enough to read directly with OpenClaw's `read` tool."
    return "Use `minerva extract` for one file or `minerva extract-files` for many files."


def _human_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f}MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.0f}KB"
    return f"{size_bytes}B"


def _usage_error(what: str, what_to_do: str, alternatives: list[str], help_text: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {what}",
            f"What to do instead: {what_to_do}",
            f"Available alternatives: {', '.join(alternatives)}",
            "",
            help_text.rstrip(),
        ]
    )


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
