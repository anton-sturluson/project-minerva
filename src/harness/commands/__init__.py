"""Command registration for the investment harness."""

from __future__ import annotations

import typer

from harness.commands import (
    analyze,
    codex,
    knowledge,
    memory_cmd,
    plot,
    read,
    report,
    sec,
    valuation,
    web,
)


def register_commands(app: typer.Typer) -> None:
    """Register all command groups on the root Typer app."""
    app.add_typer(web.app, name="web")
    app.add_typer(sec.app, name="sec")
    app.add_typer(valuation.app, name="valuation")
    app.add_typer(analyze.app, name="analyze")
    app.add_typer(knowledge.app, name="knowledge")
    app.add_typer(memory_cmd.app, name="memory")
    app.add_typer(plot.app, name="plot")
    app.add_typer(report.app, name="report")
    app.add_typer(read.app, name="read")
    app.add_typer(codex.app, name="codex")
