"""CLI adapters for news ingestion and deterministic duplicate lookup."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import NoReturn

import typer

from harness import news
from harness.config import get_settings
from harness.portfolio_state import NON_SECURITY_TICKERS, load_json, portfolio_paths
from minerva import prices as prices_mod

NEWS_HELP = (
    "Download Finnhub news and market data, ingest collected articles, and check "
    "candidate existence.\n\n"
    "Examples:\n"
    "  minerva news download-finnhub --date 2026-07-19\n"
    "  minerva news ingest --raw-dir ./raw --summaries-dir ./summaries\n"
    "  minerva news ingest --date 2026-07-19\n"
    "  minerva news exist --db invest.db --source-id example --input candidates.json\n"
    "  minerva news download-market-data --date 2026-07-19\n"
)

DEFAULT_MARKET_INDEXES = ("^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX")

app = typer.Typer(help=NEWS_HELP, no_args_is_help=True)


@app.command("download-finnhub")
def download_finnhub_cli(
    date_arg: str = typer.Option(
        ...,
        "--date",
        metavar="YYYY-MM-DD",
        help="America/New_York publication day to download.",
    ),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        help="SQLite database (default: <workspace>/data/04-database/invest.db).",
    ),
    symbols: list[str] = typer.Option(
        [],
        "--symbol",
        help=(
            "Only download company news for this Finnhub symbol; may repeat. "
            "Default: all current holdings and watchlist symbols."
        ),
    ),
) -> None:
    """Download Finnhub records directly into the canonical news table."""
    try:
        if not news.DATE_ONLY_RE.fullmatch(date_arg):
            raise ValueError
        publication_date = date.fromisoformat(date_arg)
    except ValueError:
        _fail("--date must be a valid YYYY-MM-DD date", exit_code=2)

    settings = get_settings()
    if not settings.finnhub_api_key:
        _fail("FINNHUB_API_KEY is not configured", exit_code=1)
    workspace_root = settings.resolved_workspace_root
    resolved_db_path = (
        db_path or workspace_root / "data" / "04-database" / "invest.db"
    )
    try:
        universe = load_json(portfolio_paths(workspace_root).universe, default=[])
        if not isinstance(universe, list):
            _fail("portfolio universe must be a JSON array", exit_code=1)
        result = news.download_finnhub(
            db_path=resolved_db_path,
            api_key=settings.finnhub_api_key,
            publication_date=publication_date,
            universe=universe,
            requested_symbols=symbols,
        )
    except news.NewsError as exc:
        _fail(str(exc), exit_code=1)
    except (OSError, sqlite3.Error, ValueError) as exc:
        _fail(str(exc), exit_code=1)

    typer.echo(json.dumps(result, sort_keys=True, separators=(",", ":")))


@app.command("ingest")
def ingest_cli(
    all_dates: bool = typer.Option(
        False,
        "--all",
        help="Backfill every YYYY-MM-DD directory under --news-root.",
    ),
    single_date: str | None = typer.Option(
        None,
        "--date",
        metavar="YYYY-MM-DD",
        help="Ingest one date under --news-root.",
    ),
    raw_dir: Path | None = typer.Option(
        None,
        "--raw-dir",
        help="Explicit raw directory (bypasses --news-root).",
    ),
    summaries_dir: Path | None = typer.Option(
        None,
        "--summaries-dir",
        help="Explicit summaries directory paired with --raw-dir.",
    ),
    news_root: Path | None = typer.Option(
        None,
        "--news-root",
        help="News archive root (default: <workspace>/data/02-news).",
    ),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        help="SQLite database (default: <workspace>/data/04-database/invest.db).",
    ),
    news_sources: Path | None = typer.Option(
        None,
        "--news-sources",
        help="Source registry (default: <news-root>/news-sources.json).",
    ),
    ir_registry: Path | None = typer.Option(
        None,
        "--ir-registry",
        help="IR registry (default: <workspace>/data/01-portfolio/current/ir-registry.json).",
    ),
    enrich: list[Path] = typer.Option(
        [],
        "--enrich",
        help=(
            "Optional JSONL file or directory with {path, published_at} "
            "overrides. May repeat."
        ),
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="Optional file to write per-file decisions.",
    ),
) -> None:
    """Ingest raw markdown and matching summaries into the news table."""
    selected_modes = (
        int(all_dates) + int(single_date is not None) + int(raw_dir is not None)
    )
    if selected_modes != 1:
        _fail("exactly one of --all, --date, or --raw-dir is required", exit_code=2)
    if summaries_dir is not None and raw_dir is None:
        _fail("--summaries-dir requires --raw-dir", exit_code=2)

    workspace_root = get_settings().resolved_workspace_root
    resolved_news_root = news_root or workspace_root / "data" / "02-news"
    resolved_db_path = (
        db_path or workspace_root / "data" / "04-database" / "invest.db"
    )
    resolved_news_sources = (
        news_sources or resolved_news_root / "news-sources.json"
    )
    resolved_ir_registry = (
        ir_registry
        or workspace_root
        / "data"
        / "01-portfolio"
        / "current"
        / "ir-registry.json"
    )

    try:
        result = news.ingest(
            db_path=resolved_db_path,
            news_root=resolved_news_root,
            news_sources_path=resolved_news_sources,
            ir_registry_path=resolved_ir_registry,
            all_dates=all_dates,
            single_date=single_date,
            explicit_raw=raw_dir,
            explicit_summaries=summaries_dir,
            enrichment_paths=enrich,
        )
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                "\n".join(result.report_lines) + "\n", encoding="utf-8"
            )
    except news.NewsError as exc:
        _fail(str(exc), exit_code=1)
    except (OSError, sqlite3.Error) as exc:
        _fail(str(exc), exit_code=1)

    # Preserve the ingestion script's one-line, sorted JSON stdout contract.
    typer.echo(json.dumps(result.stats, sort_keys=True))


def market_instruments(
    workspace_root: Path,
    *,
    indexes: list[str] | None,
    symbols: list[str],
) -> list[tuple[str, str | None, str]]:
    """Return a deterministic holdings/watchlist, index, and explicit universe."""
    universe = load_json(portfolio_paths(workspace_root).universe, default=[])
    instruments: list[tuple[str, str | None, str]] = []
    positions: dict[str, int] = {}

    def add(symbol: str, exchange: str | None, instrument_type: str) -> None:
        normalized = symbol.strip().upper()
        if not normalized or normalized in NON_SECURITY_TICKERS:
            return
        existing = positions.get(normalized)
        if existing is not None:
            if instrument_type == "index":
                instruments[existing] = (normalized, exchange, instrument_type)
            return
        positions[normalized] = len(instruments)
        instruments.append((normalized, exchange, instrument_type))

    portfolio_rows = universe if isinstance(universe, list) else []
    for item in sorted(
        (row for row in portfolio_rows if isinstance(row, dict)),
        key=lambda row: str(row.get("ticker") or "").upper(),
    ):
        add(
            str(item.get("ticker") or ""),
            str(item["exchange"]) if item.get("exchange") else None,
            "security",
        )
    for symbol in DEFAULT_MARKET_INDEXES if indexes is None else indexes:
        add(symbol, None, "index")
    for symbol in symbols:
        add(symbol, None, "security")
    return instruments


@app.command("download-market-data")
def download_market_data_cli(
    single_date: str = typer.Option(
        ...,
        "--date",
        metavar="YYYY-MM-DD",
        help="Use the latest completed trading session on or before this date.",
    ),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        help="SQLite database (default: <workspace>/data/04-database/invest.db).",
    ),
    indexes: list[str] = typer.Option(
        [],
        "--index",
        help="Index symbol; repeat to replace the default index set.",
    ),
    symbols: list[str] = typer.Option(
        [],
        "--symbol",
        help="Additional Yahoo symbol; may be repeated.",
    ),
) -> None:
    """Store completed daily market movements in the existing prices table."""
    try:
        target_date = date.fromisoformat(single_date)
    except ValueError:
        _fail(f"invalid --date: {single_date!r}; expected YYYY-MM-DD", exit_code=2)

    workspace_root = get_settings().resolved_workspace_root
    resolved_db = db_path or prices_mod.default_db_path(workspace_root)
    instruments = market_instruments(
        workspace_root,
        indexes=list(indexes) if indexes else None,
        symbols=list(symbols or []),
    )
    try:
        result = prices_mod.download_market_data(resolved_db, instruments, target_date)
    except (OSError, sqlite3.Error) as exc:
        _fail(str(exc), exit_code=1)
    typer.echo(json.dumps(result, sort_keys=True, separators=(",", ":")))


@app.command("exist")
def exist_cli(
    db_path: Path = typer.Option(..., "--db", help="Path to invest.db."),
    source_id: str = typer.Option(
        ...,
        "--source-id",
        help="Collector source ID used by ingestion article identity.",
    ),
    input_path: str = typer.Option(
        "-",
        "--input",
        metavar="FILE",
        help="Candidate JSON file (default: stdin; use - for stdin).",
    ),
) -> None:
    """Return which candidate news items already exist in SQLite."""
    try:
        raw = _read_candidate_input(input_path)
        candidates = news.parse_candidates(raw)
        result = news.check_candidates(db_path, source_id, candidates)
    except news.CandidateInputError as exc:
        _fail(str(exc), exit_code=2)
    except news.NewsError as exc:
        _fail(str(exc), exit_code=1)
    except (OSError, sqlite3.Error) as exc:
        _fail(str(exc), exit_code=1)

    typer.echo(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def _read_candidate_input(input_path: str) -> str:
    if input_path == "-":
        return typer.get_text_stream("stdin").read()
    return Path(input_path).read_text(encoding="utf-8")


def _fail(message: str, *, exit_code: int) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(exit_code)
