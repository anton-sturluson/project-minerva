"""Codex session recommendation command."""

from __future__ import annotations

import shlex
import time
from pathlib import Path

import typer

from harness.commands.common import elapsed_ms
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(help="Codex delegation command.", no_args_is_help=False)


def dispatch(args: list[str], settings: HarnessSettings | None = None) -> CommandResult:
    if not args:
        return _usage_error("codex", "Usage: codex <prompt>", ["codex \"Implement a new command group\""])
    return codex_prompt(" ".join(args), settings=settings)


def codex_prompt(prompt: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    project_dir: Path = Path.cwd().resolve()
    workspace_root: Path = active_settings.ensure_workspace_root()
    instruction: str = (
        f"Project dir: {project_dir}\n"
        f"Workspace root: {workspace_root}\n"
        "Relevant files: src/harness/cli.py, src/harness/commands/__init__.py, src/harness/output.py\n"
        "Command structure: shell-style dispatch_command() routes to per-group dispatch helpers; every command returns CommandResult.\n"
        "Typer registration pattern: register group apps in src/harness/commands/__init__.py and keep CLI wrappers thin.\n\n"
        "Recommended Codex command:\n"
        f"codex --cwd {shlex.quote(str(project_dir))} {shlex.quote(prompt)}"
    )
    return CommandResult.from_text(instruction, duration_ms=elapsed_ms(start))


@app.callback(invoke_without_command=True)
def codex_callback(
    ctx: typer.Context,
    prompt_parts: list[str] | None = typer.Argument(None, help="Prompt to send to Codex."),
) -> None:
    """Print a recommended Codex command for this project."""
    if ctx.invoked_subcommand is not None:
        return
    if not prompt_parts:
        _print(_usage_error("codex", "Usage: codex <prompt>", ["codex \"Implement a new command group\""]))
        raise typer.Exit()
    _print(codex_prompt(" ".join(prompt_parts)))


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
