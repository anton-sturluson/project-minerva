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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

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

# Unambiguous timezone abbreviations → UTC offset. Abbreviations that vary
# with DST ("ET", "CT", "MT", "PT") are left out on purpose: converting them
# would require guessing DST for the article date. Time is preserved as naive
# in that case rather than fabricated.
_TZ_OFFSETS = {
    "UTC": "+00:00", "GMT": "+00:00", "Z": "+00:00",
    "EST": "-05:00", "EDT": "-04:00",
    "CST": "-06:00", "CDT": "-05:00",
    "MST": "-07:00", "MDT": "-06:00",
    "PST": "-08:00", "PDT": "-07:00",
    "BST": "+01:00", "CET": "+01:00", "CEST": "+02:00",
    "JST": "+09:00", "KST": "+09:00", "IST": "+05:30",
    "HKT": "+08:00", "SGT": "+08:00",
}


@dataclass
class ParsedPublished:
    """Normalized publication timestamp.

    ``iso`` is what we store in the DB (a date or a full datetime string).
    ``date_only`` is the YYYY-MM-DD used for the article-key hash — so the key
    stays stable when the same article is re-collected with a more precise time.
    """
    iso: str
    date_only: str


def _month(token: str) -> int | None:
    return _MONTHS.get(token.lower().rstrip("."))


def _strip_ordinal(day_token: str) -> str:
    # "16th" → "16", "1st" → "1"
    return re.sub(r"(st|nd|rd|th)$", "", day_token, flags=re.IGNORECASE)


def normalize_published(raw: str) -> ParsedPublished | None:
    """Parse the ``Published:`` field into ISO form.

    Returns None if the value has no complete calendar day.
    """
    if not raw:
        return None
    s = raw.strip()
    # Strip common leading verbs.
    s = re.sub(r"^(updated|posted|published|as of)\s+", "", s, flags=re.IGNORECASE)
    # Strip leading weekday like "Monday, " / "Mon, ".
    s = re.sub(
        r"^(mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip().strip(",")
    if not s:
        return None

    # 1) Pure ISO date: 2026-07-19
    if DATE_ONLY_RE.match(s):
        return ParsedPublished(iso=s, date_only=s)

    # 2) Full ISO datetime with optional offset / Z.
    iso = s.replace(" ", "T", 1) if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", s) else s
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            date_only = dt.date().isoformat()
            # Canonical ISO keeps the same instant/offset while normalizing
            # forms SQLite cannot parse, such as -0400 instead of -04:00.
            normalized_iso = dt.isoformat(timespec="seconds")
            if iso.upper().endswith("Z"):
                normalized_iso = normalized_iso.replace("+00:00", "Z")
            return ParsedPublished(iso=normalized_iso, date_only=date_only)

    # 3) YYYY/MM/DD
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})\b", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            iso_date = date(y, mo, d).isoformat()
            return ParsedPublished(iso=iso_date, date_only=iso_date)
        except ValueError:
            return None

    # 3b) MM/DD/YYYY (US)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\b", s)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            iso_date = date(y, mo, d).isoformat()
            return ParsedPublished(iso=iso_date, date_only=iso_date)
        except ValueError:
            return None

    # 3c) "8-May-2026" — DD-Mon-YYYY
    m = re.match(r"^(\d{1,2})-([A-Za-z]+)-(\d{4})\b", s)
    if m:
        mo = _month(m.group(2))
        if mo:
            try:
                iso_date = date(int(m.group(3)), mo, int(m.group(1))).isoformat()
                return ParsedPublished(iso=iso_date, date_only=iso_date)
            except ValueError:
                return None

    # 3d) "YYYY-MM-DD HH:MM TZABBR"
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([A-Za-z]+)?\b",
        s,
    )
    if m:
        iso_date = m.group(1)
        hh, mm = int(m.group(2)), int(m.group(3))
        ss = int(m.group(4) or 0)
        tz = (m.group(5) or "").upper()
        offset = _TZ_OFFSETS.get(tz, "")
        return ParsedPublished(
            iso=f"{iso_date}T{hh:02d}:{mm:02d}:{ss:02d}{offset}",
            date_only=iso_date,
        )

    # 4) "Jul 15th 2026" / "Jul 16. 2026" / "Jul 15 2026"
    m = re.match(
        r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\.?\s+(\d{4})\b", s
    )
    if m:
        mo = _month(m.group(1))
        if mo:
            try:
                iso_date = date(int(m.group(3)), mo, int(m.group(2))).isoformat()
                return ParsedPublished(iso=iso_date, date_only=iso_date)
            except ValueError:
                return None

    # 5) "July 16, 2026" or "July 16, 2026 9:00 AM EDT" / "JULY 15, 2026"
    # Also tolerate "May 8, 20269:16 AM EDT" (missing space) and trailing junk
    # like "Updated N hours ago" that Reuters appends.
    m = re.match(
        r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
        r"(?:\s*(\d{1,2}):(\d{2})\s*([APap][Mm])?\s*([A-Za-z]+)?)?",
        s,
    )
    if m:
        mo = _month(m.group(1))
        if not mo:
            return None
        try:
            d0 = date(int(m.group(3)), mo, int(m.group(2)))
        except ValueError:
            return None
        iso_date = d0.isoformat()
        if not m.group(4):
            return ParsedPublished(iso=iso_date, date_only=iso_date)
        # Have time.
        hh, mm = int(m.group(4)), int(m.group(5))
        ampm = (m.group(6) or "").upper()
        if ampm == "PM" and hh < 12:
            hh += 12
        elif ampm == "AM" and hh == 12:
            hh = 0
        tz = (m.group(7) or "").upper()
        offset = _TZ_OFFSETS.get(tz, "") if tz else ""
        iso = f"{iso_date}T{hh:02d}:{mm:02d}:00{offset}"
        return ParsedPublished(iso=iso, date_only=iso_date)

    # 6) "16 July 2026"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", s)
    if m:
        mo = _month(m.group(2))
        if mo:
            try:
                iso_date = date(int(m.group(3)), mo, int(m.group(1))).isoformat()
                return ParsedPublished(iso=iso_date, date_only=iso_date)
            except ValueError:
                return None

    return None


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
NEWS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS news (
    article_key   TEXT PRIMARY KEY,
    published_at  TEXT NOT NULL,
    title         TEXT NOT NULL,
    content       TEXT NOT NULL,
    summary       TEXT,
    source        TEXT NOT NULL,
    url           TEXT NOT NULL,
    section       TEXT,
    collected_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);
