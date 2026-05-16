"""Plot generation commands."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from harness.commands.common import (
    abort_with_help,
    elapsed_ms,
    error_result,
    parse_flag_args,
    read_text_input,
    relative_display_path,
    resolve_path,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

PLOT_HELP = (
    "Standardized chart generation.\n\n"
    "Examples:\n"
    "  minerva plot bar --data revenue.csv --x year --y revenue --theme minerva-classic\n"
    "  minerva plot scatter --data comps.csv --x growth --y ev_rev --theme bloomberg\n"
    "  minerva run \"sec 10k AAPL --items 1A | plot wordcloud --title 'AAPL Risk Factors' --output aapl-risks.png\"\n"
)

THEMES: dict[str, dict[str, str]] = {
    "minerva-classic": {
        "primary": "#1B365D",
        "secondary": "#8B0000",
        "tertiary": "#2E5339",
        "accent": "#4A3728",
        "grid": "#D4D4D4",
        "background": "#FFFFFF",
        "text": "#3A3A3A",
    },
    "bloomberg": {
        "primary": "#FF6B35",
        "secondary": "#4ECDC4",
        "tertiary": "#45B7D1",
        "accent": "#96CEB4",
        "grid": "#333333",
        "background": "#0E1117",
        "text": "#CCCCCC",
    },
}

app = typer.Typer(help=PLOT_HELP, no_args_is_help=True)
def dispatch(
    args: list[str],
    settings: HarnessSettings,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path plot commands."""
    
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no `plot` subcommand was provided",
                "choose bar, line, scatter, or wordcloud",
                ["`plot bar --data data.csv --x year --y revenue`", "`plot wordcloud --file notes.txt`"],
                PLOT_HELP,
            ),
            exit_code=1,
        )

    subcommand = args[0]
    try:
        parsed = parse_flag_args(args[1:])
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    if subcommand in {"bar", "line", "scatter"}:
        required = ["data", "x", "y"]
        if missing := [name for name in required if name not in parsed]:
            return _dispatch_help(subcommand, missing)
        return create_plot(
            chart_type=subcommand,
            data_path=str(parsed["data"]),
            x_column=str(parsed["x"]),
            y_column=str(parsed["y"]),
            title=str(parsed["title"]) if "title" in parsed else None,
            output_path=str(parsed["output"]) if "output" in parsed else None,
            theme=str(parsed.get("theme", settings.minerva_plot_theme)),
            settings=settings,
        )
    if subcommand == "wordcloud":
        return create_wordcloud(
            file_path=str(parsed["file"]) if "file" in parsed else None,
            stdin=stdin,
            output_path=str(parsed["output"]) if "output" in parsed else None,
            title=str(parsed.get("title", "Word Cloud")),
            max_words=int(parsed.get("max-words", 100)),
            theme=str(parsed.get("theme", settings.minerva_plot_theme)),
            stopwords_mode=str(parsed.get("stopwords", "financial")),
            settings=settings,
        )

    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"unknown `plot` subcommand `{subcommand}`",
            "choose bar, line, scatter, or wordcloud",
            ["`plot bar --data data.csv --x year --y revenue`", "`plot wordcloud --file notes.txt`"],
            PLOT_HELP,
        ),
        exit_code=1,
    )
