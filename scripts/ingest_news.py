#!/usr/bin/env python3
"""Ingest collected news articles into invest.db.

Reads raw markdown articles produced by the morning-brief collectors, joins
each with its same-name summary, normalizes the publication date, computes a
stable identity key, and inserts one row per unique article into the SQLite
``news`` table.

Usage:
    python scripts/ingest_news.py --all
    python scripts/ingest_news.py --date 2026-07-19
    python scripts/ingest_news.py --raw-dir <dir> --summaries-dir <dir>

The ``article_key`` is SHA-256(source_id + normalized publication DATE +
normalized title). Exact time-of-day precision on the Published field does
not change the key, so a re-collected article stays a single row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Default filesystem layout
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
NEWS_ROOT_DEFAULT = REPO_ROOT / "hard-disk" / "data" / "02-news"
DB_DEFAULT = REPO_ROOT / "hard-disk" / "data" / "04-database" / "invest.db"
SCHEMA_PATH_DEFAULT = REPO_ROOT / "hard-disk" / "data" / "04-database" / "schema.sql"
NEWS_SOURCES_JSON = NEWS_ROOT_DEFAULT / "news-sources.json"
IR_REGISTRY_JSON = (
    REPO_ROOT / "hard-disk" / "data" / "01-portfolio" / "current" / "ir-registry.json"
)

# Header keys we care about (case-insensitive on the label).
META_KEYS = {"source", "url", "published", "collected", "section", "status"}

DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Source-ID resolution
# ---------------------------------------------------------------------------
def load_source_ids(
    news_sources_path: Path, ir_registry_path: Path
) -> list[str]:
    """Build the master list of source IDs, longest first."""
    ids: set[str] = set()
    if news_sources_path.is_file():
        try:
            for entry in json.loads(news_sources_path.read_text(encoding="utf-8")):
                sid = entry.get("id")
                if sid:
                    ids.add(sid)
        except json.JSONDecodeError:
            pass
    if ir_registry_path.is_file():
        try:
            for entry in json.loads(ir_registry_path.read_text(encoding="utf-8")):
                sid = entry.get("security_id")
                if sid:
                    ids.add(f"ir-{sid}")
        except json.JSONDecodeError:
            pass
    return sorted(ids, key=len, reverse=True)


IR_FALLBACK_RE = re.compile(r"^(ir-[A-Z0-9]+(?:\.[A-Z]+)?(?:-[A-Z])?)-")


def resolve_source_id(filename: str, known_ids: list[str]) -> str | None:
    """Return the longest source-id prefix of ``filename``, else None.

    Falls back to a regex for ir-* files when the registry is missing.
    """
    stem = filename[:-3] if filename.endswith(".md") else filename
    for sid in known_ids:
        if stem == sid or stem.startswith(sid + "-"):
            return sid
    if stem.startswith("ir-"):
        m = IR_FALLBACK_RE.match(stem)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Header + body parsing
# ---------------------------------------------------------------------------
@dataclass
class ParsedRaw:
    title: str
    meta: dict[str, str]
    body: str


def parse_raw_markdown(text: str) -> ParsedRaw:
    """Split the header (title + Key: Value block) from the article body."""
    lines = text.splitlines()

    idx = 0
    # Skip leading blank lines then the # Title line.
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    title = ""
    if idx < len(lines) and lines[idx].startswith("# "):
        title = lines[idx][2:].strip()
        idx += 1
    # Skip blanks between title and metadata.
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    meta: dict[str, str] = {}
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            break
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            k = key.strip().lower()
            if k in META_KEYS:
                meta[k] = val.strip()
                idx += 1
                continue
        break

    body = "\n".join(lines[idx:]).strip()
    return ParsedRaw(title=title, meta=meta, body=body)


# ---------------------------------------------------------------------------
# Publication-date normalization
# ---------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Fixed-offset timezone abbreviations. Generic US zone names use IANA zones so
# daylight-saving offsets are resolved from the publication date rather than
# hard-coded.
_TZ_OFFSETS = {
    "UTC": "+00:00",
    "GMT": "+00:00",
    "Z": "+00:00",
    "EST": "-05:00",
    "EDT": "-04:00",
    "CST": "-06:00",
    "CDT": "-05:00",
    "MST": "-07:00",
    "MDT": "-06:00",
    "PST": "-08:00",
    "PDT": "-07:00",
    "BST": "+01:00",
    "CET": "+01:00",
    "CEST": "+02:00",
    "JST": "+09:00",
    "KST": "+09:00",
    "IST": "+05:30",
    "HKT": "+08:00",
    "SGT": "+08:00",
}
_GENERIC_US_ZONES = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
}
_TZ_TOKEN = r"(?:Z|[A-Za-z]+|[+-]\d{2}:?\d{2})"


@dataclass(frozen=True)
class ParsedPublished:
    """A publication instant plus its source-calendar identity date."""

    epoch: int
    date_only: str


def _month(token: str) -> int | None:
    return _MONTHS.get(token.lower().rstrip("."))


def _midnight_utc(value: date) -> ParsedPublished:
    dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return ParsedPublished(epoch=int(dt.timestamp()), date_only=value.isoformat())


def _offset_timezone(token: str) -> timezone | None:
    normalized = _TZ_OFFSETS.get(token.upper(), token)
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", normalized)
    if not match:
        return None
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 23 or minutes > 59:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group(1) == "-":
        delta = -delta
    return timezone(delta)


def _with_time(
    value: date,
    hour: int,
    minute: int,
    second: int,
    zone_token: str,
    ampm: str = "",
) -> ParsedPublished | None:
    """Convert an explicitly zoned time, or fall back to source-date midnight."""
    marker = ampm.upper()
    if marker:
        if not 1 <= hour <= 12:
            return None
        if marker == "PM" and hour < 12:
            hour += 12
        elif marker == "AM" and hour == 12:
            hour = 0
    try:
        naive = datetime(value.year, value.month, value.day, hour, minute, second)
    except ValueError:
        return None

    zone = zone_token.upper()
    if not zone:
        return _midnight_utc(value)
    if zone in {"UTC", "GMT", "Z"}:
        tz = timezone.utc
    elif zone in _GENERIC_US_ZONES:
        tz = ZoneInfo(_GENERIC_US_ZONES[zone])
    else:
        tz = _offset_timezone(zone)
    if tz is None:
        # An unknown abbreviation is no safer to guess than a missing zone.
        return _midnight_utc(value)
    aware = naive.replace(tzinfo=tz)
    return ParsedPublished(
        epoch=int(aware.timestamp()),
        date_only=value.isoformat(),
    )


def _date_with_optional_time(value: date, remainder: str) -> ParsedPublished | None:
    match = re.match(
        rf"^[\s,]*(?:at\s+)?(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?\s*"
        rf"([APap][Mm])?\s*({_TZ_TOKEN})?\b",
        remainder,
        flags=re.IGNORECASE,
    )
    if not match:
        return _midnight_utc(value)
    return _with_time(
        value,
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
        match.group(5) or "",
        match.group(4) or "",
    )


def normalize_published(raw: str) -> ParsedPublished | None:
    """Parse a publication value into integer UTC epoch seconds.

    Exact times are used when the input has an explicit numeric offset, a
    fixed-offset abbreviation, or a generic US zone resolvable with IANA DST
    rules. Date-only values, naive times, and unknown zones map to midnight UTC
    on the source calendar date. The source date is retained separately for
    stable article identity.
    """
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^(updated|posted|published|as of)\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"^(mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip().strip(",")
    if not s:
        return None

    # Pure ISO date: 2026-07-19.
    if DATE_ONLY_RE.fullmatch(s):
        try:
            return _midnight_utc(date.fromisoformat(s))
        except ValueError:
            return None

    # ISO datetime. datetime.fromisoformat handles Z, colon/compact numeric
    # offsets, and fractional seconds. A parsed naive time deliberately falls
    # back to midnight rather than being treated as local time or UTC.
    iso = s.replace(" ", "T", 1) if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", s) else s
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", iso):
        try:
            dt = datetime.fromisoformat(iso.replace("z", "+00:00").replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            source_date = dt.date()
            if dt.tzinfo is None:
                return _midnight_utc(source_date)
            return ParsedPublished(
                epoch=int(dt.timestamp()),
                date_only=source_date.isoformat(),
            )

    # YYYY-MM-DD HH:MM[:SS] [AM/PM] ZONE, including a fixed abbreviation.
    match = re.match(
        rf"^(\d{{4}}-\d{{2}}-\d{{2}})[ T](\d{{1,2}}):(\d{{2}})"
        rf"(?::(\d{{2}}))?\s*([APap][Mm])?\s*({_TZ_TOKEN})?\b",
        s,
    )
    if match:
        try:
            source_date = date.fromisoformat(match.group(1))
        except ValueError:
            return None
        return _with_time(
            source_date,
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4) or 0),
            match.group(6) or "",
            match.group(5) or "",
        )

    # YYYY/MM/DD.
    match = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})\b(.*)$", s)
    if match:
        try:
            source_date = date(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
        except ValueError:
            return None
        return _date_with_optional_time(source_date, match.group(4))

    # MM/DD/YYYY (US).
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\b(.*)$", s)
    if match:
        try:
            source_date = date(
                int(match.group(3)), int(match.group(1)), int(match.group(2))
            )
        except ValueError:
            return None
        return _date_with_optional_time(source_date, match.group(4))

    # DD-Mon-YYYY.
    match = re.match(r"^(\d{1,2})-([A-Za-z]+)-(\d{4})\b(.*)$", s)
    if match:
        month = _month(match.group(2))
        if month:
            try:
                source_date = date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                return None
            return _date_with_optional_time(source_date, match.group(4))

    # "Jul 15th 2026" / "Jul 16. 2026" / "Jul 15 2026".
    match = re.match(
        r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\.?\s+(\d{4})\b(.*)$",
        s,
    )
    if match:
        month = _month(match.group(1))
        if month:
            try:
                source_date = date(int(match.group(3)), month, int(match.group(2)))
            except ValueError:
                return None
            return _date_with_optional_time(source_date, match.group(4))

    # "July 16, 2026 9:00 AM EDT". The optional whitespace before the time
    # also tolerates the historical malformed value "May 8, 20269:16 AM EDT".
    match = re.match(
        rf"^([A-Za-z]+)\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})"
        rf"(?:\s*(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?\s*"
        rf"([APap][Mm])?\s*({_TZ_TOKEN})?)?",
        s,
    )
    if match:
        month = _month(match.group(1))
        if not month:
            return None
        try:
            source_date = date(int(match.group(3)), month, int(match.group(2)))
        except ValueError:
            return None
        if not match.group(4):
            return _midnight_utc(source_date)
        return _with_time(
            source_date,
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6) or 0),
            match.group(8) or "",
            match.group(7) or "",
        )

    # "16 July 2026".
    match = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b(.*)$", s)
    if match:
        month = _month(match.group(2))
        if month:
            try:
                source_date = date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                return None
            return _date_with_optional_time(source_date, match.group(4))

    return None


def normalize_collected(raw: str) -> str:
    """Canonicalize an ISO collection timestamp without changing its instant."""
    value = raw.strip()
    if not value:
        return value
    iso = (
        value.replace(" ", "T", 1)
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", value)
        else value
    )
    try:
        parsed = datetime.fromisoformat(
            iso.replace("z", "+00:00").replace("Z", "+00:00")
        )
    except ValueError:
        return value
    normalized = parsed.isoformat(timespec="seconds")
    return normalized.replace("+00:00", "Z") if iso.upper().endswith("Z") else normalized


# ---------------------------------------------------------------------------
# Exclusion rules
# ---------------------------------------------------------------------------
def is_excluded_filename(name: str) -> str | None:
    """Return an exclusion reason for filenames we never ingest."""
    if name.endswith("-error.md"):
        return "error"
    stem = name[:-3] if name.endswith(".md") else name
    if stem.upper().startswith("INDEX"):
        return "index"
    if stem == "ad-hoc-saas-market-signal":
        return "non-article-note"
    if stem.startswith("bea-schedule"):
        return "bea-schedule-snapshot"
    if re.search(
        r"(?:^|[-_])(?:"
        r"no[-_]new|"
        r"no[-_](?:new|recent)[-_](?:articles?|items?|releases?|disclosures?|content)|"
        r"no[-_](?:articles?|items?|releases?|announcements?|disclosures?|content)|"
        r"not[-_]found|no[-_]qualifying(?:[-_](?:articles?|items?|releases?))?|"
        r"placeholder|empty"
        r")(?:[-_]|$)",
        stem,
        flags=re.IGNORECASE,
    ):
        return "placeholder"
    return None


def is_excluded_meta(meta: dict[str, str], title: str) -> str | None:
    """Content-level exclusions (belt-and-suspenders vs filename)."""
    section = meta.get("section", "").lower()
    if "collection-error" in section or "collection error" in section:
        return "error"
    status = meta.get("status", "").strip().lower()
    if status and status != "ok":
        return "status"
    if re.match(
        r"^no\s+(?:new|recent)?\s*(?:articles?|items?|releases?|announcements?|disclosures?|content)\b",
        title.strip(),
        flags=re.IGNORECASE,
    ):
        return "placeholder"
    return None


# ---------------------------------------------------------------------------
# Article key
# ---------------------------------------------------------------------------
def normalized_title_for_key(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def article_key(source_id: str, date_only: str, title: str) -> str:
    payload = f"{source_id.strip().lower()}|{date_only}|{normalized_title_for_key(title)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------
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
)

_NEWS_COLUMNS = (
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


def _create_news_schema(conn: sqlite3.Connection) -> None:
    conn.execute(NEWS_TABLE_SQL)
    for statement in NEWS_INDEX_SQL:
        conn.execute(statement)


def _legacy_publication_epoch(raw: str, collected_at: str) -> int:
    published = normalize_published(raw)
    if published is not None:
        return published.epoch
    collected = normalize_published(collected_at)
    if collected is not None:
        return _midnight_utc(date.fromisoformat(collected.date_only)).epoch
    # A malformed legacy row must not be dropped merely because its old text
    # cannot be parsed. Epoch zero is an explicit unknown sentinel; the exact
    # legacy value remains available in published_at_raw.
    return 0


def _migrate_legacy_news(
    conn: sqlite3.Connection, legacy_columns: set[str]
) -> None:
    required = set(_NEWS_COLUMNS) - {"published_at_raw"}
    missing = required - legacy_columns
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"cannot migrate legacy news table; missing columns: {names}")

    select_columns = tuple(column for column in _NEWS_COLUMNS if column != "published_at_raw")
    cursor = conn.execute(f"SELECT {', '.join(select_columns)} FROM news")
    legacy_rows = [dict(zip(select_columns, row, strict=True)) for row in cursor]

    conn.execute("SAVEPOINT migrate_legacy_news")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_news_published")
        conn.execute("DROP INDEX IF EXISTS idx_news_collected")
        conn.execute("ALTER TABLE news RENAME TO news_legacy_migration")
        _create_news_schema(conn)

        migrated_rows = []
        for row in legacy_rows:
            raw_value = row["published_at"]
            published_at_raw = "" if raw_value is None else str(raw_value)
            collected_at = row["collected_at"]
            migrated_rows.append(
                (
                    row["article_key"],
                    _legacy_publication_epoch(
                        published_at_raw,
                        "" if collected_at is None else str(collected_at),
                    ),
                    published_at_raw,
                    row["title"],
                    row["content"],
                    row["summary"],
                    row["source"],
                    row["url"],
                    row["section"],
                    collected_at,
                )
            )
        conn.executemany(
            "INSERT INTO news "
            f"({', '.join(_NEWS_COLUMNS)}) VALUES ({', '.join('?' for _ in _NEWS_COLUMNS)})",
            migrated_rows,
        )
        conn.execute("DROP TABLE news_legacy_migration")
        conn.execute("RELEASE SAVEPOINT migrate_legacy_news")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT migrate_legacy_news")
        conn.execute("RELEASE SAVEPOINT migrate_legacy_news")
        raise


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the news schema or atomically migrate the legacy TEXT schema."""
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'news'"
    ).fetchone()
    if table_exists is None:
        _create_news_schema(conn)
        conn.commit()
        return

    column_rows = conn.execute("PRAGMA table_info(news)").fetchall()
    columns = {row[1]: row for row in column_rows}
    published_type = str(columns.get("published_at", (None, None, ""))[2]).upper()
    if "published_at_raw" not in columns or published_type != "INTEGER":
        _migrate_legacy_news(conn, set(columns))
    else:
        _create_news_schema(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------
def load_enrichment(paths: Iterable[Path]) -> dict[str, str]:
    """Return normalized article-path → published_at from JSONL inputs."""
    out: dict[str, str] = {}
    for p in paths:
        if p.is_dir():
            files = sorted(p.glob("*.jsonl"))
        elif p.is_file():
            files = [p]
        else:
            continue
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                path = obj.get("path")
                published = obj.get("published_at")
                if path and published:
                    existing = str(obj.get("existing_published", "")).strip()
                    method = str(obj.get("method", "")).lower()
                    status = str(obj.get("status", "")).lower()
                    partial_existing = bool(
                        re.fullmatch(r"\d{4}(?:-\d{2})?", existing)
                        or re.fullmatch(
                            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
                            r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
                            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}",
                            existing,
                            flags=re.IGNORECASE,
                        )
                    )
                    if partial_existing and (
                        status.startswith("fallback") or "fallback" in method
                    ):
                        # A fallback worker may expand "2026" to Jan 1 or
                        # "March 2026" to Mar 1. That is not a recovered day.
                        continue
                    # Keep the exact chosen enrichment value. In particular,
                    # a naive midnight remains visible in published_at_raw even
                    # though its safe epoch representation is date midnight.
                    publication_input = str(published)
                    article_path = Path(path)
                    out[str(article_path)] = publication_input
                    if len(article_path.parts) >= 3:
                        out["/".join(article_path.parts[-3:])] = publication_input
    return out


