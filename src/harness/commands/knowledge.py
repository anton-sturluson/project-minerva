"""Knowledge base commands."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from harness.commands.common import elapsed_ms, error_result, relative_display_path
from harness.commands.fs import resolve_workspace_path
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

GLOBAL_KNOWLEDGE_ROOT: Path = Path("/Users/charlie-buffet/Documents/project-minerva/hard-disk/knowledge")

app = typer.Typer(help="Knowledge-base commands.", no_args_is_help=True)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path knowledge commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "knowledge",
            "Usage: knowledge <search|read|write> ...",
            ["knowledge search <query>", "knowledge read <path>"],
        )

    subcommand: str = args[0]
    if subcommand == "search":
        if len(args) < 2:
            return _usage_error("knowledge search", "Usage: knowledge search <query>", ["knowledge read <path>"])
        return search_knowledge(" ".join(args[1:]), settings=active_settings)
    if subcommand == "read":
        if len(args) != 2:
            return _usage_error("knowledge read", "Usage: knowledge read <path>", ["knowledge search <query>"])
        return read_knowledge(args[1], settings=active_settings)
    if subcommand == "write":
        if len(args) < 3:
            return _usage_error(
                "knowledge write",
                "Usage: knowledge write <path> <content>",
                ["knowledge read <path>", "knowledge search <query>"],
            )
        return write_knowledge(args[1], " ".join(args[2:]), settings=active_settings)
    return _usage_error("knowledge", f"Unknown knowledge subcommand: {subcommand}", ["knowledge search <query>"])


def search_knowledge(query: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    root: Path = _knowledge_root(active_settings, allow_fallback=True)
    if not root.exists():
        return error_result(
            "What went wrong: knowledge base directory does not exist.\n"
            "What to do instead: create `knowledge/` under the workspace or add files with `knowledge write`.\n"
            "Available alternatives: `ls`, `write knowledge/<file> <content>`",
            start,
        )

    lowered_query: str = query.lower()
    matches: list[str] = []
    for file_path in sorted(root.rglob("*")):
        if file_path.suffix.lower() not in {".md", ".txt"} or not file_path.is_file():
            continue
        try:
            content: str = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippets: list[str] = []
        for line in content.splitlines():
            if lowered_query in line.lower():
                snippets.append(line.strip())
            if len(snippets) == 3:
                break
        if snippets:
            matches.append(
                f"{relative_display_path(file_path, root)}\n"
                + "\n".join(f"- {snippet}" for snippet in snippets)
            )

    body: str = "\n\n".join(matches) if matches else "No matches found."
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def read_knowledge(path: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target: Path = _resolve_knowledge_path(path, active_settings, allow_fallback=True)
    except ValueError as exc:
        return error_result(str(exc), start)

    if not target.exists():
        return error_result(
            f"What went wrong: knowledge file not found: {path}\n"
            "What to do instead: use `knowledge search <query>` or `ls knowledge` to find the file first.\n"
            "Available alternatives: `knowledge search <query>`, `knowledge write <path> <content>`",
            start,
        )

    return CommandResult.from_text(target.read_text(encoding="utf-8", errors="replace"), duration_ms=elapsed_ms(start))


def write_knowledge(path: str, content: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target: Path = _resolve_knowledge_path(path, active_settings, allow_fallback=False)
    except ValueError as exc:
        return error_result(str(exc), start)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    relative_path: str = relative_display_path(target, active_settings.ensure_workspace_root())
    return CommandResult.from_text(
        f"Wrote {len(content.encode('utf-8'))} bytes to {relative_path}",
        duration_ms=elapsed_ms(start),
    )


@app.command("search")
def search_command(query: str = typer.Argument(..., help="Case-insensitive text query.")) -> None:
    """Search the knowledge base for matching files and snippets."""
    _print(search_knowledge(query))


@app.command("read")
def read_command(path: str = typer.Argument(..., help="Path relative to the knowledge root.")) -> None:
    """Read a knowledge file."""
    _print(read_knowledge(path))


@app.command("write")
def write_command(
    path: str = typer.Argument(..., help="Path relative to the knowledge root."),
    content: str = typer.Argument(..., help="Text content to write."),
) -> None:
    """Write a knowledge file."""
    _print(write_knowledge(path, content))


def _knowledge_root(settings: HarnessSettings, *, allow_fallback: bool) -> Path:
    workspace_root: Path = settings.ensure_workspace_root()
    local_root: Path = workspace_root / "knowledge"
    if local_root.exists() or not allow_fallback:
        return local_root
    return GLOBAL_KNOWLEDGE_ROOT


def _resolve_knowledge_path(path: str, settings: HarnessSettings, *, allow_fallback: bool) -> Path:
    root: Path = _knowledge_root(settings, allow_fallback=allow_fallback)
    if root == GLOBAL_KNOWLEDGE_ROOT and allow_fallback:
        candidate: Path = (root / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"What went wrong: knowledge path escapes the knowledge root: {path}\n"
                f"What to do instead: use a path inside {root}\n"
                "Available alternatives: `knowledge search <query>`, `knowledge read <path>`"
            ) from exc
        return candidate
    return resolve_workspace_path(str(Path("knowledge") / path), settings)


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


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