def create_plot(
    *,
    chart_type: str,
    data_path: str,
    x_column: str,
    y_column: str,
    title: str | None = None,
    output_path: str | None = None,
    theme: str = "minerva-classic",
    settings: HarnessSettings,
) -> CommandResult:
    start: float = time.perf_counter()
    _ = settings
    try:
        import matplotlib.pyplot as plt
        import pandas as pd

        palette = _theme(theme)
        csv_path = resolve_path(data_path)
        frame = pd.read_csv(csv_path)
        target_path = resolve_path(output_path or f"{chart_type}-{csv_path.stem}-{x_column}-{y_column}.png")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = _styled_figure(palette)
        if chart_type == "bar":
            ax.bar(frame[x_column], frame[y_column], color=palette["primary"])
        elif chart_type == "line":
            ax.plot(frame[x_column], frame[y_column], color=palette["primary"], marker="o", linewidth=2.0)
        elif chart_type == "scatter":
            ax.scatter(frame[x_column], frame[y_column], color=palette["primary"], edgecolors=palette["secondary"], linewidths=0.8)
        else:
            raise ValueError(f"unknown chart type: {chart_type}")
        _finalize_axes(ax, palette, x_label=x_column, y_label=y_column, title=title or f"{chart_type.title()} Chart")
        fig.autofmt_xdate()
        fig.savefig(target_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:
        return error_result(
            f"failed to create {chart_type} chart: {exc}",
            "verify the CSV path and column names, then retry",
            ["`plot bar --data data.csv --x year --y revenue`", "`plot wordcloud --file notes.txt`"],
            start,
        )
    return CommandResult.from_text(f"saved_to: {relative_display_path(target_path)}", duration_ms=elapsed_ms(start))
def create_wordcloud(
    *,
    file_path: str | None = None,
    stdin: bytes = b"",
    output_path: str | None = None,
    title: str = "Word Cloud",
    max_words: int = 100,
    theme: str = "minerva-classic",
    stopwords_mode: str = "financial",
    settings: HarnessSettings,
) -> CommandResult:
    start = time.perf_counter()
    _ = settings
    try:
        import matplotlib.pyplot as plt
        from wordcloud import WordCloud

        text = read_text_input(file_path=file_path, stdin=stdin)
        palette = _theme(theme)
        target_path = resolve_path(output_path or "wordcloud.png")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        wc = WordCloud(
            width=1600,
            height=900,
            max_words=max_words,
            background_color=palette["background"],
            stopwords=_stopwords(stopwords_mode),
            colormap=None,
            color_func=lambda *args, **kwargs: palette["primary"],
        ).generate(text)
        fig, ax = _styled_figure(palette)
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        ax.set_title(title, color=palette["text"], fontsize=14, fontweight="bold", fontfamily="serif")
        _add_watermark(ax, palette)
        fig.savefig(target_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:
        return error_result(
            f"failed to create word cloud: {exc}",
            "pass a readable text file or pipe text into the command",
            ["`plot wordcloud --file notes.txt`", "`minerva run \"sec 10k AAPL --items 1A | plot wordcloud --output aapl-risks.png\"`"],
            start,
        )
    return CommandResult.from_text(f"saved_to: {relative_display_path(target_path)}", duration_ms=elapsed_ms(start))
@app.command("bar", help="Create a bar chart from a CSV file.\n\nExample:\n  minerva plot bar --data revenue.csv --x year --y revenue --theme minerva-classic")
def bar_command(
    ctx: typer.Context,
    data: str | None = typer.Option(None, "--data", help="Path to a CSV file."),
    x: str | None = typer.Option(None, "--x", help="Column name for the x-axis."),
    y: str | None = typer.Option(None, "--y", help="Column name for the y-axis."),
    title: str | None = typer.Option(None, "--title", help="Chart title."),
    output: str | None = typer.Option(None, "--output", help="Output PNG path."),
    theme: str | None = typer.Option(None, "--theme", help="Theme: minerva-classic or bloomberg."),
) -> None:
    settings = get_settings()
    if None in {data, x, y}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required bar chart inputs",
            what_to_do="provide `--data`, `--x`, and `--y`",
            alternatives=["`minerva plot bar --data revenue.csv --x year --y revenue`", "`minerva plot line --data revenue.csv --x year --y revenue`"],
        )
    _print(create_plot(chart_type="bar", data_path=str(data), x_column=str(x), y_column=str(y), title=title, output_path=output, theme=theme or settings.minerva_plot_theme, settings=settings))
@app.command("line", help="Create a line chart from a CSV file.\n\nExample:\n  minerva plot line --data revenue.csv --x year --y revenue --theme minerva-classic")
def line_command(
    ctx: typer.Context,
    data: str | None = typer.Option(None, "--data", help="Path to a CSV file."),
    x: str | None = typer.Option(None, "--x", help="Column name for the x-axis."),
    y: str | None = typer.Option(None, "--y", help="Column name for the y-axis."),
    title: str | None = typer.Option(None, "--title", help="Chart title."),
    output: str | None = typer.Option(None, "--output", help="Output PNG path."),
    theme: str | None = typer.Option(None, "--theme", help="Theme: minerva-classic or bloomberg."),
) -> None:
    settings = get_settings()
    if None in {data, x, y}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required line chart inputs",
            what_to_do="provide `--data`, `--x`, and `--y`",
            alternatives=["`minerva plot line --data revenue.csv --x year --y revenue`", "`minerva plot scatter --data comps.csv --x growth --y ev_rev`"],
        )
    _print(create_plot(chart_type="line", data_path=str(data), x_column=str(x), y_column=str(y), title=title, output_path=output, theme=theme or settings.minerva_plot_theme, settings=settings))
