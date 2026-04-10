"""Command registration for the investment harness."""

from __future__ import annotations

import typer

from harness.commands import analysis, analyze, evidence, extract, fileinfo, plot, research, sec, valuation


def register_commands(app: typer.Typer) -> None:
    """Register all command groups on the root Typer app."""
    app.add_typer(sec.app, name="sec")
    app.add_typer(evidence.app, name="evidence")
    app.add_typer(valuation.app, name="valuation")
    app.add_typer(analyze.app, name="analyze")
    app.add_typer(analysis.app, name="analysis")
    app.add_typer(plot.app, name="plot")
    app.add_typer(extract.app, name="extract")
    app.add_typer(extract.extract_many_app, name="extract-many")
    app.add_typer(fileinfo.app, name="fileinfo")
    app.add_typer(research.app, name="research")
