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
    "  minerva news ingest --input article.json\n"
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
    input_path: str | None = typer.Option(
        None,
        "--input",
        metavar="FILE",
        help=(
            "One normalized article JSON object with title, source_id, url, "
            "published_at, and content (use - for stdin)."
        ),
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
    """Ingest one normalized article or a file-based news batch."""
    selected_modes = sum(
        (
            int(input_path is not None),
            int(all_dates),
            int(single_date is not None),
            int(raw_dir is not None),
        )
    )
    if selected_modes != 1:
        _fail(
            "exactly one of --input, --all, --date, or --raw-dir is required",
            exit_code=2,
        )
    if summaries_dir is not None and raw_dir is None:
        _fail("--summaries-dir requires --raw-dir", exit_code=2)
    if input_path is not None:
        incompatible = [
            flag
            for flag, selected in (
                ("--summaries-dir", summaries_dir is not None),
                ("--news-root", news_root is not None),
                ("--news-sources", news_sources is not None),
                ("--ir-registry", ir_registry is not None),
                ("--enrich", bool(enrich)),
                ("--report", report is not None),
            )
            if selected
        ]
        if incompatible:
            _fail(
                "--input cannot be combined with batch option(s): "
                + ", ".join(incompatible),
                exit_code=2,
            )

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
        if input_path is not None:
            article = news.parse_article_input(_read_json_input(input_path))
            article_result = news.ingest_article(resolved_db_path, article)
            typer.echo(
                json.dumps(
                    article_result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return

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
    except news.ArticleInputError as exc:
        _fail(str(exc), exit_code=2)
    except news.NewsError as exc:
        _fail(str(exc), exit_code=1)
    except (OSError, sqlite3.Error) as exc:
        _fail(str(exc), exit_code=1)

    # Preserve the ingestion script's one-line, sorted JSON stdout contract.
    typer.echo(json.dumps(result.stats, sort_keys=True))


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
        raw = _read_json_input(input_path)
        candidates = news.parse_candidates(raw)
        result = news.check_candidates(db_path, source_id, candidates)
    except news.CandidateInputError as exc:
        _fail(str(exc), exit_code=2)
    except news.NewsError as exc:
        _fail(str(exc), exit_code=1)
    except (OSError, sqlite3.Error) as exc:
        _fail(str(exc), exit_code=1)

    typer.echo(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def _read_json_input(input_path: str) -> str:
    if input_path == "-":
        return typer.get_text_stream("stdin").read()
    return Path(input_path).read_text(encoding="utf-8")


def _fail(message: str, *, exit_code: int) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(exit_code)