@app.command("scatter", help="Create a scatter plot from a CSV file.\n\nExample:\n  minerva plot scatter --data comps.csv --x growth --y ev_rev --theme bloomberg")
def scatter_command(
    ctx: typer.Context,
    data: str | None = typer.Option(None, "--data", help="Path to a CSV file."),
    x: str | None = typer.Option(None, "--x", help="Column name for the x-axis."),
    y: str | None = typer.Option(None, "--y", help="Column name for the y-axis."),
    title: str | None = typer.Option(None, "--title", help="Chart title."),
    output: str | None = typer.Option(None, "--output", help="Output PNG path."),
    theme: str | None = typer.Option(None, "--theme", help="Theme: minerva-classic or bloomberg."),
) -> None:
    settings = get_settings()
    if None in {data, x, y}:
        abort_with_help(
            ctx,
            what_went_wrong="missing required scatter plot inputs",
            what_to_do="provide `--data`, `--x`, and `--y`",
            alternatives=["`minerva plot scatter --data comps.csv --x growth --y ev_rev`", "`minerva plot line --data revenue.csv --x year --y revenue`"],
        )
    _print(create_plot(chart_type="scatter", data_path=str(data), x_column=str(x), y_column=str(y), title=title, output_path=output, theme=theme or settings.minerva_plot_theme, settings=settings))
@app.command("wordcloud", help="Create a word cloud from text.\n\nExample:\n  minerva plot wordcloud --file apple-10k.md --title 'AAPL Risk Factors' --output aapl-risks.png")
def wordcloud_command(
    ctx: typer.Context,
    file_path: str | None = typer.Option(None, "--file", help="Path to a text file. Omit to read from stdin."),
    output: str | None = typer.Option(None, "--output", help="Output PNG path."),
    max_words: int = typer.Option(100, "--max-words", help="Maximum words to display."),
    title: str = typer.Option("Word Cloud", "--title", help="Chart title."),
    theme: str | None = typer.Option(None, "--theme", help="Theme: minerva-classic or bloomberg."),
    stopwords: str = typer.Option("financial", "--stopwords", help="Stopword set: financial or default."),
) -> None:
    settings = get_settings()
    if not file_path and typer.get_text_stream("stdin").isatty():
        abort_with_help(
            ctx,
            what_went_wrong="no input text was provided for `plot wordcloud`",
            what_to_do="pass `--file PATH` or pipe text into the command",
            alternatives=["`minerva plot wordcloud --file notes.txt`", "`minerva run \"sec 10k AAPL --items 1A | plot wordcloud --output aapl-risks.png\"`"],
        )
    _print(create_wordcloud(file_path=file_path, stdin=typer.get_binary_stream("stdin").read(), output_path=output, title=title, max_words=max_words, theme=theme or settings.minerva_plot_theme, stopwords_mode=stopwords, settings=settings))
def _theme(name: str) -> dict[str, str]:
    if name not in THEMES:
        raise ValueError("theme must be `minerva-classic` or `bloomberg`")
    return THEMES[name]
def _styled_figure(palette: dict[str, str]):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6), facecolor=palette["background"])
    ax.set_facecolor(palette["background"])
    ax.grid(True, color=palette["grid"], alpha=0.3 if palette["background"] == "#FFFFFF" else 0.6)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig, ax
def _finalize_axes(ax, palette: dict[str, str], *, x_label: str, y_label: str, title: str) -> None:
    ax.set_xlabel(x_label, color=palette["text"], fontsize=11, fontfamily="sans-serif")
    ax.set_ylabel(y_label, color=palette["text"], fontsize=11, fontfamily="sans-serif")
    ax.set_title(title, color=palette["text"], fontsize=14, fontweight="bold", fontfamily="serif")
    ax.tick_params(axis="x", colors=palette["text"], labelsize=10)
    ax.tick_params(axis="y", colors=palette["text"], labelsize=10)
    _add_watermark(ax, palette)
def _add_watermark(ax, palette: dict[str, str]) -> None:
    ax.text(0.99, 0.02, "Minerva", transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color=palette["grid"], alpha=0.8)
def _stopwords(mode: str) -> set[str]:
    from minerva.text_analysis import DEFAULT_FINANCIAL_STOPWORDS
    from wordcloud import STOPWORDS

    if mode == "financial":
        return set(STOPWORDS) | set(DEFAULT_FINANCIAL_STOPWORDS)
    if mode == "default":
        return set(STOPWORDS)
    raise ValueError("`--stopwords` must be `financial` or `default`")
def _dispatch_help(subcommand: str, missing: list[str]) -> CommandResult:
    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"missing required arguments for `plot {subcommand}`: {', '.join(missing)}",
            f"plot {subcommand} --data <csv-file> --x <column> --y <column> [--title <text>] [--output <png>] [--theme minerva-classic|bloomberg]",
            ["`plot bar --data revenue.csv --x year --y revenue`", "`plot wordcloud --file notes.txt`"],
            PLOT_HELP,
        ),
        exit_code=1,
    )
def _usage_error(what: str, what_to_do: str, alternatives: list[str], help_text: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {what}",
            f"What to do instead: {what_to_do}",
            f"Available alternatives: {', '.join(alternatives)}",
            "",
            help_text.rstrip(),
        ]
    )
def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
