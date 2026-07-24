"""Shared schema and identity helpers for the canonical SQLite news store."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NEWS_DB_RELATIVE_PATH = Path("data") / "04-database" / "invest.db"
FINNHUB_SUMMARY_ONLY_SECTION = "finnhub-summary-only"

NEWS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS news (
    article_key       TEXT PRIMARY KEY,
    published_at      INTEGER NOT NULL,
    published_at_raw  TEXT NOT NULL,
    title             TEXT NOT NULL,
    content           TEXT NOT NULL,
    summary           TEXT,
    source            TEXT NOT NULL,
    url               TEXT NOT NULL,
    section           TEXT,
    collected_at      TEXT NOT NULL
)
"""

NEWS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_news_collected ON news(collected_at)",
    "CREATE INDEX IF NOT EXISTS idx_news_url ON news(url)",
)

NEWS_COLUMNS = (
    "article_key",
    "published_at",
    "published_at_raw",
    "title",
    "content",
    "summary",
    "source",
    "url",
    "section",
    "collected_at",
)


def create_news_schema(connection: sqlite3.Connection) -> None:
    """Create the canonical news table and indexes if they are absent."""
    connection.execute(NEWS_TABLE_SQL)
    for statement in NEWS_INDEX_SQL:
        connection.execute(statement)


def ensure_canonical_news_schema(connection: sqlite3.Connection) -> None:
    """Create or validate the canonical news schema without committing.

    Legacy schema migration remains the responsibility of ``harness.news``,
    which has the historical date parser needed to migrate old rows safely.
    """
    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'news'"
    ).fetchone()
    if table_exists is None:
        create_news_schema(connection)
        return

    columns = {
        str(row[1]): row for row in connection.execute("PRAGMA table_info(news)")
    }
    missing = set(NEWS_COLUMNS) - set(columns)
    published_type = str(columns.get("published_at", (None, None, ""))[2]).upper()
    article_key_is_primary = bool(
        columns.get("article_key") and int(columns["article_key"][5]) == 1
    )
    if missing or published_type != "INTEGER" or not article_key_is_primary:
        if missing:
            detail = f"missing columns: {', '.join(sorted(missing))}"
        elif published_type != "INTEGER":
            detail = (
                f"published_at has type {published_type or 'UNKNOWN'}, expected INTEGER"
            )
        else:
            detail = "article_key is not the primary key"
        raise RuntimeError(
            "news table has an unsupported schema "
            f"({detail}); repair or recreate the database before preparing evidence"
        )
    create_news_schema(connection)


def resolve_news_db_path(workspace_root: Path, db_path: Path | None = None) -> Path:
    """Resolve an explicit news DB path or the workspace-local default."""
    if db_path is not None:
        return db_path.expanduser().resolve()
    return workspace_root.resolve() / NEWS_DB_RELATIVE_PATH


def is_finnhub_summary_only_section(raw_section: object) -> bool:
    """Return whether a row contains only Finnhub's provider summary."""
    return str(raw_section or "").strip().casefold() == FINNHUB_SUMMARY_ONLY_SECTION


def canonical_news_url(raw_url: object) -> str:
    """Return a stable URL identity while leaving the stored URL untouched."""
    url = str(raw_url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        query = urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if not key.casefold().startswith("utm_")
                and key.casefold()
                not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
            )
        )
        host = parts.netloc.casefold().removeprefix("www.")
        path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
        return urlunsplit(("", host, path, query, ""))
    except ValueError:
        return url.partition("#")[0].rstrip("/")
