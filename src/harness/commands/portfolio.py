"""Portfolio state commands for the morning brief workflow."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Mapping

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, parse_flag_args
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from harness.portfolio_state import (
    add_adjacency_entry,
    add_thesis_metric,
    enrich_portfolio,
    ensure_portfolio_layout,
    get_thesis_by_ticker,
    load_json,
    parse_iso_date,
    portfolio_paths,
    remove_adjacency_entry,
    render_adjacency_markdown,
    render_thesis_markdown,
    set_thesis_card,
    sync_portfolio,
)

PORTFOLIO_HELP = (
    "Portfolio state commands for the morning brief pipeline.\n\n"
    "Examples:\n"
    "  minerva portfolio sync --holdings-source ./holdings.csv --transactions-source ./transactions.csv --date 2026-04-08\n"
    "  minerva portfolio adjacency add NVDA TSM --type supply-chain --priority high\n"
    "  minerva portfolio thesis set nvda --ticker NVDA --summary \"AI capex demand stays strong\" --core-thesis \"Blackwell ramps\"\n"
)

ADJACENCY_HELP = "Manage the local adjacent-company map."
THESIS_HELP = "Manage compact thesis cards for monitored securities."

app = typer.Typer(help=PORTFOLIO_HELP, no_args_is_help=True)
adjacency_app = typer.Typer(help=ADJACENCY_HELP, no_args_is_help=True)
thesis_app = typer.Typer(help=THESIS_HELP, no_args_is_help=True)
thesis_metric_app = typer.Typer(help="Manage thesis-card metric observations.", no_args_is_help=True)
app.add_typer(adjacency_app, name="adjacency")
app.add_typer(thesis_app, name="thesis")
thesis_app.add_typer(thesis_metric_app, name="metric")


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


def show_thesis_command(*, card_id: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Show one thesis card."""
    start = time.perf_counter()
    paths = ensure_portfolio_layout((settings or get_settings()).ensure_workspace_root())
    cards = load_json(paths.thesis_cards, default=[])
    selected = [card for card in cards if str(card.get("card_id", "")) == card_id]
    if not selected:
        return error_result(
            f"no thesis card exists for `{card_id}`",
            "create it first with `portfolio thesis set`",
            [f"`portfolio thesis set {card_id} --ticker GTLB --summary ...`"],
            start,
        )
    return CommandResult.from_text(render_thesis_markdown(selected), duration_ms=elapsed_ms(start))


