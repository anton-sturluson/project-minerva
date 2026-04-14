"""Morning brief evidence collection commands."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from harness.commands.common import elapsed_ms, error_result, parse_flag_args
from harness.commands.sec import _configure_edgar
from harness.config import HarnessSettings, get_settings
from harness.morning_brief import (
    append_review_log,
    audit_evidence,
    collect_earnings,
    collect_filings,
    collect_ir,
    collect_macro,
    collect_macro_registry_events,
    collect_market,
    prepare_evidence,
)
from harness.output import CommandResult, OutputEnvelope
from harness.portfolio_state import parse_iso_date

BRIEF_HELP = (
    "Morning brief evidence collection commands.\n\n"
    "Examples:\n"
    "  minerva brief filings --date 2026-04-08\n"
    "  minerva brief macro-collect --date 2026-04-08\n"
    "  minerva brief earnings --date 2026-04-08 --source ./market-data.json\n"
    "  minerva brief prep --date 2026-04-08\n"
)

app = typer.Typer(help=BRIEF_HELP, no_args_is_help=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch brief commands for `minerva run`."""
    _ = stdin
    active_settings = settings or get_settings()
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `brief` subcommand was provided"), exit_code=1)

    subcommand = args[0]
    try:
        if subcommand == "filings":
            parsed = parse_flag_args(args[1:])
            return filings_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                source=str(parsed["source"]) if "source" in parsed else None,
                since=parse_iso_date(str(parsed["since"])) if "since" in parsed else None,
                until=parse_iso_date(str(parsed["until"])) if "until" in parsed else None,
                forms=_split_csv(str(parsed.get("forms", ""))) or None,
                limit_per_company=int(parsed.get("limit-per-company", 10)),
                settings=active_settings,
            )
        if subcommand == "earnings":
            parsed = parse_flag_args(args[1:])
            return earnings_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                source=str(parsed["source"]) if "source" in parsed else None,
                provider=str(parsed.get("provider", "auto")),
                settings=active_settings,
            )
        if subcommand == "macro":
            parsed = parse_flag_args(args[1:])
            return macro_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                source=str(parsed["source"]) if "source" in parsed else None,
                registry=str(parsed["registry"]) if "registry" in parsed else None,
                settings=active_settings,
            )
        if subcommand == "macro-collect":
            parsed = parse_flag_args(args[1:])
            return macro_collect_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                registry=str(parsed["registry"]) if "registry" in parsed else None,
                output=str(parsed["output"]) if "output" in parsed else None,
                settings=active_settings,
            )
        if subcommand == "ir":
            parsed = parse_flag_args(args[1:])
            return ir_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                registry=str(parsed["registry"]) if "registry" in parsed else None,
                settings=active_settings,
            )
        if subcommand == "market":
            parsed = parse_flag_args(args[1:])
            return market_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                source=str(parsed["source"]) if "source" in parsed else None,
                provider=str(parsed.get("provider", "auto")),
                settings=active_settings,
            )
        if subcommand == "prep":
            parsed = parse_flag_args(args[1:])
            return prep_command(run_date=parse_iso_date(str(parsed.get("date") or "")), settings=active_settings)
        if subcommand == "audit":
            parsed = parse_flag_args(args[1:])
            return audit_command(run_date=parse_iso_date(str(parsed.get("date") or "")), settings=active_settings)
        if subcommand == "review-log":
            parsed = parse_flag_args(args[1:])
            return review_log_command(
                run_date=parse_iso_date(str(parsed.get("date") or "")),
                notes=str(parsed.get("notes", "")),
                settings=active_settings,
            )
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text("", stderr=_usage_error(f"unknown `brief` subcommand `{subcommand}`"), exit_code=1)


