"""CLI adapters for news ingestion and deterministic duplicate lookup."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import NoReturn

import typer

from harness import news
from harness.config import get_settings

NEWS_HELP = (
    "Ingest collected news and check candidate article existence.\n\n"
    "Examples:\n"
    "  minerva news ingest --raw-dir ./raw --summaries-dir ./summaries\n"
    "  minerva news ingest --date 2026-07-19\n"
    "  minerva news exist --db invest.db --source-id example --input candidates.json\n"
)

app = typer.Typer(help=NEWS_HELP, no_args_is_help=True)


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
        _fail("exactly one of --all, --date, or --raw-dir is required")

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
        stats, report_lines = _ingest(
            all_dates=all_dates,
            single_date=single_date,
            raw_dir=raw_dir,
            summaries_dir=summaries_dir,
            news_root=resolved_news_root,
            db_path=resolved_db_path,
            news_sources=resolved_news_sources,
            ir_registry=resolved_ir_registry,
            enrich=enrich,
        )
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        _fail(str(exc))

    # Preserve the ingestion script's one-line, sorted JSON stdout contract.
    typer.echo(json.dumps(stats, sort_keys=True))


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
    except (OSError, ValueError, sqlite3.Error) as exc:
        _fail(str(exc))

    typer.echo(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def _ingest(
    *,
    all_dates: bool,
    single_date: str | None,
    raw_dir: Path | None,
    summaries_dir: Path | None,
    news_root: Path,
    db_path: Path,
    news_sources: Path,
    ir_registry: Path,
    enrich: list[Path],
) -> tuple[dict[str, int], list[str]]:
    report_lines: list[str] = []
    stats = news.ingest(
        db_path=db_path,
        news_root=news_root,
        news_sources_path=news_sources,
        ir_registry_path=ir_registry,
        all_dates=all_dates,
        single_date=single_date,
        explicit_raw=raw_dir,
        explicit_summaries=summaries_dir,
        enrichment_paths=enrich,
        report=report_lines,
    )
    return stats, report_lines


def _read_candidate_input(input_path: str) -> str:
    if input_path == "-":
        return typer.get_text_stream("stdin").read()
    return Path(input_path).read_text(encoding="utf-8")


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(2)
