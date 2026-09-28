"""HF Best Ideas weekly fetch, extraction, and summary commands."""

from __future__ import annotations

import time
from importlib import resources
from pathlib import Path
from typing import Any

import typer

from harness.commands.common import elapsed_ms, error_result, resolve_path
from harness.config import HarnessSettings, get_settings
from harness.hf_ideas import (
    FetchResult,
    PipelineError,
    build_report,
    fetch_latest_issue,
    write_failure_marker,
)
from harness.output import CommandResult, OutputEnvelope

DEFAULT_OUTPUT_ROOT = "hard-disk/reports/05-weekly-ideas"
IDEAS_HELP = (
    "Fetch and validate the weekly HF Best Ideas roster.\n\n"
    "Examples:\n"
    "  minerva ideas weekly\n"
    "  minerva ideas weekly --dry-run\n"
    "  minerva ideas fetch --sleep 0.5\n"
    "  minerva ideas build hard-disk/reports/05-weekly-ideas/2026-09-21\n"
)

app = typer.Typer(help=IDEAS_HELP, no_args_is_help=True)


def dispatch(
    args: list[str], settings: HarnessSettings, stdin: bytes = b""
) -> CommandResult:
    """Dispatch ideas commands for `minerva run`."""
    del stdin
    if not args:
        return CommandResult.from_text(
            "", stderr=_usage_error("no `ideas` subcommand was provided"), exit_code=1
        )

    subcommand = args[0]
    try:
        if subcommand in {"weekly", "fetch"}:
            parsed = _parse_fetch_args(args[1:])
            command = weekly_command if subcommand == "weekly" else fetch_command
            return command(
                dry_run=parsed["dry_run"],
                sleep_seconds=parsed["sleep_seconds"],
                out=parsed["out"],
                settings=settings,
            )
        if subcommand == "build":
            if len(args) != 2 or args[1].startswith("-"):
                raise ValueError("`ideas build` requires exactly one output-directory path")
            return build_command(path=args[1], settings=settings)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text(
        "",
        stderr=_usage_error(f"unknown `ideas` subcommand `{subcommand}`"),
        exit_code=1,
    )


def fetch_command(
    *,
    dry_run: bool,
    sleep_seconds: float,
    out: str,
    settings: HarnessSettings,
) -> CommandResult:
    """Fetch and archive the latest weekly issue without running extraction."""
    start = time.perf_counter()
    progress: list[str] = []
    try:
        result = fetch_latest_issue(
            _output_root(out),
            dry_run=dry_run,
            sleep_seconds=sleep_seconds,
            progress=progress.append,
        )
    except (PipelineError, OSError, KeyError, TypeError) as exc:
        return error_result(
            f"weekly ideas fetch failed: {exc}",
            "verify network access and the source roster, then retry",
            ["`minerva ideas fetch --dry-run`", "`minerva ideas weekly --dry-run`"],
            start,
            help_text=IDEAS_HELP,
        )

    progress.extend(_fetch_summary(result, dry_run=dry_run))
    return CommandResult.from_text("\n".join(progress), duration_ms=elapsed_ms(start))


def build_command(
    *, path: str | Path, settings: HarnessSettings
) -> CommandResult:
    """Validate existing weekly extractions and build the summary and indices."""
    start = time.perf_counter()
    folder = resolve_path(path)
    try:
        coverage = build_report(folder)
    except (PipelineError, OSError, KeyError, TypeError) as exc:
        message = str(exc)
        write_failure_marker(folder, message)
        return error_result(
            f"weekly ideas coverage validation failed: {message}",
            "fix or rerun the extraction before rebuilding the report",
            [
                f"`minerva ideas build {folder}`",
                "`minerva ideas weekly`",
            ],
            start,
            help_text=IDEAS_HELP,
        )

    return CommandResult.from_text(
        _coverage_summary(coverage, folder), duration_ms=elapsed_ms(start)
    )


def weekly_command(
    *,
    dry_run: bool,
    sleep_seconds: float,
    out: str,
    settings: HarnessSettings,
) -> CommandResult:
    """Run fetch, in-process extraction dispatch, and strict report building."""
    start = time.perf_counter()
    progress: list[str] = []
    folder: Path | None = None
    try:
        fetched = fetch_latest_issue(
            _output_root(out),
            dry_run=dry_run,
            sleep_seconds=sleep_seconds,
            progress=progress.append,
        )
        folder = fetched.output_dir
    except (PipelineError, OSError, KeyError, TypeError) as exc:
        return error_result(
            f"weekly ideas fetch failed: {exc}",
            "verify network access and the source roster, then retry",
            ["`minerva ideas weekly --dry-run`", "`minerva ideas fetch --dry-run`"],
            start,
            help_text=IDEAS_HELP,
        )

    if dry_run:
        progress.extend(_fetch_summary(fetched, dry_run=True))
        return CommandResult.from_text(
            "\n".join(progress), duration_ms=elapsed_ms(start)
        )

    progress.extend(_fetch_summary(fetched, dry_run=False))
    progress.append("→ extracting all company inputs in-process")
    extraction_result = _dispatch_extraction(folder, settings)
    if extraction_result.stdout:
        progress.append(extraction_result.stdout.decode("utf-8", errors="replace").strip())
    if extraction_result.exit_code:
        detail = extraction_result.stderr.decode("utf-8", errors="replace").strip()
        detail = detail or f"extract-files returned exit code {extraction_result.exit_code}"
        write_failure_marker(folder, f"extraction stage: {detail}")
        return CommandResult.from_text(
            "\n".join(line for line in progress if line),
            stderr=f"weekly ideas extraction failed: {detail}",
            exit_code=extraction_result.exit_code,
            duration_ms=elapsed_ms(start),
        )

    progress.append("→ validating coverage and building summary")
    try:
        coverage = build_report(folder)
    except (PipelineError, OSError, KeyError, TypeError) as exc:
        message = str(exc)
        write_failure_marker(folder, message)
        return error_result(
            f"weekly ideas coverage validation failed: {message}",
            "fix or rerun the extraction before rebuilding the report",
            [f"`minerva ideas build {folder}`", "`minerva ideas weekly`"],
            start,
            help_text=IDEAS_HELP,
        )

    progress.append(_coverage_summary(coverage, folder))
    return CommandResult.from_text("\n".join(progress), duration_ms=elapsed_ms(start))