# ---------------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    eligible: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped: int = 0
    missing_summaries: int = 0
    publication_fallbacks: int = 0

    def as_dict(self, db_total: int) -> dict[str, int]:
        return {
            "eligible": self.eligible,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "skipped": self.skipped,
            "missing_summaries": self.missing_summaries,
            "publication_fallbacks": self.publication_fallbacks,
            "db_total": db_total,
        }


def _summary_path_for(raw_path: Path, summaries_dir: Path | None) -> Path | None:
    if summaries_dir is None:
        return None
    candidate = summaries_dir / raw_path.name
    return candidate if candidate.is_file() else None


def _iter_raw_dirs(
    news_root: Path,
    *,
    all_dates: bool,
    single_date: str | None,
    explicit_raw: Path | None,
    explicit_summaries: Path | None,
) -> Iterable[tuple[Path, Path | None]]:
    """Yield (raw_dir, summaries_dir_or_None) pairs to walk."""
    if explicit_raw is not None:
        yield explicit_raw, explicit_summaries
        return
    if single_date:
        raw = news_root / single_date / "raw"
        summaries = news_root / single_date / "summaries"
        if raw.is_dir():
            yield raw, summaries if summaries.is_dir() else None
        return
    if all_dates:
        for day_dir in sorted(news_root.iterdir()):
            if not day_dir.is_dir():
                continue
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", day_dir.name):
                continue
            raw = day_dir / "raw"
            if not raw.is_dir():
                continue
            summaries = day_dir / "summaries"
            yield raw, summaries if summaries.is_dir() else None


