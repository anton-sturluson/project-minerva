"""Placeholder codex command group."""

from __future__ import annotations

import typer

from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(help="Codex delegation commands. Coming in Phase 3.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def codex_placeholder() -> None:
    """Codex tools placeholder."""
    typer.echo(OutputEnvelope.from_result(CommandResult.from_text("Not yet implemented. Coming in Phase 2/3.")).render())
