"""Evidence workflow commands."""

from __future__ import annotations

import time

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, parse_flag_args
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from harness.workflows.evidence.audit import DEFAULT_AUDIT_MODEL, default_audit_llm, run_audit
from harness.workflows.evidence.constants import RECOGNIZED_CATEGORIES
from harness.workflows.evidence.ledger import load_ledger, upsert_evidence
from harness.workflows.evidence.paths import resolve_company_root
from harness.workflows.evidence.registry import initialize_registry

EVIDENCE_HELP = (
    "Evidence collection and workflow state commands.\n\n"
    "Examples:\n"
    "  minerva evidence init --root hard-disk/reports/00-companies/12-robinhood --ticker HOOD --name Robinhood --slug robinhood\n"
    "  minerva evidence add-source --root hard-disk/reports/00-companies/12-robinhood --title 'Market Report' --category industry-report --status downloaded --path ./report.md\n"
    "  minerva evidence audit --root hard-disk/reports/00-companies/12-robinhood\n"
)

app = typer.Typer(help=EVIDENCE_HELP, no_args_is_help=True)


def dispatch(args: list[str], settings: HarnessSettings, stdin: bytes = b"") -> CommandResult:
    """Dispatch evidence commands for `minerva run`."""
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `evidence` subcommand was provided", "choose an evidence workflow command", ["`evidence init --root ... --ticker AAPL --name Apple --slug apple`", "`evidence add-source --root ... --title ... --category ... --status ...`", "`evidence audit --root ...`"], EVIDENCE_HELP), exit_code=1)

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
        if subcommand == "add-source":
            parsed = parse_flag_args(args[1:])
            return add_source_command(
                root=str(parsed["root"]),
                title=str(parsed["title"]),
                category=str(parsed["category"]),
                status=str(parsed["status"]),
                path=str(parsed["path"]) if "path" in parsed else None,
                url=str(parsed["url"]) if "url" in parsed else None,
                date=str(parsed["date"]) if "date" in parsed else None,
                notes=str(parsed["notes"]) if "notes" in parsed else None,
                collector=str(parsed["collector"]) if "collector" in parsed else None,
            )
        if subcommand == "audit":
            parsed = parse_flag_args(args[1:])
            import os
            api_key_env = str(parsed.get("api-key-env-var", "OPENAI_API_KEY"))
            api_key = os.environ.get(api_key_env)
            categories_raw = str(parsed["categories"]) if "categories" in parsed else None
            categories = [c.strip() for c in categories_raw.split(",") if c.strip()] if categories_raw else None
            return audit_command(
                root=str(parsed["root"]),
                categories=categories,
                model=str(parsed.get("model", DEFAULT_AUDIT_MODEL)),
                api_key=api_key,
            )
    except KeyError as exc:
        return CommandResult.from_text("", stderr=f"missing required flag: {exc}", exit_code=1)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text("", stderr=_usage_error(f"unknown `evidence` subcommand `{subcommand}`", "choose an evidence workflow command", ["`evidence init --root ... --ticker AAPL --name Apple --slug apple`", "`evidence add-source --root ... --title ... --category ... --status ...`", "`evidence audit --root ...`"], EVIDENCE_HELP), exit_code=1)


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