CREATE INDEX IF NOT EXISTS idx_news_collected ON news(collected_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(NEWS_TABLE_DDL)
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
                    precision = str(obj.get("precision", "")).lower()
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
                    # Do not turn known date-only values into fabricated
                    # midnight publication times.
                    if precision in {"date", "date_only"}:
                        match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(published))
                        if match:
                            published = match.group(1)
                    elif (
                        re.fullmatch(r"\d{4}-\d{2}-\d{2}", existing)
                        and re.fullmatch(
                            r"\d{4}-\d{2}-\d{2}T00:00:00", str(published)
                        )
                    ):
                        published = existing
                    article_path = Path(path)
                    out[str(article_path)] = published
                    if len(article_path.parts) >= 3:
                        out["/".join(article_path.parts[-3:])] = published
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
        normalized_collected = normalize_published(collected)
        if normalized_collected is not None:
            collected = normalized_collected.iso

    relative_key = "/".join(raw_path.parts[-3:]) if len(raw_path.parts) >= 3 else str(raw_path)
    published_raw = (
        enrichment.get(str(raw_path))
        or enrichment.get(str(raw_path.resolve()))
        or enrichment.get(relative_key)
        or parsed.meta.get("published", "")
    )
    published = normalize_published(published_raw)
    if published is None:
        # Completeness wins for the historical migration. Collection date is
        # the least-bad deterministic fallback and cannot make an old row show
        # up in a future digest because collected_at remains historical.
        collected_date = normalize_published(collected)
        if collected_date is None:
            stats.skipped += 1
            report.append(
                f"skip:no-date(published={published_raw!r}, collected={collected!r})\t{raw_path}"
            )
            return
        published = ParsedPublished(
            iso=collected_date.date_only,
            date_only=collected_date.date_only,
        )
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
        "(article_key, published_at, title, content, summary, source, url, section, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            published.iso,
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
