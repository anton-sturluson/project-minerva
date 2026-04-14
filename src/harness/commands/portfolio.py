"""Portfolio state commands for the morning brief workflow."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, parse_flag_args
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from harness.portfolio_state import (
    add_adjacency_entry,
    canonical_security_id,
    enrich_portfolio,
    ensure_portfolio_layout,
    load_json,
    parse_iso_date,
    portfolio_paths,
    remove_adjacency_entry,
    render_adjacency_markdown,
    render_thesis_markdown,
    set_thesis_card,
    sync_portfolio,
    write_json,
)

PORTFOLIO_HELP = (
    "Portfolio state commands for the morning brief pipeline.\n\n"
    "Examples:\n"
    "  minerva portfolio sync --holdings-source ./holdings.csv --transactions-source ./transactions.csv --date 2026-04-08\n"
    "  minerva portfolio adjacency add NVDA TSM --type supply-chain --priority high\n"
    "  minerva portfolio thesis set NVDA --summary \"AI capex demand stays strong\" --expectations \"Blackwell ramps;Gross margin normalizes\"\n"
)

ADJACENCY_HELP = "Manage the local adjacent-company map."
THESIS_HELP = "Manage compact thesis cards for monitored securities."

app = typer.Typer(help=PORTFOLIO_HELP, no_args_is_help=True)
adjacency_app = typer.Typer(help=ADJACENCY_HELP, no_args_is_help=True)
thesis_app = typer.Typer(help=THESIS_HELP, no_args_is_help=True)
app.add_typer(adjacency_app, name="adjacency")
app.add_typer(thesis_app, name="thesis")


def dispatch(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch portfolio commands for `minerva run`."""
    _ = stdin
    active_settings = settings or get_settings()
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `portfolio` subcommand was provided"), exit_code=1)

    subcommand = args[0]
    try:
        if subcommand == "sync":
            parsed = parse_flag_args(args[1:])
            return sync_command(
                as_of=parse_iso_date(str(parsed.get("date") or parsed.get("as-of") or "")),
                holdings_source=str(parsed["holdings-source"]) if "holdings-source" in parsed else None,
                transactions_source=str(parsed["transactions-source"]) if "transactions-source" in parsed else None,
                watchlist_source=str(parsed["watchlist-source"]) if "watchlist-source" in parsed else None,
                sheet_id=str(parsed["sheet-id"]) if "sheet-id" in parsed else None,
                holdings_gid=str(parsed["holdings-gid"]) if "holdings-gid" in parsed else None,
                transactions_gid=str(parsed["transactions-gid"]) if "transactions-gid" in parsed else None,
                settings=active_settings,
            )
        if subcommand == "enrich":
            return enrich_command(settings=active_settings)
        if subcommand == "adjacency":
            return _dispatch_adjacency(args[1:], active_settings)
        if subcommand == "thesis":
            return _dispatch_thesis(args[1:], active_settings)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text("", stderr=_usage_error(f"unknown `portfolio` subcommand `{subcommand}`"), exit_code=1)


def sync_command(
    *,
    as_of,
    holdings_source: str | None,
    transactions_source: str | None,
    watchlist_source: str | None,
    sheet_id: str | None,
    holdings_gid: str | None,
    transactions_gid: str | None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Sync holdings, watchlist, and transactions into local state."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = sync_portfolio(
            active_settings.ensure_workspace_root(),
            as_of=as_of,
            holdings_source=holdings_source,
            transactions_source=transactions_source,
            watchlist_source=watchlist_source,
            sheet_id=sheet_id,
            holdings_gid=holdings_gid,
            transactions_gid=transactions_gid,
        )
    except Exception as exc:
        return error_result(
            f"failed to sync portfolio state: {exc}",
            "provide holdings and transaction sources or configure a sheet export",
            ["`portfolio sync --holdings-source ./holdings.csv --transactions-source ./transactions.csv`"],
            start,
            help_text=PORTFOLIO_HELP,
        )
    lines = [
        f"as_of: {summary['as_of']}",
        f"holdings: {summary['holdings_count']}",
        f"watchlist: {summary['watchlist_count']}",
        f"universe: {summary['universe_count']}",
        f"transactions: {summary['transactions_count']}",
        f"rendered_to: {summary['rendered_path']}",
    ]
    return CommandResult.from_text("\n".join(lines), duration_ms=elapsed_ms(start))