def ingest(
    *,
    db_path: Path,
    news_root: Path,
    news_sources_path: Path,
    ir_registry_path: Path,
    all_dates: bool = False,
    single_date: str | None = None,
    explicit_raw: Path | None = None,
    explicit_summaries: Path | None = None,
    enrichment_paths: list[Path] | None = None,
    report: list[str] | None = None,
) -> dict[str, int]:
    """Run the ingestion; return stats dict."""
    known_ids = load_source_ids(news_sources_path, ir_registry_path)
    enrichment = load_enrichment(enrichment_paths or [])
    stats = Stats()
    report_lines = report if report is not None else []

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        for raw_dir, summaries_dir in _iter_raw_dirs(
            news_root,
            all_dates=all_dates,
            single_date=single_date,
            explicit_raw=explicit_raw,
            explicit_summaries=explicit_summaries,
        ):
            for raw_path in sorted(raw_dir.glob("*.md")):
                _ingest_one(
                    raw_path,
                    summaries_dir,
                    conn,
                    known_ids,
                    enrichment,
                    stats,
                    report_lines,
                )
        conn.commit()
        db_total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    finally:
        conn.close()
    return stats.as_dict(db_total)


def _ingest_one(
    raw_path: Path,
    summaries_dir: Path | None,
    conn: sqlite3.Connection,
    known_ids: list[str],
    enrichment: dict[str, str],
    stats: Stats,
    report: list[str],
) -> None:
    name = raw_path.name
    reason = is_excluded_filename(name)
    if reason:
        stats.skipped += 1
        report.append(f"skip:{reason}\t{raw_path}")
        return

    source_id = resolve_source_id(name, known_ids)
    if source_id is None:
        stats.skipped += 1
        report.append(f"skip:unknown-source\t{raw_path}")
        return
    if source_id == "bea-schedule":
        stats.skipped += 1
        report.append(f"skip:bea-schedule-snapshot\t{raw_path}")
        return

    try:
        text = raw_path.read_text(encoding="utf-8")
    except OSError as exc:
        stats.skipped += 1
        report.append(f"skip:read-error({exc})\t{raw_path}")
        return

    parsed = parse_raw_markdown(text)
    reason = is_excluded_meta(parsed.meta, parsed.title)
    if reason:
        stats.skipped += 1
        report.append(f"skip:{reason}\t{raw_path}")
        return

    if not parsed.title:
        stats.skipped += 1
        report.append(f"skip:no-title\t{raw_path}")
        return
    if not parsed.body:
        stats.skipped += 1
        report.append(f"skip:no-body\t{raw_path}")
        return

    collected = parsed.meta.get("collected", "").strip()
    if not collected:
        collected = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    else:
        collected = normalize_collected(collected)

    relative_key = (
        "/".join(raw_path.parts[-3:])
        if len(raw_path.parts) >= 3
        else str(raw_path)
    )
    enrichment_value = next(
        (
            value
            for key in (str(raw_path), str(raw_path.resolve()), relative_key)
            if (value := enrichment.get(key)) is not None
        ),
        None,
    )
    published_at_raw = (
        enrichment_value
        if enrichment_value is not None
        else parsed.meta.get("published", "")
    )
    published = normalize_published(published_at_raw)
    if published is None:
        # Completeness wins for the historical migration. Collection date is
        # the least-bad deterministic fallback and cannot make an old row show
        # up in a future digest because collected_at remains historical.
        collected_date = normalize_published(collected)
        if collected_date is None:
            stats.skipped += 1
            report.append(
                f"skip:no-date(published={published_at_raw!r}, collected={collected!r})\t{raw_path}"
            )
            return
        published = _midnight_utc(date.fromisoformat(collected_date.date_only))
        stats.publication_fallbacks += 1
        report.append(f"fallback:publication-date\t{raw_path}")

    url = parsed.meta.get("url", "").strip()
    section = parsed.meta.get("section", "").strip() or None

    stats.eligible += 1

    summary_text: str | None = None
    summary_path = _summary_path_for(raw_path, summaries_dir)
    if summary_path:
        summary_text = summary_path.read_text(encoding="utf-8").strip() or None
    if summary_text is None:
        stats.missing_summaries += 1

    key = article_key(source_id, published.date_only, parsed.title)
    cursor = conn.execute(
        "INSERT OR IGNORE INTO news "
        "(article_key, published_at, published_at_raw, title, content, summary, "
        "source, url, section, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            published.epoch,
            published_at_raw,
            parsed.title,
            parsed.body,
            summary_text,
            source_id,
            url,
            section,
            collected,
        ),
    )
    if cursor.rowcount == 1:
        stats.inserted += 1
    else:
        stats.duplicates += 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="Backfill every YYYY-MM-DD dir under --news-root.")
    mode.add_argument("--date", metavar="YYYY-MM-DD", help="Ingest a single date under --news-root.")
    mode.add_argument("--raw-dir", type=Path, help="Explicit raw directory (bypasses --news-root).")
    p.add_argument("--summaries-dir", type=Path, help="Explicit summaries directory (paired with --raw-dir).")
    p.add_argument("--news-root", type=Path, default=NEWS_ROOT_DEFAULT)
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--news-sources", type=Path, default=NEWS_SOURCES_JSON)
    p.add_argument("--ir-registry", type=Path, default=IR_REGISTRY_JSON)
    p.add_argument(
        "--enrich",
        type=Path,
        action="append",
        default=[],
        help="Optional JSONL file or directory with {path, published_at} overrides. May repeat.",
    )
    p.add_argument("--report", type=Path, help="Optional file to write per-file decisions.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    report_lines: list[str] = []
    stats = ingest(
        db_path=args.db,
        news_root=args.news_root,
        news_sources_path=args.news_sources,
        ir_registry_path=args.ir_registry,
        all_dates=args.all,
        single_date=args.date,
        explicit_raw=args.raw_dir,
        explicit_summaries=args.summaries_dir,
        enrichment_paths=args.enrich,
        report=report_lines,
    )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    # Machine-readable one-line JSON on stdout is the contract for callers
    # (run_morning_brief.sh, tests). Additional human-readable lines go after.
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
