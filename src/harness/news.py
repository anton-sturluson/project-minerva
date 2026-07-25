"""News ingestion, stable article identity, and read-only existence lookup.

Raw morning-brief markdown is joined to same-name summaries and inserted into
SQLite with a stable SHA-256 identity based on source ID, normalized source
publication date, and normalized title. Duplicate lookup imports and reuses
that exact identity implementation so collection and ingestion cannot drift.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from typing import Iterable, Literal, Mapping, Sequence, TypedDict
from zoneinfo import ZoneInfo

# Header keys we care about (case-insensitive on the label).
META_KEYS = {"source", "url", "published", "collected", "section", "status"}

DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NewsError(Exception):
    """Base class for expected news-domain failures."""


class CandidateInputError(NewsError):
    """Raised when candidate JSON does not match the lookup contract."""


class ArticleInputError(NewsError):
    """Raised when single-article JSON does not match the ingest contract."""


class SourceRegistryError(NewsError):
    """Raised when an existing source registry is malformed."""


class NewsSchemaError(NewsError):
    """Raised when the news schema cannot be created or migrated safely."""


# ---------------------------------------------------------------------------
# Source-ID resolution
# ---------------------------------------------------------------------------


def _load_registry_ids(
    path: Path,
    *,
    registry_name: str,
    id_field: str,
    prefix: str = "",
) -> set[str]:
    """Load required string IDs while allowing an absent optional registry."""
    if not path.exists():
        return set()
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceRegistryError(
            f"malformed {registry_name} {path}: invalid JSON at line "
            f"{exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(payload, list):
        raise SourceRegistryError(
            f"malformed {registry_name} {path}: expected a JSON array"
        )

    ids: set[str] = set()
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise SourceRegistryError(
                f"malformed {registry_name} {path}: entry {index} must be an object"
            )
        source_id = entry.get(id_field)
        if not isinstance(source_id, str) or not source_id.strip():
            raise SourceRegistryError(
                f"malformed {registry_name} {path}: entry {index} must have a "
                f"non-empty string {id_field}"
            )
        ids.add(f"{prefix}{source_id.strip()}")
    return ids


def load_source_ids(news_sources_path: Path, ir_registry_path: Path) -> list[str]:
    """Build the master list of source IDs, longest first.

    Both registry files are optional, but an existing malformed file is an
    operator error rather than an empty registry.
    """
    ids = _load_registry_ids(
        news_sources_path,
        registry_name="news source registry",
        id_field="id",
    )
    ids.update(
        _load_registry_ids(
            ir_registry_path,
            registry_name="IR registry",
            id_field="security_id",
            prefix="ir-",
        )
    )
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
# Single-article input
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArticleInput:
    """Validated normalized article supplied directly by a crawler."""

    title: str
    source_id: str
    url: str
    published_at_raw: str
    published: ParsedPublished
    content: str
    summary: str | None = None
    section: str | None = None
    collected_at: str | None = None


ArticleIngestStatus = Literal["inserted", "duplicate", "updated"]


class ArticleIngestResult(TypedDict):
    status: ArticleIngestStatus
    article_key: str


_ARTICLE_REQUIRED_FIELDS = (
    "title",
    "source_id",
    "url",
    "published_at",
    "content",
)
_ARTICLE_OPTIONAL_FIELDS = {"summary", "section", "collected_at"}


def _required_article_text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ArticleInputError(f"article must have a non-empty string {field}")
    return value.strip()


def _optional_article_text(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArticleInputError(f"article {field} must be a string or null")
    return value.strip() or None


def parse_article_input(text: str) -> ArticleInput:
    """Parse one normalized Markdown/text article from a JSON object."""
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArticleInputError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise ArticleInputError("article JSON must be an object")

    unknown = set(payload) - set(_ARTICLE_REQUIRED_FIELDS) - _ARTICLE_OPTIONAL_FIELDS
    if unknown:
        raise ArticleInputError(
            f"article has unknown field(s): {', '.join(sorted(unknown))}"
        )

    values = {
        field: _required_article_text(payload, field)
        for field in _ARTICLE_REQUIRED_FIELDS
    }
    published = normalize_published(values["published_at"])
    if published is None:
        raise ArticleInputError("article must have a parseable published_at")
    if re.match(r"^(?:<!doctype\s+html\b|<html\b)", values["content"], re.IGNORECASE):
        raise ArticleInputError(
            "article content must be normalized Markdown/text, not raw HTML"
        )

    collected_at = _optional_article_text(payload, "collected_at")
    if collected_at is not None:
        collected_at = normalize_collected(collected_at)

    return ArticleInput(
        title=values["title"],
        source_id=values["source_id"],
        url=values["url"],
        published_at_raw=values["published_at"],
        published=published,
        content=values["content"],
        summary=_optional_article_text(payload, "summary"),
        section=_optional_article_text(payload, "section"),
        collected_at=collected_at,
    )


# ---------------------------------------------------------------------------
# Read-only duplicate lookup
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Candidate:
    """A validated candidate at the JSON/domain boundary."""

    title: str
    url: str
    published: str = ""


MatchKind = Literal["url", "article_key", "batch_url", "batch_article_key"]
ExistenceStatus = Literal["ok", "database_missing", "news_table_missing"]


class SeenMatch(TypedDict):
    index: int
    match: MatchKind


class ExistenceResult(TypedDict):
    status: ExistenceStatus
    seen: list[SeenMatch]
    unseen: list[int]


CandidateInput = Candidate | Mapping[str, object]


def _validated_candidate(item: Mapping[str, object], index: int) -> Candidate:
    title = item.get("title")
    url = item.get("url")
    published = item.get("published", "")
    if not isinstance(title, str) or not title.strip():
        raise CandidateInputError(
            f"candidate {index} must have a non-empty string title"
        )
    if not isinstance(url, str):
        raise CandidateInputError(f"candidate {index} must have a string url")
    if published is None:
        published = ""
    if not isinstance(published, str):
        raise CandidateInputError(
            f"candidate {index} published must be a string when provided"
        )
    return Candidate(title=title, url=url.strip(), published=published.strip())


def _validated_candidates(candidates: Sequence[CandidateInput]) -> list[Candidate]:
    validated: list[Candidate] = []
    for index, candidate in enumerate(candidates):
        if isinstance(candidate, Candidate):
            if not candidate.title.strip():
                raise CandidateInputError(
                    f"candidate {index} must have a non-empty string title"
                )
            validated.append(
                Candidate(
                    title=candidate.title,
                    url=candidate.url.strip(),
                    published=candidate.published.strip(),
                )
            )
        else:
            validated.append(_validated_candidate(candidate, index))
    return validated


def parse_candidates(text: str) -> list[Candidate]:
    """Parse and validate a JSON array of candidate news items."""
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CandidateInputError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, list):
        raise CandidateInputError("candidate JSON must be an array")

    candidates: list[Candidate] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise CandidateInputError(f"candidate {index} must be an object")
        # Ingestion strips metadata values before insertion, so outer transport
        # whitespace is not part of exact URL identity.
        candidates.append(_validated_candidate(item, index))
    return candidates


def _batch_matches(
    source_id: str, candidates: Sequence[Candidate]
) -> list[MatchKind | None]:
    """Mark later in-batch duplicates without touching SQLite."""
    matches: list[MatchKind | None] = [None] * len(candidates)
    urls: set[str] = set()
    keys: set[str] = set()
    for index, candidate in enumerate(candidates):
        if candidate.url:
            if candidate.url in urls:
                matches[index] = "batch_url"
            urls.add(candidate.url)

        published = normalize_published(candidate.published)
        if published is None:
            continue
        key = article_key(source_id, published.date_only, candidate.title)
        if matches[index] is None and key in keys:
            matches[index] = "batch_article_key"
        keys.add(key)
    return matches


def _existence_result(
    status: ExistenceStatus, matches: Sequence[MatchKind | None]
) -> ExistenceResult:
    seen: list[SeenMatch] = []
    unseen: list[int] = []
    for index, match in enumerate(matches):
        if match is None:
            unseen.append(index)
        else:
            seen.append({"index": index, "match": match})
    return {"status": status, "seen": seen, "unseen": unseen}


def check_candidates(
    db_path: Path, source_id: str, candidates: Sequence[CandidateInput]
) -> ExistenceResult:
    """Classify candidates by exact URL, then by shared article identity.

    Later duplicates in the input are classified before any database access.
    Existing databases are opened with SQLite ``mode=ro`` and guarded by
    ``query_only``. A missing database or ``news`` table therefore leaves each
    first occurrence unseen without creating or mutating filesystem state.
    """
    normalized_source_id = source_id.strip()
    if not normalized_source_id:
        raise CandidateInputError("source-id must not be empty")

    validated = _validated_candidates(candidates)
    matches = _batch_matches(normalized_source_id, validated)
    if not db_path.is_file():
        return _existence_result("database_missing", matches)

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        # Keep the batch on one read snapshot while collectors may run in
        # parallel with the eventual single ingestion writer.
        conn.execute("BEGIN")
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "news"),
        ).fetchone()
        if table_exists is None:
            return _existence_result("news_table_missing", matches)

        for index, candidate in enumerate(validated):
            if matches[index] is not None:
                continue
            if candidate.url:
                url_match = conn.execute(
                    "SELECT 1 FROM news WHERE url = ? COLLATE BINARY LIMIT 1",
                    (candidate.url,),
                ).fetchone()
                if url_match is not None:
                    matches[index] = "url"
                    continue

            published = normalize_published(candidate.published)
            if published is not None:
                key = article_key(
                    normalized_source_id, published.date_only, candidate.title
                )
                key_match = conn.execute(
                    "SELECT 1 FROM news WHERE article_key = ? COLLATE BINARY LIMIT 1",
                    (key,),
                ).fetchone()
                if key_match is not None:
                    matches[index] = "article_key"

    return _existence_result("ok", matches)


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
    "CREATE INDEX IF NOT EXISTS idx_news_url ON news(url)",
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
        raise NewsSchemaError(
            f"cannot migrate legacy news table; missing columns: {names}"
        )

    select_columns = tuple(column for column in _NEWS_COLUMNS if column != "published_at_raw")
    cursor = conn.execute(f"SELECT {', '.join(select_columns)} FROM news")
    legacy_rows = [dict(zip(select_columns, row, strict=True)) for row in cursor]

    conn.execute("SAVEPOINT migrate_legacy_news")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_news_published")
        conn.execute("DROP INDEX IF EXISTS idx_news_collected")
        conn.execute("DROP INDEX IF EXISTS idx_news_url")
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
    """Stage schema creation or migration in the caller-owned transaction.

    The function deliberately never commits. If the caller has not started a
    transaction, one is opened so even SQLite DDL remains subject to the
    caller's eventual commit or rollback.
    """
    if not conn.in_transaction:
        conn.execute("BEGIN")

    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'news'"
    ).fetchone()
    if table_exists is None:
        _create_news_schema(conn)
        return

    column_rows = conn.execute("PRAGMA table_info(news)").fetchall()
    columns = {row[1]: row for row in column_rows}
    published_type = str(columns.get("published_at", (None, None, ""))[2]).upper()
    if "published_at_raw" not in columns or published_type != "INTEGER":
        _migrate_legacy_news(conn, set(columns))
    else:
        _create_news_schema(conn)


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Enable WAL, retrying its lock-sensitive first-time transition."""
    deadline = monotonic() + 30
    while True:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or monotonic() >= deadline:
                raise
            sleep(0.05)