def enrich_command(*, settings: HarnessSettings | None = None) -> CommandResult:
    """Enrich portfolio records with exchange, country, sec_registered, and finnhub_symbol."""
    start = time.perf_counter()
    active_settings = settings or get_settings()
    try:
        summary = enrich_portfolio(
            active_settings.ensure_workspace_root(),
            finnhub_api_key=active_settings.finnhub_api_key,
        )
    except Exception as exc:
        return error_result(
            f"failed to enrich portfolio: {exc}",
            "ensure holdings exist and optionally set FINNHUB_API_KEY for live enrichment",
            ["`portfolio enrich`"],
            start,
        )
    lines = [
        f"enriched: {summary['enriched_count']}",
        f"skipped: {summary['skipped_count']}",
        f"errors: {summary['error_count']}",
    ]
    return CommandResult.from_text("\n".join(lines), duration_ms=elapsed_ms(start))


def list_adjacency_command(*, settings: HarnessSettings | None = None) -> CommandResult:
    """List adjacency entries."""
    start = time.perf_counter()
    paths = ensure_portfolio_layout((settings or get_settings()).ensure_workspace_root())
    entries = load_json(paths.adjacency_map, default=[])
    return CommandResult.from_text(render_adjacency_markdown(entries), duration_ms=elapsed_ms(start))


