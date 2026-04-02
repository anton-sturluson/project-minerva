"""Typer CLI and shell-style command chaining for the investment harness."""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from harness.commands import register_commands
from harness.commands import fs as fs_commands
from harness.commands import web as web_commands
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

PLACEHOLDER_GROUPS: set[str] = {
    "sec",
    "valuation",
    "analyze",
    "knowledge",
    "memory",
    "plot",
    "report",
    "read",
    "codex",
}


@dataclass(slots=True)
class ParsedCommand:
    """A parsed command segment and the operator that follows it."""

    text: str
    operator: str | None = None


app = typer.Typer(
    name="minerva",
    help=(
        "Minerva investment harness CLI.\n\n"
        "Examples:\n"
        "  minerva cat notes.txt\n"
        "  minerva web search \"hotel software benchmarks\"\n"
        "  minerva run \"cat notes.txt | grep margin && stat notes.txt\""
    ),
    add_completion=False,
    no_args_is_help=True,
)


@app.command("run")
def run_command(
    command: str = typer.Argument(
        ...,
        help='Command chain to execute. Example: \'cat sample.txt | grep revenue && stat sample.txt\'',
    )
) -> None:
    """Execute a shell-style command chain with pipes and short-circuit operators."""
    settings: HarnessSettings = get_settings()
    result: CommandResult = execute_chain(command, settings=settings)
    envelope = OutputEnvelope.from_result(result, workspace_root=settings.ensure_workspace_root())
    typer.echo(envelope.render())


@app.command("cat")
def cat_command(path: str = typer.Argument(..., help="Workspace-relative path. Example: reports/notes.txt")) -> None:
    """Read a text file from the workspace."""
    _print_envelope(fs_commands.cat_file(path))


@app.command("ls")
def ls_command(directory: str | None = typer.Argument(None, help="Directory to list. Defaults to workspace root.")) -> None:
    """List files in the workspace."""
    _print_envelope(fs_commands.list_files(directory))


@app.command("write")
def write_command(
    path: str = typer.Argument(..., help="Workspace-relative output path. Example: notes/todo.txt"),
    content: str = typer.Argument(..., help='Content to write. Example: "hello world"'),
) -> None:
    """Write a UTF-8 text file inside the workspace."""
    _print_envelope(fs_commands.write_file(path, content))


@app.command("stat")
def stat_command(path: str = typer.Argument(..., help="Workspace-relative path to inspect.")) -> None:
    """Show file metadata and reading guidance."""
    _print_envelope(fs_commands.stat_path(path))


@app.command("rm")
def rm_command(path: str = typer.Argument(..., help="Workspace-relative path to remove.")) -> None:
    """Remove a file or directory from the workspace."""
    _print_envelope(fs_commands.remove_path(path))


register_commands(app)


def parse_chain(command: str) -> list[ParsedCommand]:
    """Split a command string on unquoted |, &&, ||, and ; operators."""
    commands: list[ParsedCommand] = []
    buffer: list[str] = []
    quote: str | None = None
    escape: bool = False
    index: int = 0

    while index < len(command):
        char: str = command[index]
        if escape:
            buffer.append(char)
            escape = False
            index += 1
            continue

        if char == "\\":
            buffer.append(char)
            escape = True
            index += 1
            continue

        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            index += 1
            continue

        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
            index += 1
            continue

        next_two: str = command[index : index + 2]
        if next_two in {"&&", "||"}:
            commands.append(ParsedCommand(text="".join(buffer).strip(), operator=next_two))
            buffer = []
            index += 2
            continue
        if char in {"|", ";"}:
            commands.append(ParsedCommand(text="".join(buffer).strip(), operator=char))
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail: str = "".join(buffer).strip()
    if tail or not commands:
        commands.append(ParsedCommand(text=tail, operator=None))

    return [item for item in commands if item.text]