@app.command("weekly", help="Run fetch, extraction, and validated summary stages.")
def weekly_cli(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and list the roster without writing, fetching stock pages, extracting, or building.",
    ),
    sleep_seconds: float = typer.Option(
        1.0,
        "--sleep",
        min=0.0,
        help="Delay in seconds between public stock-page requests.",
    ),
    out: str = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--out",
        help="Parent directory for dated weekly issue folders.",
    ),
) -> None:
    _print(
        weekly_command(
            dry_run=dry_run,
            sleep_seconds=sleep_seconds,
            out=out,
            settings=get_settings(),
        )
    )


@app.command("fetch", help="Fetch and archive the latest issue without extraction.")
def fetch_cli(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and list the roster without writing or fetching stock pages.",
    ),
    sleep_seconds: float = typer.Option(
        1.0,
        "--sleep",
        min=0.0,
        help="Delay in seconds between public stock-page requests.",
    ),
    out: str = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--out",
        help="Parent directory for dated weekly issue folders.",
    ),
) -> None:
    _print(
        fetch_command(
            dry_run=dry_run,
            sleep_seconds=sleep_seconds,
            out=out,
            settings=get_settings(),
        )
    )


@app.command("build", help="Validate extractions and build a summary for one issue folder.")
def build_cli(
    path: Path = typer.Argument(..., help="Existing dated weekly issue folder."),
) -> None:
    _print(build_command(path=path, settings=get_settings()))


def _dispatch_extraction(folder: Path, settings: HarnessSettings) -> CommandResult:
    """Call the registered extract-files dispatcher without spawning a subprocess."""
    from harness.cli import dispatch_command

    prompt = resources.files("harness.prompts").joinpath("hf_ideas_questions.md")
    with resources.as_file(prompt) as prompt_path:
        return dispatch_command(
            [
                "extract-files",
                "--questions-file",
                str(prompt_path),
                "--files-from",
                str(folder / "extraction-files.txt"),
                "--out",
                str(folder / "extractions"),
                "--concurrency",
                "3",
                "--force",
            ],
            settings=settings,
        )


def _output_root(out: str) -> Path:
    return resolve_path(out)


def _fetch_summary(result: FetchResult, *, dry_run: bool) -> list[str]:
    lines: list[str] = []
    if dry_run:
        for group in result.groups:
            symbol = " ".join(
                part for part in [group["ticker"], group["exchange"]] if part
            ) or "—"
            funds = "; ".join(
                entry["fund"] for entry in group["roster_entries"]
            )
            lines.append(f"   {group['company_id']:<50} {symbol:<12} {funds}")
        lines.append(f"✓ dry run complete: {result.output_dir}")
        return lines

    manifest = result.manifest or {}
    public_sources = manifest.get("public_sources", {})
    fetched_count = sum(
        source.get("status") == "fetched" for source in public_sources.values()
    )
    lines.append(
        f"✓ archived issue and {len(result.groups)} extraction inputs "
        f"({fetched_count} validated public pages; "
        f"{len(result.groups) - fetched_count} individually explained gaps)"
    )
    lines.append(f"output_dir: {result.output_dir}")
    return lines


def _coverage_summary(coverage: dict[str, Any], folder: Path) -> str:
    warnings = coverage.get("warnings", [])
    lines = [
        "✓ summary.md + indices: "
        f"{coverage['roster_validated']}/{coverage['roster_expected']} roster entries, "
        f"{coverage['companies_validated']}/{coverage['companies_expected']} companies",
        f"✓ coverage.json ({coverage['gap_count']} explicit source gaps; {len(warnings)} warnings)",
    ]
    for warning in warnings[:5]:
        lines.append(f"  warning: {warning}")
    if len(warnings) > 5:
        lines.append(f"  ... {len(warnings) - 5} more warning(s) in coverage.json")
    lines.append(f"output_dir: {folder}")
    return "\n".join(lines)


def _parse_fetch_args(args: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "dry_run": False,
        "sleep_seconds": 1.0,
        "out": DEFAULT_OUTPUT_ROOT,
    }
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--dry-run":
            parsed["dry_run"] = True
            index += 1
            continue
        if token in {"--sleep", "--out"}:
            if index + 1 >= len(args):
                raise ValueError(f"missing value for `{token}`")
            value = args[index + 1]
            if token == "--sleep":
                parsed["sleep_seconds"] = float(value)
                if parsed["sleep_seconds"] < 0:
                    raise ValueError("`--sleep` must be non-negative")
            else:
                parsed["out"] = value
            index += 2
            continue
        raise ValueError(f"unknown argument for `ideas`: `{token}`")
    return parsed


def _usage_error(message: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {message}",
            "What to do instead: use one of the supported ideas commands",
            "Available alternatives: `ideas weekly`, `ideas fetch`, `ideas build PATH`",
            "",
            IDEAS_HELP.rstrip(),
        ]
    )


def _print(result: CommandResult) -> None:
    settings = get_settings()
    envelope = OutputEnvelope.from_result(
        result, workspace_root=settings.resolved_workspace_root
    )
    typer.echo(envelope.render())
    if result.exit_code:
        raise typer.Exit(result.exit_code)