def by_ticker_thesis_command(*, ticker: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Show thesis cards linked to a ticker."""
    start = time.perf_counter()
    try:
        selected = get_thesis_by_ticker((settings or get_settings()).ensure_workspace_root(), ticker=ticker)
    except Exception as exc:
        return error_result(
            f"failed to look up thesis cards by ticker: {exc}",
            "pass one valid ticker symbol",
            ["`portfolio thesis by-ticker MU`", "`portfolio thesis by-ticker GTLB`"],
            start,
        )
    return CommandResult.from_text(render_thesis_markdown(selected), duration_ms=elapsed_ms(start))


def set_thesis_command(
    *,
    card_id: str,
    ticker_symbols: list[str],
    summary: str,
    core_thesis: list[str],
    signals: list[str],
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Create or replace one thesis card definition."""
    start = time.perf_counter()
    try:
        card = set_thesis_card(
            (settings or get_settings()).ensure_workspace_root(),
            card_id=card_id,
            ticker_symbols=ticker_symbols,
            summary=summary,
            core_thesis=core_thesis,
            signals=signals,
        )
    except Exception as exc:
        return error_result(
            f"failed to set thesis card: {exc}",
            "pass a lowercase card id, at least one --ticker, and a summary",
            ["`portfolio thesis set gtlb --ticker GTLB --summary 'DevSecOps platform compounder'`"],
            start,
        )
    return CommandResult.from_text(json_lines(card), duration_ms=elapsed_ms(start))


def add_thesis_metric_command(
    *,
    card_id: str,
    name: str,
    period: str,
    value: str,
    date: str | None,
    source: str | None,
    unit: str | None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Append one metric observation to a thesis card."""
    start = time.perf_counter()
    try:
        metric = add_thesis_metric(
            (settings or get_settings()).ensure_workspace_root(),
            card_id=card_id,
            name=name,
            period=period,
            value=value,
            date=date,
            source=source,
            unit=unit,
        )
    except Exception as exc:
        return error_result(
            f"failed to add thesis metric: {exc}",
            "pass a card id, metric name, fiscal period, and value",
            ["`portfolio thesis metric add gtlb --name NRR --period 'Q1 FY2027' --value '116%' --unit %`"],
            start,
        )
    return CommandResult.from_text(json_lines(metric), duration_ms=elapsed_ms(start))


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
def thesis_show_cli(card_id: str = typer.Argument(..., help="Thesis card id.")) -> None:
    _print(show_thesis_command(card_id=card_id))


@thesis_app.command("by-ticker", help="Show thesis cards linked to a ticker.")
def thesis_by_ticker_cli(ticker: str = typer.Argument(..., help="Ticker symbol.")) -> None:
    _print(by_ticker_thesis_command(ticker=ticker))


@thesis_app.command("set", help="Create or replace one thesis card definition.")
def thesis_set_cli(
    card_id: str = typer.Argument(..., help="Thesis card id, lowercase kebab-style."),
    ticker_symbols: list[str] = typer.Option([], "--ticker", help="Ticker symbol; repeat for multi-ticker cards."),
    summary: str = typer.Option(..., "--summary", help="Compact thesis summary."),
    core_thesis: list[str] = typer.Option([], "--core-thesis", help="Core thesis bullet; repeat up to 5."),
    signals: list[str] = typer.Option([], "--signal", help="Signal bullet; repeat up to 5."),
) -> None:
    _print(
        set_thesis_command(
            card_id=card_id,
            ticker_symbols=ticker_symbols,
            summary=summary,
            core_thesis=core_thesis,
            signals=signals,
        )
    )


@thesis_metric_app.command("add", help="Append one thesis metric observation.")
def thesis_metric_add_cli(
    card_id: str = typer.Argument(..., help="Thesis card id."),
    name: str = typer.Option(..., "--name", help="Metric name."),
    period: str = typer.Option(..., "--period", help="Fiscal period, e.g. Q1 FY2027."),
    value: str = typer.Option(..., "--value", help="Metric observation value, stored as text."),
    date_value: str | None = typer.Option(None, "--date", help="Optional observation date."),
    source: str | None = typer.Option(None, "--source", help="Optional source note."),
    unit: str | None = typer.Option(None, "--unit", help="Optional metric unit."),
) -> None:
    _print(
        add_thesis_metric_command(
            card_id=card_id,
            name=name,
            period=period,
            value=value,
            date=date_value,
            source=source,
            unit=unit,
        )
    )


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
            return CommandResult.from_text("", stderr=_usage_error("missing thesis card id"), exit_code=1)
        return show_thesis_command(card_id=args[1], settings=settings)
    if action == "by-ticker":
        if len(args) < 2:
            return CommandResult.from_text("", stderr=_usage_error("missing ticker symbol"), exit_code=1)
        return by_ticker_thesis_command(ticker=args[1], settings=settings)
    if action == "set":
        if len(args) < 2:
            return CommandResult.from_text("", stderr=_usage_error("missing thesis card id"), exit_code=1)
        parsed = _parse_repeated_flag_args(args[2:])
        return set_thesis_command(
            card_id=args[1],
            ticker_symbols=parsed.get("ticker", []),
            summary=_one_flag_value(parsed, "summary"),
            core_thesis=parsed.get("core-thesis", []),
            signals=parsed.get("signal", []),
            settings=settings,
        )
    if action == "metric":
        if len(args) < 2 or args[1] != "add":
            return CommandResult.from_text("", stderr=_usage_error("expected `portfolio thesis metric add <CARD_ID>`"), exit_code=1)
        if len(args) < 3:
            return CommandResult.from_text("", stderr=_usage_error("missing thesis card id"), exit_code=1)
        parsed = _parse_repeated_flag_args(args[3:])
        return add_thesis_metric_command(
            card_id=args[2],
            name=_one_flag_value(parsed, "name"),
            period=_one_flag_value(parsed, "period"),
            value=_one_flag_value(parsed, "value"),
            date=_optional_flag_value(parsed, "date"),
            source=_optional_flag_value(parsed, "source"),
            unit=_optional_flag_value(parsed, "unit"),
            settings=settings,
        )
    return CommandResult.from_text("", stderr=_usage_error(f"unknown thesis action `{action}`"), exit_code=1)


def _usage_error(message: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {message}",
            "What to do instead: use one of the supported portfolio commands",
            "Available alternatives: `portfolio sync`, `portfolio adjacency list`, `portfolio thesis set gtlb --ticker GTLB --summary ...`",
            "",
            PORTFOLIO_HELP.rstrip(),
        ]
    )


def _parse_repeated_flag_args(args: list[str]) -> dict[str, list[str]]:
    """Parse simple `--name value` args while preserving repeated flags."""
    parsed: dict[str, list[str]] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if not token.startswith("--"):
            raise ValueError(_usage_error("arguments must be passed as `--name value` pairs"))
        if index + 1 >= len(args):
            raise ValueError(_usage_error(f"missing value for flag `{token}`"))
        key = token.removeprefix("--")
        parsed.setdefault(key, []).append(args[index + 1])
        index += 2
    return parsed


def _one_flag_value(parsed: dict[str, list[str]], key: str) -> str:
    values = parsed.get(key, [])
    return values[-1] if values else ""


def _optional_flag_value(parsed: dict[str, list[str]], key: str) -> str | None:
    value = _one_flag_value(parsed, key).strip()
    return value or None


def json_lines(payload: Mapping[str, object]) -> str:
    return "\n".join(f"{key}: {payload[key]}" for key in sorted(payload))


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
