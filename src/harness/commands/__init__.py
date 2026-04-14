"""Command registration for the investment harness."""

from __future__ import annotations

import typer

from harness.commands import analyze, brief, extract, fileinfo, plot, portfolio, research, sec, valuation


def register_commands(app: typer.Typer) -> None:
    """Register all command groups on the root Typer app."""
    app.add_typer(sec.app, name="sec")
    app.add_typer(portfolio.app, name="portfolio")
    app.add_typer(brief.app, name="brief")
    app.add_typer(valuation.app, name="valuation")
    app.add_typer(analyze.app, name="analyze")
    app.add_typer(plot.app, name="plot")
    app.add_typer(extract.app, name="extract")
    app.add_typer(extract.extract_many_app, name="extract-many")
    app.add_typer(fileinfo.app, name="fileinfo")
    app.add_typer(research.app, name="research")
