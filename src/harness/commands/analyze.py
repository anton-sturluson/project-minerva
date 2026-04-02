"""Text analysis commands."""

from __future__ import annotations

import time

import typer

from harness.commands.common import elapsed_ms, error_result
from harness.commands.fs import resolve_workspace_path
from harness.config import HarnessSettings, get_settings
from harness.delegate import extract_text_from_path
from harness.output import CommandResult, OutputEnvelope
from minerva.formatting import build_markdown_table, format_pct
from minerva.text_analysis import (
    KeywordGroup,
    compute_keyword_density,
    count_keyword_groups,
    score_sentiment,
)

DEFAULT_GROUPS: dict[str, list[str]] = {
    "growth": ["growth", "expand", "expansion", "accelerate", "momentum", "demand", "opportunity"],
    "risk": ["risk", "challenge", "uncertain", "litigation", "regulatory", "downside", "volatility"],
    "competition": ["competition", "competitive", "rival", "pricing", "market share", "differentiated"],
}

app = typer.Typer(help="Analysis commands.", no_args_is_help=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None) -> CommandResult:
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "analyze",
            "Usage: analyze <sentiment|keywords> ...",
            ["analyze sentiment <file>", "analyze keywords <file> --groups growth,risk"],
        )

    subcommand: str = args[0]
    if subcommand == "sentiment":
        if len(args) != 2:
            return _usage_error("analyze sentiment", "Usage: analyze sentiment <file>", ["analyze keywords <file> --groups growth"])
        return analyze_sentiment(args[1], settings=active_settings)
    if subcommand == "keywords":
        if len(args) != 4 or args[2] != "--groups":
            return _usage_error(
                "analyze keywords",
                "Usage: analyze keywords <file> --groups growth,risk,competition",
                ["analyze sentiment <file>"],
            )
        return analyze_keywords(args[1], args[3], settings=active_settings)
    return _usage_error("analyze", f"Unknown analyze subcommand: {subcommand}", ["analyze sentiment <file>"])


def analyze_sentiment(path: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target = resolve_workspace_path(path, active_settings)
        text: str = extract_text_from_path(target)
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to read {path}: {exc}\n"
            "What to do instead: use a readable workspace file, then retry.\n"
            "Available alternatives: `stat <file>`, `cat <file>`",
            start,
        )

    paragraphs: list[str] = [part.strip() for part in text.split("\n\n") if part.strip()]
    result = score_sentiment(paragraphs)
    lines: list[str] = [
        f"paragraph_count: {result.paragraph_count}",
        f"confidence_count: {result.confidence_count}",
        f"uncertainty_count: {result.uncertainty_count}",
        f"net_score: {result.net_score:.3f}",
    ]
    return CommandResult.from_text("\n".join(lines), duration_ms=elapsed_ms(start))


def analyze_keywords(path: str, group_names_csv: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target = resolve_workspace_path(path, active_settings)
        text: str = extract_text_from_path(target)
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to read {path}: {exc}\n"
            "What to do instead: use a readable workspace file, then retry.\n"
            "Available alternatives: `stat <file>`, `cat <file>`",
            start,
        )

    requested_names: list[str] = [name.strip().lower() for name in group_names_csv.split(",") if name.strip()]
    unknown: list[str] = [name for name in requested_names if name not in DEFAULT_GROUPS]
    if unknown:
        return error_result(
            f"What went wrong: unknown keyword groups: {', '.join(unknown)}\n"
            f"What to do instead: choose from {', '.join(sorted(DEFAULT_GROUPS))}.\n"
            "Available alternatives: `analyze sentiment <file>`, `analyze keywords <file> --groups growth,risk`",
            start,
        )

    groups: list[KeywordGroup] = [KeywordGroup(name=name, keywords=DEFAULT_GROUPS[name]) for name in requested_names]
    counts: dict[str, int] = count_keyword_groups(text, groups)
    densities: dict[str, float] = compute_keyword_density(text, groups)
    rows: list[list[str]] = []
    for group in groups:
        rows.append([
            group.name,
            str(counts[group.name]),
            format_pct(densities[group.name] / 100, decimals=2),
            f"{densities[group.name]:.2f}",
        ])
    table: str = build_markdown_table(
        ["group", "count", "density_pct", "mentions_per_10k_words"],
        rows,
        alignment=["l", "r", "r", "r"],
    )
    return CommandResult.from_text(table, duration_ms=elapsed_ms(start))


@app.command("sentiment")
def sentiment_command(path: str = typer.Argument(..., help="Workspace-relative file path.")) -> None:
    """Score confidence versus uncertainty language."""
    _print(analyze_sentiment(path))


@app.command("keywords")
def keywords_command(
    path: str = typer.Argument(..., help="Workspace-relative file path."),
    groups: str = typer.Option(..., "--groups", help="Comma-separated keyword group names."),
) -> None:
    """Compute keyword density for default analysis groups."""
    _print(analyze_keywords(path, groups))


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