def execute_chain(command: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Execute a parsed chain sequentially with shell-like operator semantics."""
    active_settings: HarnessSettings = settings or get_settings()
    parsed: list[ParsedCommand] = parse_chain(command)
    if not parsed:
        return CommandResult.from_text(
            "",
            stderr=(
                "No command to run.\n"
                "What to do instead: pass a quoted command string to `minerva run`.\n"
                "Available alternatives: `minerva --help`, `minerva run \"ls\"`"
            ),
            exit_code=1,
        )

    previous_result: CommandResult | None = None
    pending_stdin: bytes = b""
    should_run: bool = True
    index: int = 0

    while index < len(parsed):
        item: ParsedCommand = parsed[index]
        if not should_run:
            previous_result = previous_result or CommandResult.from_text("")
            should_run = _should_run_after(previous_result.exit_code, item.operator)
            index += 1
            continue

        pipeline: list[ParsedCommand] = [item]
        while pipeline[-1].operator == "|" and index + len(pipeline) < len(parsed):
            pipeline.append(parsed[index + len(pipeline)])

        result: CommandResult = _execute_pipeline(pipeline, pending_stdin, active_settings)
        previous_result = result
        pending_stdin = b""
        last_operator: str | None = pipeline[-1].operator
        should_run = _should_run_after(result.exit_code, last_operator)
        index += len(pipeline)

    return previous_result or CommandResult.from_text("")


def generate_command_catalog(typer_app: typer.Typer) -> str:
    """Generate Level 0 help text from registered Typer commands and groups."""
    lines: list[str] = []
    _collect_command_catalog(typer_app, [], lines)
    return "\n".join(lines)


def dispatch_command(argv: list[str], stdin: bytes = b"", settings: HarnessSettings | None = None) -> CommandResult:
    """Dispatch a command to an internal handler or external process."""
    active_settings: HarnessSettings = settings or get_settings()
    if not argv:
        return CommandResult.from_text(
            "",
            stderr=(
                "Empty command.\n"
                "What to do instead: provide a command name before any arguments.\n"
                "Available alternatives: `ls`, `cat <path>`, `web search <query>`"
            ),
            exit_code=1,
        )

    command: str = argv[0]
    if command == "cat":
        if len(argv) != 2:
            return _usage_error("cat", "Usage: cat <path>", ["stat <path>", "ls"])
        return fs_commands.cat_file(argv[1], settings=active_settings)
    if command == "ls":
        if len(argv) > 2:
            return _usage_error("ls", "Usage: ls [dir]", ["stat <path>", "cat <file>"])
        return fs_commands.list_files(argv[1] if len(argv) == 2 else None, settings=active_settings)
    if command == "write":
        if len(argv) < 3:
            return _usage_error("write", "Usage: write <path> <content>", ["cat <path>", "ls"])
        return fs_commands.write_file(argv[1], " ".join(argv[2:]), settings=active_settings)
    if command == "stat":
        if len(argv) != 2:
            return _usage_error("stat", "Usage: stat <path>", ["ls", "cat <file>"])
        return fs_commands.stat_path(argv[1], settings=active_settings)
    if command == "rm":
        if len(argv) != 2:
            return _usage_error("rm", "Usage: rm <path>", ["ls", "stat <path>"])
        return fs_commands.remove_path(argv[1], settings=active_settings)
    if command == "web":
        return _dispatch_web(argv[1:], active_settings)
    if command in PLACEHOLDER_GROUPS:
        return CommandResult.from_text("Not yet implemented. Coming in Phase 2/3.")

    return _run_external_command(argv, stdin=stdin, settings=active_settings)


def _execute_pipeline(
    pipeline: list[ParsedCommand],
    initial_stdin: bytes,
    settings: HarnessSettings,
) -> CommandResult:
    stdin: bytes = initial_stdin
    last_result: CommandResult = CommandResult.from_text("")

    for item in pipeline:
        try:
            argv: list[str] = shlex.split(item.text)
        except ValueError as exc:
            return CommandResult.from_text(
                "",
                stderr=(
                    f"Failed to parse command: {item.text}\n"
                    f"What went wrong: {exc}\n"
                    "What to do instead: fix the quoting and retry.\n"
                    "Available alternatives: wrap arguments with spaces in quotes."
                ),
                exit_code=1,
            )

        last_result = dispatch_command(argv, stdin=stdin, settings=settings)
        stdin = last_result.stdout

    return last_result


def _dispatch_web(args: list[str], settings: HarnessSettings) -> CommandResult:
    if not args:
        return _usage_error("web", "Usage: web <search|fetch> <value>", ["web search <query>", "web fetch <url>"])
    subcommand: str = args[0]
    if subcommand == "search":
        if len(args) < 2:
            return _usage_error("web search", "Usage: web search <query>", ["web fetch <url>"])
        return web_commands.search_web(" ".join(args[1:]), settings=settings)
    if subcommand == "fetch":
        if len(args) != 2:
            return _usage_error("web fetch", "Usage: web fetch <url>", ["web search <query>"])
        return web_commands.fetch_url(args[1])
    return _usage_error("web", f"Unknown web subcommand: {subcommand}", ["web search <query>", "web fetch <url>"])


def _run_external_command(argv: list[str], stdin: bytes, settings: HarnessSettings) -> CommandResult:
    start: float = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            cwd=settings.ensure_workspace_root(),
            check=False,
        )
    except FileNotFoundError:
        return CommandResult.from_text(
            "",
            stderr=(
                f"Unknown command: {' '.join(argv)}\n"
                "What to do instead: use a registered Minerva command or an installed system command.\n"
                "Available alternatives: `ls`, `cat <path>`, `web search <query>`"
            ),
            exit_code=127,
            duration_ms=_elapsed_ms(start),
        )

    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        duration_ms=_elapsed_ms(start),
    )


def _should_run_after(exit_code: int, operator: str | None) -> bool:
    if operator == "&&":
        return exit_code == 0
    if operator == "||":
        return exit_code != 0
    return True


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


def _collect_command_catalog(typer_app: typer.Typer, prefix: list[str], lines: list[str]) -> None:
    for command_info in typer_app.registered_commands:
        name: str = command_info.name or command_info.callback.__name__.replace("_", "-")
        help_text: str = _first_line(command_info.help or (command_info.callback.__doc__ or ""))
        lines.append(f"{' '.join(prefix + [name])} - {help_text}")

    for group_info in typer_app.registered_groups:
        group_name: str = group_info.name or "group"
        group_help: str = _first_line(group_info.help or "")
        lines.append(f"{' '.join(prefix + [group_name])} - {group_help}")
        if group_info.typer_instance is not None:
            _collect_command_catalog(group_info.typer_instance, prefix + [group_name], lines)


def _first_line(text: str) -> str:
    stripped: str = text.strip()
    return stripped.splitlines()[0] if stripped else "No description."


def _print_envelope(result: CommandResult) -> None:
    settings: HarnessSettings = get_settings()
    envelope = OutputEnvelope.from_result(result, workspace_root=settings.ensure_workspace_root())
    typer.echo(envelope.render())


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))
