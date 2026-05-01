"""Typer CLI and shell-style command chaining for the investment harness."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Callable

import typer

from harness.commands import register_commands
from harness.commands.common import show_help_if_bare
from harness.commands import analyze as analyze_commands
from harness.commands import brief as brief_commands
from harness.commands import evidence as evidence_commands
from harness.commands import extract as extract_commands
from harness.commands import fileinfo as fileinfo_commands
from harness.commands import plot as plot_commands
from harness.commands import portfolio as portfolio_commands
from harness.commands import research as research_commands
from harness.commands import sec as sec_commands
from harness.commands import valuation as valuation_commands
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope


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
        "  minerva sec 10k AAPL --items 7\n"
        "  minerva extract -f apple-10k.md \"What are the key risks?\"\n"
        "  minerva extract-files -q questions.md -F selected-files.txt -o data/extractions/summary\n"
        "  minerva run \"sec 10k AAPL --items 1A | extract 'What are the top 3 risk factors?'\"\n"
    ),
    add_completion=False,
    no_args_is_help=True,
)


@app.command(
    "run",
    help=(
        "Execute a chain of Minerva domain commands.\n\n"
        "Examples:\n"
        "  minerva run \"sec 10k AAPL --items 1A | extract 'Top risks'\"\n"
        "  minerva run \"sec financials MSFT --type income && valuation comps --ntm-revenue 420e9 ...\"\n"
    ),
)
def run_command(
    ctx: typer.Context,
    command: str | None = typer.Argument(
        None,
        help='Command chain to execute. Example: \'sec 10k AAPL --items 1A | extract "Top risks"\'',
    ),
) -> None:
    """Execute a shell-style command chain with pipes and short-circuit operators."""
    show_help_if_bare(ctx, command=command)
    if not command:
        typer.echo(
            "What went wrong: no command chain was provided.\n"
            "What to do instead: pass a quoted Minerva command chain.\n"
            "Available alternatives: `minerva run \"sec 10k AAPL --items 7\"`, `minerva --help`\n\n"
            f"{ctx.get_help()}"
        )
        raise typer.Exit(1)
    settings: HarnessSettings = get_settings()
    result: CommandResult = execute_chain(command, settings=settings)
    envelope = OutputEnvelope.from_result(result, workspace_root=settings.ensure_workspace_root())
    typer.echo(envelope.render())


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
                "What went wrong: no command was parsed from the chain.\n"
                "What to do instead: pass a quoted command string to `minerva run`.\n"
                "Available alternatives: `minerva --help`, `minerva run \"sec 10k AAPL --items 7\"`"
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
        should_run = _should_run_after(result.exit_code, pipeline[-1].operator)
        index += len(pipeline)

    return previous_result or CommandResult.from_text("")


def generate_command_catalog(typer_app: typer.Typer) -> str:
    """Generate Level 0 help text from registered Typer commands and groups."""
    lines: list[str] = []
    _collect_command_catalog(typer_app, [], lines)
    return "\n".join(lines)


def dispatch_command(argv: list[str], stdin: bytes = b"", settings: HarnessSettings | None = None) -> CommandResult:
    """Dispatch a command to a registered internal handler only."""
    active_settings: HarnessSettings = settings or get_settings()
    if not argv:
        return CommandResult.from_text(
            "",
            stderr=(
                "What went wrong: an empty command segment was provided.\n"
                "What to do instead: provide a command name before any arguments.\n"
                "Available alternatives: sec, evidence, portfolio, brief, valuation, analyze, plot, extract, fileinfo, research"
            ),
            exit_code=1,
        )

    command: str = argv[0]
    dispatchers: dict[str, Callable[[list[str], HarnessSettings, bytes], CommandResult]] = {
        "sec": lambda full_argv, current_settings, current_stdin: sec_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "evidence": lambda full_argv, current_settings, current_stdin: evidence_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "portfolio": lambda full_argv, current_settings, current_stdin: portfolio_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "brief": lambda full_argv, current_settings, current_stdin: brief_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "valuation": lambda full_argv, current_settings, current_stdin: valuation_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "analyze": lambda full_argv, current_settings, current_stdin: analyze_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "plot": lambda full_argv, current_settings, current_stdin: plot_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "extract": lambda full_argv, current_settings, current_stdin: extract_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "extract-files": lambda full_argv, current_settings, current_stdin: extract_commands.dispatch_files(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "fileinfo": lambda full_argv, current_settings, current_stdin: fileinfo_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
        "research": lambda full_argv, current_settings, current_stdin: research_commands.dispatch(
            full_argv[1:], settings=current_settings, stdin=current_stdin
        ),
    }
    dispatcher = dispatchers.get(command)
    if dispatcher is None:
        return CommandResult.from_text(
            "",
            stderr=(
                f"What went wrong: unknown command `{command}`.\n"
                "What to do instead: use a registered Minerva domain command.\n"
                f"Available alternatives: {', '.join(_available_root_commands())}"
            ),
            exit_code=1,
        )
    return dispatcher(argv, active_settings, stdin)


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
                    f"What went wrong: failed to parse command `{item.text}` because {exc}.\n"
                    "What to do instead: fix the quoting and retry.\n"
                    "Available alternatives: wrap arguments with spaces in quotes"
                ),
                exit_code=1,
            )
        last_result = dispatch_command(argv, stdin=stdin, settings=settings)
        stdin = last_result.stdout
    return last_result


def _should_run_after(exit_code: int, operator: str | None) -> bool:
    if operator == "&&":
        return exit_code == 0
    if operator == "||":
        return exit_code != 0
    return True


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


def _available_root_commands() -> list[str]:
    names: set[str] = set()
    for command_info in app.registered_commands:
        names.add(command_info.name or command_info.callback.__name__.replace("_", "-"))
    for group_info in app.registered_groups:
        names.add(group_info.name or "group")
    return sorted(names)
