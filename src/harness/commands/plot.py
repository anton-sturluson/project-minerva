"""Plot generation commands."""

from __future__ import annotations

import time
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import typer

from harness.commands.common import elapsed_ms, error_result, relative_display_path
from harness.commands.fs import resolve_workspace_path
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from minerva.plotting import apply_theme, save_fig

app = typer.Typer(help="Plot commands.", no_args_is_help=True)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path plot commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "plot",
            "Usage: plot <bar|line|scatter> --data <csv_file> --x <col> --y <col> [--title <str>] [--output <path>]",
            ["plot bar --data file.csv --x name --y value"],
        )

    chart_type: str = args[0]
    try:
        parsed = _parse_flag_args(args[1:])
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    required = ["data", "x", "y"]
    if any(name not in parsed for name in required):
        return _usage_error(
            f"plot {chart_type}",
            f"Usage: plot {chart_type} --data <csv_file> --x <col> --y <col> [--title <str>] [--output <path>]",
            ["plot line --data file.csv --x date --y revenue"],
        )
    return create_plot(
        chart_type=chart_type,
        data_path=parsed["data"],
        x_column=parsed["x"],
        y_column=parsed["y"],
        title=parsed.get("title"),
        output_path=parsed.get("output"),
        settings=active_settings,
    )


def create_plot(
    *,
    chart_type: str,
    data_path: str,
    x_column: str,
    y_column: str,
    title: str | None = None,
    output_path: str | None = None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        csv_path: Path = resolve_workspace_path(data_path, active_settings)
        frame: pd.DataFrame = pd.read_csv(csv_path)
        target_path: Path = (
            resolve_workspace_path(output_path, active_settings)
            if output_path
            else resolve_workspace_path(f"plots/{chart_type}-{csv_path.stem}-{x_column}-{y_column}.png", active_settings)
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        apply_theme()
        fig, ax = plt.subplots()
        if chart_type == "bar":
            ax.bar(frame[x_column], frame[y_column])
        elif chart_type == "line":
            ax.plot(frame[x_column], frame[y_column], marker="o")
        elif chart_type == "scatter":
            ax.scatter(frame[x_column], frame[y_column])
        else:
            raise ValueError(f"unknown chart type: {chart_type}")
        ax.set_xlabel(x_column)
        ax.set_ylabel(y_column)
        ax.set_title(title or f"{chart_type.title()} Chart")
        fig.autofmt_xdate()
        save_fig(fig, target_path)
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to create {chart_type} chart: {exc}\n"
            "What to do instead: verify the CSV path and column names, then retry.\n"
            "Available alternatives: `cat <csv_file>`, `stat <csv_file>`",
            start,
        )

    relative_path: str = relative_display_path(target_path, active_settings.ensure_workspace_root())
    return CommandResult.from_text(f"Saved {chart_type} chart to {relative_path}", duration_ms=elapsed_ms(start))


@app.command("bar")
def bar_command(
    data: str = typer.Option(..., "--data"),
    x: str = typer.Option(..., "--x"),
    y: str = typer.Option(..., "--y"),
    title: str | None = typer.Option(None, "--title"),
    output: str | None = typer.Option(None, "--output"),
) -> None:
    """Create a bar chart from a CSV file."""
    _print(create_plot(chart_type="bar", data_path=data, x_column=x, y_column=y, title=title, output_path=output))


@app.command("line")
def line_command(
    data: str = typer.Option(..., "--data"),
    x: str = typer.Option(..., "--x"),
    y: str = typer.Option(..., "--y"),
    title: str | None = typer.Option(None, "--title"),
    output: str | None = typer.Option(None, "--output"),
) -> None:
    """Create a line chart from a CSV file."""
    _print(create_plot(chart_type="line", data_path=data, x_column=x, y_column=y, title=title, output_path=output))


@app.command("scatter")
def scatter_command(
    data: str = typer.Option(..., "--data"),
    x: str = typer.Option(..., "--x"),
    y: str = typer.Option(..., "--y"),
    title: str | None = typer.Option(None, "--title"),
    output: str | None = typer.Option(None, "--output"),
) -> None:
    """Create a scatter plot from a CSV file."""
    _print(create_plot(chart_type="scatter", data_path=data, x_column=x, y_column=y, title=title, output_path=output))


def _parse_flag_args(args: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    index: int = 0
    while index < len(args):
        token: str = args[index]
        if not token.startswith("--") or index + 1 >= len(args):
            raise ValueError(
                "Invalid plot arguments.\n"
                "What to do instead: pass values as `--name value` pairs.\n"
                "Available alternatives: `plot bar --data file.csv --x a --y b`, `plot line --data file.csv --x a --y b`"
            )
        parsed[token.removeprefix("--")] = args[index + 1]
        index += 2
    return parsed


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