def add_adjacency_command(
    *,
    monitored: str,
    adjacent: str,
    relationship_type: str,
    note: str | None,
    priority: str | None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Add an adjacency entry."""
    start = time.perf_counter()
    try:
        entry = add_adjacency_entry(
            (settings or get_settings()).ensure_workspace_root(),
            monitored=monitored,
            adjacent=adjacent,
            relationship_type=relationship_type,
            note=note,
            priority=priority,
        )
    except Exception as exc:
        return error_result(
            f"failed to add adjacency entry: {exc}",
            "pass monitored and adjacent identifiers plus a relationship type",
            ["`portfolio adjacency add NVDA TSM --type supply-chain`"],
            start,
        )
    return CommandResult.from_text(json_lines(entry), duration_ms=elapsed_ms(start))


def remove_adjacency_command(
    *,
    monitored: str,
    adjacent: str,
    relationship_type: str | None = None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Remove adjacency entries for one pair."""
    start = time.perf_counter()
    try:
        summary = remove_adjacency_entry(
            (settings or get_settings()).ensure_workspace_root(),
            monitored=monitored,
            adjacent=adjacent,
            relationship_type=relationship_type,
        )
    except Exception as exc:
        return error_result(
            f"failed to remove adjacency entry: {exc}",
            "pass monitored and adjacent identifiers, and optionally a relationship type",
            ["`portfolio adjacency remove NVDA TSM --type supply-chain`"],
            start,
        )
    return CommandResult.from_text(json_lines(summary), duration_ms=elapsed_ms(start))


def render_adjacency_command(*, settings: HarnessSettings | None = None) -> CommandResult:
    """Render adjacency markdown to disk."""
    start = time.perf_counter()
    paths = ensure_portfolio_layout((settings or get_settings()).ensure_workspace_root())
    entries = load_json(paths.adjacency_map, default=[])
    body = render_adjacency_markdown(entries)
    paths.adjacency_rendered.write_text(body, encoding="utf-8")
    return CommandResult.from_text(f"rendered_to: {paths.adjacency_rendered}", duration_ms=elapsed_ms(start))


def list_thesis_command(*, settings: HarnessSettings | None = None) -> CommandResult:
    """List thesis cards."""
    start = time.perf_counter()
    paths = ensure_portfolio_layout((settings or get_settings()).ensure_workspace_root())
    cards = load_json(paths.thesis_cards, default=[])
    return CommandResult.from_text(render_thesis_markdown(cards), duration_ms=elapsed_ms(start))


def show_thesis_command(*, security: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Show one thesis card."""
    start = time.perf_counter()
    paths = ensure_portfolio_layout((settings or get_settings()).ensure_workspace_root())
    cards = load_json(paths.thesis_cards, default=[])
    security_id = canonical_security_id(security)
    selected = [card for card in cards if str(card.get("security_id", "")).upper() == security_id]
    if not selected:
        return error_result(
            f"no thesis card exists for {security_id}",
            "set one first with `portfolio thesis set`",
            [f"`portfolio thesis set {security_id} --summary ...`"],
            start,
        )
    return CommandResult.from_text(render_thesis_markdown(selected), duration_ms=elapsed_ms(start))


def set_thesis_command(
    *,
    security: str,
    summary: str,
    expectations: str,
    disconfirming: str,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Create or replace one thesis card."""
    start = time.perf_counter()
    try:
        card = set_thesis_card(
            (settings or get_settings()).ensure_workspace_root(),
            security=security,
            summary=summary,
            expectations=_split_multi_value(expectations),
            disconfirming_signals=_split_multi_value(disconfirming),
        )
    except Exception as exc:
        return error_result(
            f"failed to set thesis card: {exc}",
            "pass a security identifier and summary, then retry",
            ["`portfolio thesis set NVDA --summary 'AI capex demand stays strong'`"],
            start,
        )
    return CommandResult.from_text(json_lines(card), duration_ms=elapsed_ms(start))


def render_thesis_command(*, settings: HarnessSettings | None = None) -> CommandResult:
    """Render thesis cards to disk."""
    start = time.perf_counter()
    paths = ensure_portfolio_layout((settings or get_settings()).ensure_workspace_root())
    cards = load_json(paths.thesis_cards, default=[])
    body = render_thesis_markdown(cards)
    paths.thesis_rendered.write_text(body, encoding="utf-8")
    return CommandResult.from_text(f"rendered_to: {paths.thesis_rendered}", duration_ms=elapsed_ms(start))


@app.command("sync", help="Sync holdings, transactions, and watchlist state.")
def sync_cli(
    ctx: typer.Context,
    date_arg: str | None = typer.Option(None, "--date", help="ISO date for the sync run."),
    as_of: str | None = typer.Option(None, "--as-of", help="Alias for --date."),
    holdings_source: str | None = typer.Option(None, "--holdings-source", help="CSV/JSON/YAML holdings source."),
    transactions_source: str | None = typer.Option(None, "--transactions-source", help="CSV/JSON/YAML transactions source."),
    watchlist_source: str | None = typer.Option(None, "--watchlist-source", help="Optional local watchlist source."),
    sheet_id: str | None = typer.Option(None, "--sheet-id", help="Google Sheet identifier."),
    holdings_gid: str | None = typer.Option(None, "--holdings-gid", help="Google Sheet gid for holdings."),
    transactions_gid: str | None = typer.Option(None, "--transactions-gid", help="Google Sheet gid for transactions."),
) -> None:
    if not holdings_source and not sheet_id and not portfolio_paths(get_settings().ensure_workspace_root()).holdings.exists():
        abort_with_help(
            ctx,
            what_went_wrong="no holdings source was provided",
            what_to_do="pass `--holdings-source` or a Google Sheet export configuration",
            alternatives=["`minerva portfolio sync --holdings-source ./holdings.csv --transactions-source ./transactions.csv`"],
        )
    _print(
        sync_command(
            as_of=parse_iso_date(date_arg or as_of),
            holdings_source=holdings_source,
            transactions_source=transactions_source,
            watchlist_source=watchlist_source,
            sheet_id=sheet_id,
            holdings_gid=holdings_gid,
            transactions_gid=transactions_gid,
        )
    )


@app.command("enrich", help="Enrich portfolio records with exchange, country, and Finnhub metadata.")
def enrich_cli() -> None:
    _print(enrich_command())


@adjacency_app.command("list", help="List stored adjacency mappings.")
def adjacency_list_cli() -> None:
    _print(list_adjacency_command())


@adjacency_app.command("add", help="Add or replace one adjacency relationship.")
def adjacency_add_cli(
    monitored: str = typer.Argument(..., help="Monitored company identifier."),
    adjacent: str = typer.Argument(..., help="Adjacent company identifier."),
    relationship_type: str = typer.Option(..., "--type", help="Relationship type."),
    note: str | None = typer.Option(None, "--note", help="Optional note."),
    priority: str | None = typer.Option(None, "--priority", help="Optional priority tag."),
) -> None:
    _print(
        add_adjacency_command(
            monitored=monitored,
            adjacent=adjacent,
            relationship_type=relationship_type,
            note=note,
            priority=priority,
        )
    )


@adjacency_app.command("remove", help="Remove one adjacency mapping pair.")
def adjacency_remove_cli(
    monitored: str = typer.Argument(..., help="Monitored company identifier."),
    adjacent: str = typer.Argument(..., help="Adjacent company identifier."),
    relationship_type: str | None = typer.Option(None, "--type", help="Optional relationship type filter."),
) -> None:
    _print(remove_adjacency_command(monitored=monitored, adjacent=adjacent, relationship_type=relationship_type))


@adjacency_app.command("render", help="Render adjacency markdown.")
def adjacency_render_cli() -> None:
    _print(render_adjacency_command())


@thesis_app.command("list", help="List thesis cards.")
def thesis_list_cli() -> None:
    _print(list_thesis_command())


@thesis_app.command("show", help="Show one thesis card.")
def thesis_show_cli(security: str = typer.Argument(..., help="Security identifier.")) -> None:
    _print(show_thesis_command(security=security))


@thesis_app.command("set", help="Create or replace one thesis card.")
def thesis_set_cli(
    security: str = typer.Argument(..., help="Security identifier."),
    summary: str = typer.Option(..., "--summary", help="Compact thesis summary."),
    expectations: str = typer.Option("", "--expectations", help="Semicolon-separated key expectations."),
    disconfirming: str = typer.Option("", "--disconfirming", help="Semicolon-separated disconfirming signals."),
) -> None:
    _print(set_thesis_command(security=security, summary=summary, expectations=expectations, disconfirming=disconfirming))


@thesis_app.command("render", help="Render thesis cards markdown.")
def thesis_render_cli() -> None:
    _print(render_thesis_command())


def _dispatch_adjacency(args: list[str], settings: HarnessSettings) -> CommandResult:
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `portfolio adjacency` action was provided"), exit_code=1)
    action = args[0]
    if action == "list":
        return list_adjacency_command(settings=settings)
    if action == "render":
        return render_adjacency_command(settings=settings)
    if action == "add":
        if len(args) < 3:
            return CommandResult.from_text("", stderr=_usage_error("missing monitored/adjacent identifiers"), exit_code=1)
        parsed = parse_flag_args(args[3:])
        return add_adjacency_command(
            monitored=args[1],
            adjacent=args[2],
            relationship_type=str(parsed.get("type", "")),
            note=str(parsed["note"]) if "note" in parsed else None,
            priority=str(parsed["priority"]) if "priority" in parsed else None,
            settings=settings,
        )
    if action == "remove":
        if len(args) < 3:
            return CommandResult.from_text("", stderr=_usage_error("missing monitored/adjacent identifiers"), exit_code=1)
        parsed = parse_flag_args(args[3:])
        return remove_adjacency_command(
            monitored=args[1],
            adjacent=args[2],
            relationship_type=str(parsed["type"]) if "type" in parsed else None,
            settings=settings,
        )
    return CommandResult.from_text("", stderr=_usage_error(f"unknown adjacency action `{action}`"), exit_code=1)


def _dispatch_thesis(args: list[str], settings: HarnessSettings) -> CommandResult:
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `portfolio thesis` action was provided"), exit_code=1)
    action = args[0]
    if action == "list":
        return list_thesis_command(settings=settings)
    if action == "render":
        return render_thesis_command(settings=settings)
    if action == "show":
        if len(args) < 2:
            return CommandResult.from_text("", stderr=_usage_error("missing security identifier"), exit_code=1)
        return show_thesis_command(security=args[1], settings=settings)
    if action == "set":
        if len(args) < 2:
            return CommandResult.from_text("", stderr=_usage_error("missing security identifier"), exit_code=1)
        parsed = parse_flag_args(args[2:])
        return set_thesis_command(
            security=args[1],
            summary=str(parsed.get("summary", "")),
            expectations=str(parsed.get("expectations", "")),
            disconfirming=str(parsed.get("disconfirming", "")),
            settings=settings,
        )
    return CommandResult.from_text("", stderr=_usage_error(f"unknown thesis action `{action}`"), exit_code=1)


def _usage_error(message: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {message}",
            "What to do instead: use one of the supported portfolio commands",
            "Available alternatives: `portfolio sync`, `portfolio adjacency list`, `portfolio thesis set NVDA --summary ...`",
            "",
            PORTFOLIO_HELP.rstrip(),
        ]
    )


def _split_multi_value(value: str) -> list[str]:
    normalized = value.replace("|", ";")
    return [item.strip() for item in normalized.split(";") if item.strip()]


def json_lines(payload: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {payload[key]}" for key in sorted(payload))


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
