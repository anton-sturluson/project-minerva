"""Evidence workflow commands."""

from __future__ import annotations

import time

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, parse_flag_args
from harness.commands.extract import DEFAULT_MODEL
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from harness.workflows.evidence.collector import collect_sec_sources
from harness.workflows.evidence.coverage import run_coverage
from harness.workflows.evidence.extraction import run_extraction
from harness.workflows.evidence.inventory import run_inventory
from harness.workflows.evidence.paths import resolve_company_root
from harness.workflows.evidence.registry import (
    SOURCE_STATUSES,
    initialize_registry,
    normalize_local_path,
    upsert_source,
)

EVIDENCE_HELP = (
    "Evidence collection and workflow state commands.\n\n"
    "Examples:\n"
    "  minerva evidence init --root hard-disk/reports/00-companies/12-robinhood --ticker HOOD --name Robinhood --slug robinhood\n"
    "  minerva evidence collect sec --root hard-disk/reports/00-companies/12-robinhood --ticker HOOD --annual 3 --quarters 4\n"
    "  minerva evidence extract --root hard-disk/reports/00-companies/12-robinhood --profile default\n"
)

COLLECT_HELP = "Collect workflow-aware evidence sources."

app = typer.Typer(help=EVIDENCE_HELP, no_args_is_help=True)
collect_app = typer.Typer(help=COLLECT_HELP, no_args_is_help=True)
app.add_typer(collect_app, name="collect")