def ingest_article(db_path: Path, article: ArticleInput) -> ArticleIngestResult:
    """Insert or update one article in a short, serialized WAL transaction."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    key = article_key(article.source_id, article.published.date_only, article.title)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        _enable_wal(conn)
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        existing = conn.execute(
            f"SELECT {', '.join(_NEWS_COLUMNS)} FROM news "
            "WHERE url = ? COLLATE BINARY "
            "ORDER BY CASE WHEN article_key = ? THEN 0 ELSE 1 END, article_key "
            "LIMIT 1",
            (article.url, key),
        ).fetchone()
        if existing is None:
            existing = conn.execute(
                f"SELECT {', '.join(_NEWS_COLUMNS)} FROM news WHERE article_key = ?",
                (key,),
            ).fetchone()
        collected_at = article.collected_at
        if collected_at is None:
            collected_at = (
                existing[-1]
                if existing is not None
                else datetime.now(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
        values = (
            key,
            article.published.epoch,
            article.published_at_raw,
            article.title,
            article.content,
            article.summary,
            article.source_id,
            article.url,
            article.section,
            collected_at,
        )

        if existing is None:
            placeholders = ", ".join("?" for _ in _NEWS_COLUMNS)
            conn.execute(
                f"INSERT INTO news ({', '.join(_NEWS_COLUMNS)}) "
                f"VALUES ({placeholders})",
                values,
            )
            status: ArticleIngestStatus = "inserted"
        elif tuple(existing) == values:
            status = "duplicate"
        elif existing[0] != key and conn.execute(
            "SELECT 1 FROM news WHERE article_key = ?", (key,)
        ).fetchone() is not None:
            # The database already contains separate URL and article-key
            # matches. Preserve both rather than guessing which row to merge.
            status = "duplicate"
        else:
            assignments = ", ".join(f"{column} = ?" for column in _NEWS_COLUMNS)
            conn.execute(
                f"UPDATE news SET {assignments} WHERE article_key = ?",
                (*values, existing[0]),
            )
            status = "updated"
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"status": status, "article_key": key}


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------
def _is_partial_publication(value: str) -> bool:
    """Return whether a publication value has a year/month but no day."""
    normalized = value.strip()
    if re.fullmatch(r"\d{4}(?:-\d{2})?", normalized):
        return True
    month_year = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})", normalized)
    return month_year is not None and _month(month_year.group(1)) is not None


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
                    payload: object = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                obj: Mapping[object, object] = payload
                path = obj.get("path")
                published = obj.get("published_at")
                if (
                    isinstance(path, str)
                    and path
                    and isinstance(published, (str, int, float))
                    and not isinstance(published, bool)
                ):
                    existing = str(obj.get("existing_published", "")).strip()
                    method = str(obj.get("method", "")).lower()
                    status = str(obj.get("status", "")).lower()
                    partial_existing = _is_partial_publication(existing)
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


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Reusable ingestion output with statistics and per-file decisions."""

    stats: dict[str, int]
    report_lines: tuple[str, ...]


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
) -> IngestResult:
    """Run one atomic ingestion and return stats plus per-file decisions."""
    known_ids = load_source_ids(news_sources_path, ir_registry_path)
    enrichment = load_enrichment(enrichment_paths or [])
    stats = Stats()
    report_lines: list[str] = []

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")
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
    return IngestResult(
        stats=stats.as_dict(db_total),
        report_lines=tuple(report_lines),
    )


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
