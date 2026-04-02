"""Placeholder valuation command group."""

from __future__ import annotations

import typer

from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(help="Valuation commands. Coming in Phase 2.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def valuation_placeholder() -> None:
    """Valuation tools placeholder."""
    typer.echo(OutputEnvelope.from_result(CommandResult.from_text("Not yet implemented. Coming in Phase 2/3.")).render())