def dispatch(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch evidence commands for `minerva run`."""
    _ = stdin
    active_settings = settings or get_settings()
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `evidence` subcommand was provided", "choose an evidence workflow command", ["`evidence init --root ... --ticker AAPL --name Apple --slug apple`", "`evidence inventory --root ...`"], EVIDENCE_HELP), exit_code=1)

    subcommand = args[0]
    try:
        if subcommand == "init":
            parsed = parse_flag_args(args[1:])
            return init_command(
                root=str(parsed["root"]),
                ticker=str(parsed["ticker"]),
                company_name=str(parsed["name"]),
                slug=str(parsed["slug"]),
            )
        if subcommand == "collect":
            if len(args) < 2 or args[1] != "sec":
                return _collect_usage_result()
            parsed = parse_flag_args(args[2:], allow_flags_without_values={"financials", "no-financials", "html", "no-html"})
            include_financials = True
            include_html = True
            if "no-financials" in parsed:
                include_financials = False
            elif "financials" in parsed:
                include_financials = True
            if "no-html" in parsed:
                include_html = False
            elif "html" in parsed:
                include_html = True
            return collect_sec_command(
                root=str(parsed["root"]),
                ticker=str(parsed["ticker"]),
                annual=int(parsed.get("annual", 5)),
                quarters=int(parsed.get("quarters", 4)),
                earnings=int(parsed.get("earnings", 4)),
                include_financials=include_financials,
                include_html=include_html,
                settings=active_settings,
            )
        if subcommand == "register":
            parsed = parse_flag_args(args[1:])
            return register_command(
                root=str(parsed["root"]),
                status=str(parsed["status"]),
                bucket=str(parsed["bucket"]),
                source_kind=str(parsed["source-kind"]),
                title=str(parsed["title"]),
                path=str(parsed["path"]) if "path" in parsed else None,
                url=str(parsed["url"]) if "url" in parsed else None,
                notes=str(parsed["notes"]) if "notes" in parsed else None,
            )
        if subcommand == "inventory":
            parsed = parse_flag_args(args[1:], allow_flags_without_values={"write-index", "no-write-index"})
            write_index = "no-write-index" not in parsed
            return inventory_command(root=str(parsed["root"]), write_index=write_index)
        if subcommand == "extract":
            parsed = parse_flag_args(args[1:], allow_flags_without_values={"force"})
            return extract_command(
                root=str(parsed["root"]),
                profile=str(parsed.get("profile", "default")),
                source_prefix=str(parsed["source-prefix"]) if "source-prefix" in parsed else None,
                match=str(parsed["match"]) if "match" in parsed else None,
                force=bool(parsed.get("force", False)),
                model=str(parsed.get("model", DEFAULT_MODEL)),
                settings=active_settings,
            )
        if subcommand == "coverage":
            parsed = parse_flag_args(args[1:])
            return coverage_command(root=str(parsed["root"]), profile=str(parsed.get("profile", "default")))
    except KeyError as exc:
        return CommandResult.from_text("", stderr=f"missing required flag: {exc}", exit_code=1)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text("", stderr=_usage_error(f"unknown `evidence` subcommand `{subcommand}`", "choose an evidence workflow command", ["`evidence init --root ... --ticker AAPL --name Apple --slug apple`", "`evidence inventory --root ...`"], EVIDENCE_HELP), exit_code=1)


def init_command(*, root: str, ticker: str, company_name: str, slug: str) -> CommandResult:
    """Initialize the canonical company evidence tree."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        initialize_registry(paths, ticker=ticker, company_name=company_name, slug=slug)
    except Exception as exc:
        return error_result(
            f"failed to initialize evidence tree: {exc}",
            "verify the root path and company metadata, then retry",
            ["`minerva evidence init --root ... --ticker AAPL --name Apple --slug apple`"],
            start,
        )
    body = "\n".join(
        [
            f"initialized_root: {paths.root}",
            f"source_registry: {paths.source_registry_json.relative_to(paths.root)}",
            f"analysis_dir: {paths.analysis_dir.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def collect_sec_command(
    *,
    root: str,
    ticker: str,
    annual: int,
    quarters: int,
    earnings: int,
    include_financials: bool,
    include_html: bool,
    settings: HarnessSettings,
) -> CommandResult:
    """Collect SEC materials into the evidence tree."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        summary = collect_sec_sources(
            paths,
            ticker=ticker,
            annual=annual,
            quarters=quarters,
            earnings=earnings,
            include_financials=include_financials,
            include_html=include_html,
            settings=settings,
        )
    except Exception as exc:
        return error_result(
            f"SEC evidence collection failed: {exc}",
            "verify the root path, ticker, EDGAR identity, and filing counts, then retry",
            ["`minerva evidence collect sec --root ... --ticker AAPL`", "`minerva evidence init --root ... --ticker AAPL --name Apple --slug apple`"],
            start,
        )
    body = "\n".join(
        [
            f"collected_count: {summary['collected_count']}",
            f"summary_json: {paths.sec_collection_summary_json.relative_to(paths.root)}",
            f"inventory_json: {paths.inventory_json.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def register_command(
    *,
    root: str,
    status: str,
    bucket: str,
    source_kind: str,
    title: str,
    path: str | None,
    url: str | None,
    notes: str | None,
) -> CommandResult:
    """Register an external, discovered, or blocked source."""
    start = time.perf_counter()
    if status not in SOURCE_STATUSES:
        return error_result(
            f"`--status` must be one of {', '.join(sorted(SOURCE_STATUSES))}",
            "retry with a supported status",
            ["`minerva evidence register --root ... --status discovered --bucket external-research --source-kind expert-call --title 'Channel check' --url https://...`"],
            start,
        )
    if status == "downloaded" and not path:
        return error_result(
            "downloaded sources require `--path`",
            "pass a local file path for downloaded sources",
            ["`minerva evidence register --root ... --status downloaded --bucket external-research --source-kind industry-report --title 'Market report' --path ./report.pdf`"],
            start,
        )
    try:
        paths = resolve_company_root(root)
        normalized_path = normalize_local_path(paths, path) if path else None
        ticker = _ticker_from_root(paths)
        entry = upsert_source(
            paths,
            ticker=ticker,
            bucket=bucket,
            source_kind=source_kind,
            status=status,
            title=title,
            local_path=normalized_path,
            url=url,
            notes=notes,
        )
    except Exception as exc:
        return error_result(
            f"failed to register source: {exc}",
            "verify the registry root, bucket, and source metadata, then retry",
            ["`minerva evidence register --root ... --status discovered --bucket external-research --source-kind industry-report --title 'Market report' --url https://...`"],
            start,
        )
    body = "\n".join(
        [
            f"registered_source_id: {entry['id']}",
            f"status: {entry['status']}",
            f"source_registry: {paths.source_registry_json.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def inventory_command(*, root: str, write_index: bool) -> CommandResult:
    """Recompute the evidence inventory."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        inventory = run_inventory(paths, write_index=write_index)
    except Exception as exc:
        return error_result(
            f"failed to compute inventory: {exc}",
            "verify the root path and retry",
            ["`minerva evidence inventory --root ...`"],
            start,
        )
    body = "\n".join(
        [
            f"downloaded: {inventory['counts']['downloaded']}",
            f"downloaded_missing_on_disk: {inventory['counts']['downloaded_missing_on_disk']}",
            f"inventory_json: {paths.inventory_json.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def extract_command(
    *,
    root: str,
    profile: str,
    source_prefix: str | None,
    match: str | None,
    force: bool,
    model: str,
    settings: HarnessSettings,
) -> CommandResult:
    """Run extraction over downloaded sources."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        run = run_extraction(
            paths,
            profile_name=profile,
            source_prefix=source_prefix,
            match=match,
            force=force,
            model=model,
            settings=settings,
        )
    except Exception as exc:
        return error_result(
            f"evidence extraction failed: {exc}",
            "verify the profile, filters, local source files, and Gemini configuration, then retry",
            ["`minerva evidence extract --root ... --profile default`"],
            start,
        )
    body = "\n".join(
        [
            f"matched_count: {run['matched_count']}",
            f"processed_count: {run['processed_count']}",
            f"skipped_existing_count: {run['skipped_existing_count']}",
            f"extraction_runs_dir: {paths.extraction_runs_dir.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def coverage_command(*, root: str, profile: str) -> CommandResult:
    """Compute coverage against a workflow profile."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        coverage = run_coverage(paths, profile_name=profile)
    except Exception as exc:
        return error_result(
            f"failed to compute evidence coverage: {exc}",
            "verify the root path and coverage profile, then retry",
            ["`minerva evidence coverage --root ... --profile default`"],
            start,
        )
    body = "\n".join(
        [
            f"ready_for_analysis: {coverage['ready_for_analysis']}",
            f"coverage_json: {paths.coverage_json.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


@app.command("init", help="Create or reuse the standard company evidence tree.")
def init_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    ticker: str | None = typer.Option(None, "--ticker", help="Company ticker."),
    company_name: str | None = typer.Option(None, "--name", help="Company name."),
    slug: str | None = typer.Option(None, "--slug", help="Company slug."),
) -> None:
    if not all([root, ticker, company_name, slug]):
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence init`",
            what_to_do="pass `--root`, `--ticker`, `--name`, and `--slug`",
            alternatives=["`minerva evidence init --root hard-disk/reports/00-companies/12-robinhood --ticker HOOD --name Robinhood --slug robinhood`"],
        )
    _print(init_command(root=root, ticker=ticker, company_name=company_name, slug=slug))


@collect_app.command("sec", help="Collect SEC sources into the workflow tree.")
def collect_sec_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    ticker: str | None = typer.Option(None, "--ticker", help="Company ticker."),
    annual: int = typer.Option(5, "--annual", min=0, help="Number of 10-K filings."),
    quarters: int = typer.Option(4, "--quarters", min=0, help="Number of 10-Q filings."),
    earnings: int = typer.Option(4, "--earnings", min=0, help="Number of earnings releases."),
    financials: bool = typer.Option(True, "--financials/--no-financials", help="Include financial statement markdown and CSV."),
    html: bool = typer.Option(True, "--html/--no-html", help="Save HTML rendering for human review."),
) -> None:
    if not root or not ticker:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence collect sec`",
            what_to_do="pass `--root` and `--ticker`",
            alternatives=["`minerva evidence collect sec --root hard-disk/reports/00-companies/12-robinhood --ticker HOOD`"],
        )
    _print(
        collect_sec_command(
            root=root,
            ticker=ticker,
            annual=annual,
            quarters=quarters,
            earnings=earnings,
            include_financials=financials,
            include_html=html,
            settings=get_settings(),
        )
    )


@app.command("register", help="Register a downloaded, discovered, or blocked source.")
def register_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    status: str | None = typer.Option(None, "--status", help="downloaded, discovered, or blocked."),
    bucket: str | None = typer.Option(None, "--bucket", help="Explicit coverage bucket."),
    source_kind: str | None = typer.Option(None, "--source-kind", help="Explicit source kind."),
    title: str | None = typer.Option(None, "--title", help="Human-readable source title."),
    path: str | None = typer.Option(None, "--path", help="Optional local file path."),
    url: str | None = typer.Option(None, "--url", help="Optional source URL."),
    notes: str | None = typer.Option(None, "--notes", help="Optional notes."),
) -> None:
    if not all([root, status, bucket, source_kind, title]):
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence register`",
            what_to_do="pass `--root`, `--status`, `--bucket`, `--source-kind`, and `--title`",
            alternatives=["`minerva evidence register --root ... --status discovered --bucket external-research --source-kind industry-report --title 'Market report' --url https://...`"],
        )
    _print(register_command(root=root, status=status, bucket=bucket, source_kind=source_kind, title=title, path=path, url=url, notes=notes))


@app.command("inventory", help="Compute current evidence inventory from disk and registry state.")
def inventory_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    write_index: bool = typer.Option(True, "--write-index/--no-write-index", help="Refresh INDEX.md files."),
) -> None:
    if not root:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence inventory`",
            what_to_do="pass `--root`",
            alternatives=["`minerva evidence inventory --root hard-disk/reports/00-companies/12-robinhood`"],
        )
    _print(inventory_command(root=root, write_index=write_index))


@app.command("extract", help="Extract structured outputs from saved sources using a named profile.")
def extract_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    profile: str = typer.Option("default", "--profile", help="Extraction profile name."),
    source_prefix: str | None = typer.Option(None, "--source-prefix", help="Optional local path prefix filter."),
    match: str | None = typer.Option(None, "--match", help="Optional text match filter."),
    force: bool = typer.Option(False, "--force", help="Recompute outputs even when they already exist."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Model override."),
) -> None:
    if not root:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence extract`",
            what_to_do="pass `--root`",
            alternatives=["`minerva evidence extract --root hard-disk/reports/00-companies/12-robinhood --profile default`"],
        )
    _print(
        extract_command(
            root=root,
            profile=profile,
            source_prefix=source_prefix,
            match=match,
            force=force,
            model=model,
            settings=get_settings(),
        )
    )


@app.command("coverage", help="Compare current evidence state against a coverage profile.")
def coverage_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    profile: str = typer.Option("default", "--profile", help="Coverage profile name."),
) -> None:
    if not root:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence coverage`",
            what_to_do="pass `--root`",
            alternatives=["`minerva evidence coverage --root hard-disk/reports/00-companies/12-robinhood --profile default`"],
        )
    _print(coverage_command(root=root, profile=profile))


def _ticker_from_root(paths) -> str:
    registry_path = paths.source_registry_json
    if registry_path.exists():
        import json

        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        ticker = payload.get("ticker")
        if ticker:
            return str(ticker)
    return paths.root.name.split("-", 1)[-1].upper()


def _collect_usage_result() -> CommandResult:
    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            "missing required arguments for `evidence collect sec`",
            "use `evidence collect sec --root ... --ticker ...`",
            ["`evidence collect sec --root ... --ticker AAPL`"],
            EVIDENCE_HELP,
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