def add_source_command(
    *,
    root: str,
    title: str,
    category: str,
    status: str,
    path: str | None,
    url: str | None,
    date: str | None,
    notes: str | None,
    collector: str | None,
) -> CommandResult:
    """Add an external or manual evidence source to the V2 ledger."""
    start = time.perf_counter()

    # Validate: downloaded requires a path.
    if status == "downloaded" and not path:
        return CommandResult.from_text(
            "",
            stderr="status=downloaded requires --path; pass a local file path for downloaded sources",
            exit_code=1,
        )

    try:
        paths = resolve_company_root(root)

        # Warn on unrecognized category (but still write the entry).
        warn_stderr: str = ""
        if category.lower() not in RECOGNIZED_CATEGORIES:
            warn_stderr = f"warning: unrecognized category '{category}' — not in RECOGNIZED_CATEGORIES; entry will be written anyway\n"

        # Resolve ticker: check existing ledger → source-registry.json → infer from root.
        ticker: str | None = None
        entries = load_ledger(paths)
        if entries:
            ticker = entries[0].get("ticker")
        if not ticker:
            ticker = _ticker_from_root(paths)

        # Compute relative local_path if a path is provided.
        local_path: str | None = None
        if path:
            try:
                local_path = str(paths.root.__class__(path).relative_to(paths.root))
            except ValueError:
                # Path is not under root — store absolute as-is.
                local_path = path

        entry = upsert_evidence(
            paths,
            ticker=ticker,
            category=category,
            status=status,
            title=title,
            local_path=local_path,
            url=url,
            date=date,
            notes=notes,
            collector=collector,
        )
    except Exception as exc:
        return error_result(
            f"failed to add source: {exc}",
            "verify the root path and source metadata, then retry",
            ["`minerva evidence add-source --root ... --title 'Report' --category industry-report --status discovered --url https://...`"],
            start,
        )

    body = "\n".join(
        [
            f"added_source_id: {entry['id']}",
            f"category: {entry['category']}",
            f"status: {entry['status']}",
            f"evidence_jsonl: {paths.evidence_jsonl.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, stderr=warn_stderr, duration_ms=elapsed_ms(start))


def audit_command(
    *,
    root: str,
    categories: list[str] | None,
    model: str,
    api_key: str | None,
) -> CommandResult:
    """Run the evidence audit workflow and write a memo."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        llm = default_audit_llm(api_key=api_key)
        result = run_audit(paths, categories=categories, model=model, llm=llm)
    except Exception as exc:
        return error_result(
            f"evidence audit failed: {exc}",
            "verify the root path, API key, and evidence ledger, then retry",
            ["`minerva evidence audit --root ...`"],
            start,
        )
    body = f"memo_path: {result['memo_path']}"
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


@app.command("add-source", help="Add an external or manual evidence source to the V2 ledger.")
def add_source_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    title: str | None = typer.Option(None, "--title", help="Human-readable source title."),
    category: str | None = typer.Option(None, "--category", help="Evidence category (e.g. industry-report, news)."),
    status: str | None = typer.Option(None, "--status", help="downloaded, discovered, or blocked."),
    path: str | None = typer.Option(None, "--path", help="Optional local file path (required when status=downloaded)."),
    url: str | None = typer.Option(None, "--url", help="Optional source URL."),
    date: str | None = typer.Option(None, "--date", help="Optional publication date (YYYY-MM-DD)."),
    notes: str | None = typer.Option(None, "--notes", help="Optional notes."),
    collector: str | None = typer.Option(None, "--collector", help="Optional collector identifier."),
) -> None:
    if not all([root, title, category, status]):
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence add-source`",
            what_to_do="pass `--root`, `--title`, `--category`, and `--status`",
            alternatives=["`minerva evidence add-source --root ... --title 'Report' --category industry-report --status discovered --url https://...`"],
        )
    _print(add_source_command(root=root, title=title, category=category, status=status, path=path, url=url, date=date, notes=notes, collector=collector))


@app.command("audit", help="Run the evidence audit workflow and write a memo.")
def audit_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    categories: str | None = typer.Option(None, "--categories", help="Comma-separated list of categories to audit (default: all)."),
    model: str = typer.Option(DEFAULT_AUDIT_MODEL, "--model", help="LLM model to use for the audit."),
    api_key_env_var: str = typer.Option("OPENAI_API_KEY", "--api-key-env-var", help="Environment variable containing the API key."),
) -> None:
    import os

    if not root:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `evidence audit`",
            what_to_do="pass `--root`",
            alternatives=["`minerva evidence audit --root hard-disk/reports/00-companies/12-robinhood`"],
        )
    api_key = os.environ.get(api_key_env_var)
    categories_list = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    _print(audit_command(root=root, categories=categories_list, model=model, api_key=api_key))


def _ticker_from_root(paths) -> str:
    registry_path = paths.source_registry_json
    if registry_path.exists():
        import json

        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        ticker = payload.get("ticker")
        if ticker:
            return str(ticker)
    return paths.root.name.split("-", 1)[-1].upper()


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