def filings_command(
    *,
    run_date,
    source: str | None,
    since,
    until,
    forms: list[str] | None,
    limit_per_company: int,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Collect monitored SEC filings for the run window."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    if not source:
        identity_error = _configure_edgar(active_settings)
        if identity_error:
            return error_result(
                identity_error,
                "set EDGAR_IDENTITY or pass `--source` for a local filings payload",
                ["`export EDGAR_IDENTITY='Minerva Research name@email.com'`", "`brief filings --date 2026-04-08 --source ./filings.json`"],
                start,
            )
    try:
        summary = collect_filings(
            active_settings.ensure_workspace_root(),
            run_date=run_date,
            source=source,
            since=since,
            until=until,
            forms=forms,
            limit_per_company=limit_per_company,
        )
    except Exception as exc:
        return error_result(
            f"failed to collect filings: {exc}",
            "verify the portfolio universe and SEC identity, then retry",
            ["`portfolio sync --holdings-source ./holdings.csv --transactions-source ./transactions.csv`", "`brief filings --date 2026-04-08`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def earnings_command(
    *,
    run_date,
    source: str | None,
    provider: str,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Collect earnings metadata."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = collect_earnings(
            active_settings.ensure_workspace_root(),
            run_date=run_date,
            source=source,
            provider=provider,
            finnhub_api_key=active_settings.finnhub_api_key,
        )
    except Exception as exc:
        return error_result(
            f"failed to collect earnings: {exc}",
            "provide a source file or configure market data credentials",
            ["`brief earnings --date 2026-04-08 --source ./market-data.json`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def macro_command(
    *,
    run_date,
    source: str | None,
    registry: str | None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Collect macro schedule evidence."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = collect_macro(
            active_settings.ensure_workspace_root(),
            run_date=run_date,
            source=source,
            registry_path=Path(registry) if registry else None,
        )
    except Exception as exc:
        return error_result(
            f"failed to collect macro events: {exc}",
            "provide a macro events source or run `brief macro-collect` against the local registry",
            ["`brief macro-collect --date 2026-04-08`", "`brief macro --date 2026-04-08 --source ./macro-events.json`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def macro_collect_command(
    *,
    run_date,
    registry: str | None,
    output: str | None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Build a deterministic macro-events payload from the configured registry."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = collect_macro_registry_events(
            active_settings.ensure_workspace_root(),
            run_date=run_date,
            registry_path=Path(registry) if registry else None,
            output_path=Path(output) if output else None,
        )
    except Exception as exc:
        return error_result(
            f"failed to build macro events source: {exc}",
            "verify the macro registry entries and output path, then retry",
            ["`brief macro-collect --date 2026-04-08`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def ir_command(
    *,
    run_date,
    registry: str | None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Collect IR releases from configured feeds."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = collect_ir(
            active_settings.ensure_workspace_root(),
            run_date=run_date,
            registry_path=Path(registry) if registry else None,
        )
    except Exception as exc:
        return error_result(
            f"failed to collect IR releases: {exc}",
            "update `ir-registry.json` or pass an alternate registry file",
            ["`brief ir --date 2026-04-08`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def market_command(
    *,
    run_date,
    source: str | None,
    provider: str,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Collect narrow market context evidence."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = collect_market(
            active_settings.ensure_workspace_root(),
            run_date=run_date,
            source=source,
            provider=provider,
            finnhub_api_key=active_settings.finnhub_api_key,
        )
    except Exception as exc:
        return error_result(
            f"failed to collect market context: {exc}",
            "provide a market source file or configure market data credentials",
            ["`brief market --date 2026-04-08 --source ./market-data.json`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def prep_command(*, run_date, settings: HarnessSettings | None = None) -> CommandResult:
    """Prepare agent-ready evidence from collected sources."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = prepare_evidence(active_settings.ensure_workspace_root(), run_date=run_date)
    except Exception as exc:
        return error_result(
            f"failed to prepare evidence: {exc}",
            "run the collection commands first, then retry",
            ["`brief filings --date 2026-04-08`", "`brief prep --date 2026-04-08`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def audit_command(*, run_date, settings: HarnessSettings | None = None) -> CommandResult:
    """Run a bounded audit of the prepared evidence."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = audit_evidence(active_settings.ensure_workspace_root(), run_date=run_date)
    except Exception as exc:
        return error_result(
            f"failed to audit evidence: {exc}",
            "run `brief prep` first, then retry",
            ["`brief prep --date 2026-04-08`", "`brief audit --date 2026-04-08`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


def review_log_command(*, run_date, notes: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Append one review-log entry for the run."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = append_review_log(active_settings.ensure_workspace_root(), run_date=run_date, notes=notes)
    except Exception as exc:
        return error_result(
            f"failed to append the review log: {exc}",
            "run `brief audit` first, then retry",
            ["`brief review-log --date 2026-04-08 --notes '...'`"],
            start,
        )
    return CommandResult.from_text(_summary_lines(summary), duration_ms=elapsed_ms(start))


@app.command("filings", help="Collect overnight SEC filings for the monitored universe.")
def filings_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    source: str | None = typer.Option(None, "--source", help="Fixture-backed filings payload file."),
    since: str | None = typer.Option(None, "--since", help="Window start date."),
    until: str | None = typer.Option(None, "--until", help="Window end date."),
    forms: str = typer.Option("", "--forms", help="Comma-separated filing forms."),
    limit_per_company: int = typer.Option(10, "--limit-per-company", min=1, help="Max filings per company."),
) -> None:
    _print(
        filings_command(
            run_date=parse_iso_date(date_arg),
            source=source,
            since=parse_iso_date(since) if since else None,
            until=parse_iso_date(until) if until else None,
            forms=_split_csv(forms) or None,
            limit_per_company=limit_per_company,
        )
    )


@app.command("earnings", help="Collect reported and upcoming earnings metadata.")
def earnings_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    source: str | None = typer.Option(None, "--source", help="Shared market data source file."),
    provider: str = typer.Option("auto", "--provider", help="Provider mode: auto, file, or finnhub."),
) -> None:
    _print(earnings_command(run_date=parse_iso_date(date_arg), source=source, provider=provider))


@app.command("macro", help="Collect the run-date macro and policy calendar.")
def macro_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    source: str | None = typer.Option(None, "--source", help="Macro events source file."),
    registry: str | None = typer.Option(None, "--registry", help="Optional macro registry path."),
) -> None:
    _print(macro_command(run_date=parse_iso_date(date_arg), source=source, registry=registry))


@app.command("macro-collect", help="Build a normalized macro-events source from the local registry.")
def macro_collect_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    registry: str | None = typer.Option(None, "--registry", help="Optional macro registry path."),
    output: str | None = typer.Option(None, "--output", help="Output file for the generated macro events payload."),
) -> None:
    _print(macro_collect_command(run_date=parse_iso_date(date_arg), registry=registry, output=output))


@app.command("ir", help="Scan configured IR feeds for overnight releases.")
def ir_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    registry: str | None = typer.Option(None, "--registry", help="Optional IR registry path."),
) -> None:
    _print(ir_command(run_date=parse_iso_date(date_arg), registry=registry))


@app.command("market", help="Collect narrow market context that materially matters.")
def market_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    source: str | None = typer.Option(None, "--source", help="Shared market data source file."),
    provider: str = typer.Option("auto", "--provider", help="Provider mode: auto, file, or finnhub."),
) -> None:
    _print(market_command(run_date=parse_iso_date(date_arg), source=source, provider=provider))


@app.command("prep", help="Prepare the agent-ready evidence pack.")
def prep_cli(date_arg: str | None = typer.Option(None, "--date", help="Run date.")) -> None:
    _print(prep_command(run_date=parse_iso_date(date_arg)))


@app.command("audit", help="Run a bounded miss-check after prep.")
def audit_cli(date_arg: str | None = typer.Option(None, "--date", help="Run date.")) -> None:
    _print(audit_command(run_date=parse_iso_date(date_arg)))


@app.command("review-log", help="Append a structured review-log entry.")
def review_log_cli(
    date_arg: str | None = typer.Option(None, "--date", help="Run date."),
    notes: str = typer.Option("", "--notes", help="Optional operator notes."),
) -> None:
    _print(review_log_command(run_date=parse_iso_date(date_arg), notes=notes))


def _usage_error(message: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {message}",
            "What to do instead: use one of the supported brief commands",
            "Available alternatives: `brief filings`, `brief macro-collect`, `brief prep`, `brief review-log --notes ...`",
            "",
            BRIEF_HELP.rstrip(),
        ]
    )


def _summary_lines(summary: dict[str, object]) -> str:
    return "\n".join(f"{key}: {summary[key]}" for key in sorted(summary))


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
