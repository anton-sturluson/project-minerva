"""Focused tests for the importable news ingestion domain."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness import news as ingest_news


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _write_raw(dirpath: Path, name: str, header: dict[str, str], title: str, body: str) -> Path:
    meta = "\n".join(f"{k}: {v}" for k, v in header.items())
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / name
    path.write_text(f"# {title}\n\n{meta}\n\n{body}\n", encoding="utf-8")
    return path


def _sources_json(tmp: Path) -> Path:
    payload = [
        {"id": "wsj"},
        {"id": "economist"},
        {"id": "reuters-markets"},
        {"id": "bls-calendar"},
        {"id": "bea-schedule"},
        {"id": "fed-press"},
    ]
    p = tmp / "news-sources.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _ir_json(tmp: Path) -> Path:
    payload = [
        {"security_id": "AMZN", "company_name": "Amazon.com, Inc."},
        {"security_id": "BRK-B", "company_name": "Berkshire Hathaway"},
        {"security_id": "005930.KS", "company_name": "Samsung"},
    ]
    p = tmp / "ir-registry.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _epoch(iso_utc: str) -> int:
    value = iso_utc.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _ingest(tmp_path: Path, raw_dir: Path, *, summaries_dir=None, enrichment=None) -> tuple[dict[str, int], Path]:
    db = tmp_path / "test.db"
    result = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        explicit_raw=raw_dir,
        explicit_summaries=summaries_dir,
        enrichment_paths=enrichment or [],
    )
    return result.stats, db


# ---------------------------------------------------------------------------
# 1. source registries and schema idempotency
# ---------------------------------------------------------------------------
def test_news_errors_have_domain_specific_types() -> None:
    assert issubclass(ingest_news.CandidateInputError, ingest_news.NewsError)
    assert issubclass(ingest_news.SourceRegistryError, ingest_news.NewsError)
    assert issubclass(ingest_news.NewsSchemaError, ingest_news.NewsError)


def test_absent_optional_source_registries_are_empty(tmp_path: Path) -> None:
    assert ingest_news.load_source_ids(
        tmp_path / "missing-news.json", tmp_path / "missing-ir.json"
    ) == []


@pytest.mark.parametrize(
    ("registry", "payload", "message"),
    [
        ("news", "not-json", "invalid JSON"),
        ("news", '{}', "expected a JSON array"),
        ("news", '[{"id": 123}]', "non-empty string id"),
        ("ir", '[{"security_id": null}]', "non-empty string security_id"),
    ],
)
def test_malformed_source_registry_fails_clearly(
    tmp_path: Path, registry: str, payload: str, message: str
) -> None:
    news_path = tmp_path / "news-sources.json"
    ir_path = tmp_path / "ir-registry.json"
    target = news_path if registry == "news" else ir_path
    target.write_text(payload, encoding="utf-8")

    with pytest.raises(ingest_news.SourceRegistryError, match=message):
        ingest_news.load_source_ids(news_path, ir_path)


def test_schema_ensure_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    conn = sqlite3.connect(db)
    try:
        ingest_news.ensure_schema(conn)
        ingest_news.ensure_schema(conn)  # second call must not raise
        conn.commit()
        column_rows = conn.execute("PRAGMA table_info(news)").fetchall()
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(news)").fetchall()
        }
        url_query_plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT 1 FROM news WHERE url = ? COLLATE BINARY LIMIT 1",
            ("https://example.test/article",),
        ).fetchall()
    finally:
        conn.close()

    columns = {row[1]: row for row in column_rows}
    assert list(columns) == [
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
    ]
    assert columns["published_at"][2].upper() == "INTEGER"
    assert columns["published_at"][3] == 1
    assert columns["published_at_raw"][2].upper() == "TEXT"
    assert columns["published_at_raw"][3] == 1
    assert "idx_news_url" in indexes
    assert any("idx_news_url" in str(row[3]) for row in url_query_plan)


def test_ensure_schema_does_not_commit_callers_pending_write(tmp_path: Path) -> None:
    db = tmp_path / "transaction.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("INSERT INTO unrelated VALUES ('pending')")

        ingest_news.ensure_schema(conn)
        conn.rollback()

        assert conn.execute("SELECT value FROM unrelated").fetchall() == []
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'news'"
        ).fetchone() is None


def test_schema_migrates_legacy_text_rows_and_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE news (
                article_key TEXT PRIMARY KEY,
                published_at TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                section TEXT,
                collected_at TEXT NOT NULL
            );
            CREATE INDEX idx_news_published ON news(published_at);
            CREATE INDEX idx_news_collected ON news(collected_at);
            """
        )
        legacy_rows = [
            (
                "one",
                "2026-07-15T09:00:00-04:00",
                "Offset",
                "Body one",
                "Summary one",
                "wsj",
                "https://one",
                "markets",
                "2026-07-16T01:02:03Z",
            ),
            (
                "two",
                "July 16, 2026 9:00 AM ET",
                "Ambiguous",
                "Body two",
                None,
                "economist",
                "https://two",
                None,
                "2026-07-17T04:05:06-04:00",
            ),
        ]
        conn.executemany(
            "INSERT INTO news VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", legacy_rows
        )
        conn.commit()

        ingest_news.ensure_schema(conn)
        ingest_news.ensure_schema(conn)
        conn.commit()

        column_rows = conn.execute("PRAGMA table_info(news)").fetchall()
        rows = conn.execute(
            "SELECT article_key, published_at, published_at_raw, title, content, "
            "summary, source, url, section, collected_at FROM news ORDER BY article_key"
        ).fetchall()
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(news)").fetchall()
        }
    finally:
        conn.close()

    columns = {row[1]: row for row in column_rows}
    assert columns["published_at"][2].upper() == "INTEGER"
    assert columns["published_at_raw"][3] == 1
    assert "idx_news_url" in indexes
    assert rows == [
        (
            "one",
            _epoch("2026-07-15T13:00:00Z"),
            "2026-07-15T09:00:00-04:00",
            "Offset",
            "Body one",
            "Summary one",
            "wsj",
            "https://one",
            "markets",
            "2026-07-16T01:02:03Z",
        ),
        (
            "two",
            _epoch("2026-07-16T13:00:00Z"),
            "July 16, 2026 9:00 AM ET",
            "Ambiguous",
            "Body two",
            None,
            "economist",
            "https://two",
            None,
            "2026-07-17T04:05:06-04:00",
        ),
    ]


# ---------------------------------------------------------------------------
# 2. article_key is stable across time-precision changes
# ---------------------------------------------------------------------------
def test_article_key_stable_across_time_precision() -> None:
    # The precise value crosses into the prior UTC day, but identity still uses
    # the source calendar date and therefore matches the date-only collection.
    coarse_date = ingest_news.normalize_published("2026-07-16")
    fine_date = ingest_news.normalize_published("2026-07-16T00:30:00+05:30")
    assert coarse_date is not None
    assert fine_date is not None
    coarse = ingest_news.article_key("wsj", coarse_date.date_only, "A Big Story")
    fine = ingest_news.article_key("wsj", fine_date.date_only, "A Big Story")
    assert coarse == fine

    # Casing / whitespace on title normalizes.
    other = ingest_news.article_key("WSJ", "2026-07-16", "  A big   story  ")
    assert other == coarse

    # But changing the DATE changes the key.
    different_date = ingest_news.article_key("wsj", "2026-07-17", "A Big Story")
    assert different_date != coarse


# ---------------------------------------------------------------------------
# 3. real-world header / date variants
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected_date",
    [
        ("2026-07-19", "2026-07-19"),
        ("July 16, 2026 9:00 AM EDT", "2026-07-16"),
        ("July 18, 2026 12:00 pm ET", "2026-07-18"),
        ("Jul 15th 2026", "2026-07-15"),
        ("Jul 16. 2026", "2026-07-16"),
        ("JULY 15, 2026", "2026-07-15"),
        ("2026/07/16", "2026-07-16"),
        ("Updated July 17, 2026 10:49 pm ET", "2026-07-17"),
        ("May 8, 20269:16 AM EDT", "2026-05-08"),
        ("Tuesday, May 12, 2026", "2026-05-12"),
        ("8-May-2026", "2026-05-08"),
        ("2026-06-18 02:06 EDT", "2026-06-18"),
    ],
)
def test_published_variants_parse_to_date(raw: str, expected_date: str) -> None:
    parsed = ingest_news.normalize_published(raw)
    assert parsed is not None, f"failed to parse {raw!r}"
    assert parsed.date_only == expected_date


def test_published_without_day_returns_none() -> None:
    for bad in ["2025", "July 2026 (no exact date visible)", "", "March 2026"]:
        assert ingest_news.normalize_published(bad) is None


@pytest.mark.parametrize(
    ("raw", "expected_utc"),
    [
        ("2026-07-19T04:25:00-04:00", "2026-07-19T08:25:00Z"),
        ("2026-07-19T04:25:00-0400", "2026-07-19T08:25:00Z"),
        ("2026-07-19T04:25:00+05:30", "2026-07-18T22:55:00Z"),
        ("2026-07-19T04:25:00Z", "2026-07-19T04:25:00Z"),
    ],
)
def test_published_exact_offsets_convert_to_utc_epoch(
    raw: str, expected_utc: str
) -> None:
    parsed = ingest_news.normalize_published(raw)
    assert parsed is not None
    assert parsed.epoch == _epoch(expected_utc)
    # Identity follows the source calendar date, even when UTC is a day earlier.
    assert parsed.date_only == "2026-07-19"


@pytest.mark.parametrize(
    ("raw", "expected_utc"),
    [
        ("July 16, 2026 9:00 AM EDT", "2026-07-16T13:00:00Z"),
        ("2026-06-18 02:06 EST", "2026-06-18T07:06:00Z"),
        ("July 16, 2026 9:00 AM JST", "2026-07-16T00:00:00Z"),
        ("July 16, 2026 9:00 AM UTC", "2026-07-16T09:00:00Z"),
    ],
)
def test_published_fixed_abbreviations_convert_to_utc_epoch(
    raw: str, expected_utc: str
) -> None:
    parsed = ingest_news.normalize_published(raw)
    assert parsed is not None
    assert parsed.epoch == _epoch(expected_utc)


@pytest.mark.parametrize(
    ("raw", "expected_utc"),
    [
        ("July 16, 2026 11:00 PM ET", "2026-07-17T03:00:00Z"),
        ("January 16, 2026 11:00 PM ET", "2026-01-17T04:00:00Z"),
        ("July 16, 2026 9:00 AM PT", "2026-07-16T16:00:00Z"),
        ("January 16, 2026 9:00 AM PT", "2026-01-16T17:00:00Z"),
    ],
)
def test_published_generic_us_zones_use_date_aware_utc_offsets(
    raw: str, expected_utc: str
) -> None:
    parsed = ingest_news.normalize_published(raw)
    assert parsed is not None
    assert parsed.epoch == _epoch(expected_utc)


@pytest.mark.parametrize(
    "raw",
    [
        "2026-07-19",
        "July 19, 2026",
        "2026/07/19",
        "19 July 2026",
    ],
)
def test_published_date_only_is_midnight_utc(raw: str) -> None:
    parsed = ingest_news.normalize_published(raw)
    assert parsed is not None
    assert parsed.epoch == _epoch("2026-07-19T00:00:00Z")


@pytest.mark.parametrize(
    "raw",
    [
        "July 16, 2026 9:00 AM",
        "2026-07-16T09:00:00",
        "2026-07-16 09:00 UNKNOWN",
    ],
)
def test_published_unknown_or_missing_zone_falls_back_to_midnight(
    raw: str,
) -> None:
    parsed = ingest_news.normalize_published(raw)
    assert parsed is not None
    assert parsed.epoch == _epoch("2026-07-16T00:00:00Z")
    assert parsed.date_only == "2026-07-16"


def test_collected_timestamp_is_canonicalized_without_changing_offset() -> None:
    assert (
        ingest_news.normalize_collected("2026-07-19T04:25:00-0400")
        == "2026-07-19T04:25:00-04:00"
    )
    assert ingest_news.normalize_collected("2026-07-19T08:25:00Z") == "2026-07-19T08:25:00Z"


# ---------------------------------------------------------------------------
# 4. exclusions
# ---------------------------------------------------------------------------
def test_exclusions_are_skipped(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    # Included baseline
    _write_raw(
        raw,
        "wsj-headline-story.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "2026-07-16", "Collected": "2026-07-19T04:00:00Z"},
        "Headline Story",
        "Body.",
    )
    # Error file — excluded by filename
    _write_raw(
        raw,
        "ir-DUOL-error.md",
        {"Source": "IR", "URL": "https://x", "Published": "2026-07-16", "Collected": "2026-07-19T04:00:00Z", "Section": "collection-error"},
        "Fetch failed",
        "Status: failed",
    )
    # INDEX file
    _write_raw(
        raw,
        "INDEX.md",
        {"Source": "meta", "URL": "n/a", "Published": "2026-07-16", "Collected": "2026-07-19T04:00:00Z"},
        "Index of the day",
        "Body.",
    )
    # BEA schedule snapshot
    _write_raw(
        raw,
        "bea-schedule-gdp-q1.md",
        {"Source": "BEA Release Schedule", "URL": "https://bea", "Published": "2026-07-21", "Collected": "2026-07-19T04:00:00Z"},
        "Scheduled GDP release",
        "Body.",
    )
    # Placeholder no-new-releases
    _write_raw(
        raw,
        "ir-COIN-no-new-releases-jul19.md",
        {"Source": "IR", "URL": "https://x", "Published": "2026-07-19", "Collected": "2026-07-19T04:00:00Z"},
        "No New Releases — IR COIN — 2026-07-19",
        "Body.",
    )
    # Generic no-new variants seen in the historical archive.
    _write_raw(
        raw,
        "ir-005930.KS-no-new-jul19.md",
        {"Source": "IR", "URL": "https://x", "Published": "2026-07-19", "Collected": "2026-07-19T04:00:00Z"},
        "No New Samsung Releases",
        "Body.",
    )
    _write_raw(
        raw,
        "ir-AMZN-no-announcements.md",
        {"Source": "IR", "URL": "https://x", "Published": "2026-07-19", "Collected": "2026-07-19T04:00:00Z"},
        "No Announcements",
        "Body.",
    )
    # Unknown-source file
    _write_raw(
        raw,
        "unknown-random-file.md",
        {"Source": "?", "URL": "?", "Published": "2026-07-19", "Collected": "2026-07-19T04:00:00Z"},
        "Random",
        "Body.",
    )

    stats, _ = _ingest(tmp_path, raw)
    assert stats["inserted"] == 1
    assert stats["eligible"] == 1
    assert stats["skipped"] == 7


def test_missing_publication_day_falls_back_to_collection_date(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_raw(
        raw,
        "wsj-month-only.md",
        {
            "Source": "WSJ",
            "URL": "https://x",
            "Published": "July 2026",
            "Collected": "2026-07-19T04:00:00-04:00",
        },
        "Month Only Story",
        "Article body.",
    )
    stats, db = _ingest(tmp_path, raw)
    assert stats["inserted"] == 1
    assert stats["publication_fallbacks"] == 1
    with sqlite3.connect(db) as conn:
        published, published_raw = conn.execute(
            "SELECT published_at, published_at_raw FROM news"
        ).fetchone()
    assert published == _epoch("2026-07-19T00:00:00Z")
    assert published_raw == "July 2026"


# ---------------------------------------------------------------------------
# 5. reusable result and nullable summary
# ---------------------------------------------------------------------------
def test_ingest_returns_stats_and_report_lines(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_raw(
        raw,
        "wsj-fallback.md",
        {
            "Source": "WSJ",
            "URL": "https://x",
            "Published": "",
            "Collected": "2026-07-19T04:00:00Z",
        },
        "Fallback Story",
        "Article body.",
    )

    result = ingest_news.ingest(
        db_path=tmp_path / "result.db",
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        explicit_raw=raw,
    )

    assert isinstance(result, ingest_news.IngestResult)
    assert result.stats["inserted"] == 1
    assert result.report_lines == (f"fallback:publication-date\t{raw / 'wsj-fallback.md'}",)


def test_summary_is_nullable(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_raw(
        raw,
        "wsj-no-summary.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "2026-07-16", "Collected": "2026-07-19T04:00:00Z"},
        "No Summary Story",
        "Article body.",
    )
    stats, db = _ingest(tmp_path, raw)  # no summaries dir
    assert stats["inserted"] == 1
    assert stats["missing_summaries"] == 1
    with sqlite3.connect(db) as conn:
        (summary,) = conn.execute("SELECT summary FROM news").fetchone()
    assert summary is None


def test_summary_is_joined_by_same_name(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    summaries = tmp_path / "summaries"
    _write_raw(
        raw,
        "wsj-joined.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "2026-07-16", "Collected": "2026-07-19T04:00:00Z"},
        "Joined",
        "Body.",
    )
    summaries.mkdir()
    (summaries / "wsj-joined.md").write_text("This is the summary paragraph.", encoding="utf-8")
    stats, db = _ingest(tmp_path, raw, summaries_dir=summaries)
    assert stats["missing_summaries"] == 0
    with sqlite3.connect(db) as conn:
        (summary,) = conn.execute("SELECT summary FROM news").fetchone()
    assert summary == "This is the summary paragraph."


# ---------------------------------------------------------------------------
# 6. duplicate insert stays one row with original collected_at
# ---------------------------------------------------------------------------
def test_duplicate_reingest_keeps_one_row(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    # First collection: only date, early collected_at
    _write_raw(
        raw,
        "wsj-story-x.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "2026-07-16", "Collected": "2026-07-16T09:00:00Z"},
        "Story X",
        "Body v1.",
    )
    stats1, db = _ingest(tmp_path, raw)
    assert stats1["inserted"] == 1

    # Second collection: same title, more precise Published, later Collected.
    _write_raw(
        raw,
        "wsj-story-x.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "July 16, 2026 9:00 AM EDT", "Collected": "2026-07-19T04:00:00Z"},
        "Story X",
        "Body v2.",
    )
    result2 = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        explicit_raw=raw,
    )
    assert result2.stats["inserted"] == 0
    assert result2.stats["duplicates"] == 1
    assert result2.stats["db_total"] == 1

    with sqlite3.connect(db) as conn:
        collected, published, published_raw, content = conn.execute(
            "SELECT collected_at, published_at, published_at_raw, content FROM news"
        ).fetchone()
    assert collected == "2026-07-16T09:00:00Z", "original collected_at must survive"
    assert published == _epoch("2026-07-16T00:00:00Z")
    assert published_raw == "2026-07-16"
    assert content == "Body v1."


# ---------------------------------------------------------------------------
# 7. enrichment override
# ---------------------------------------------------------------------------
def test_enrichment_overrides_raw_published(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    path = _write_raw(
        raw,
        "wsj-fuzzy-date.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "July 2026 (no exact date visible)", "Collected": "2026-07-19T04:00:00Z"},
        "Fuzzy Date",
        "Body.",
    )
    enrich_file = tmp_path / "enrich.jsonl"
    enrich_file.write_text(
        json.dumps({"path": str(path), "published_at": "2026-07-15T09:00:00-04:00"}) + "\n",
        encoding="utf-8",
    )

    stats, db = _ingest(tmp_path, raw, enrichment=[enrich_file])
    assert stats["inserted"] == 1

    with sqlite3.connect(db) as conn:
        published, published_raw = conn.execute(
            "SELECT published_at, published_at_raw FROM news"
        ).fetchone()
    assert published == _epoch("2026-07-15T13:00:00Z")
    assert published_raw == "2026-07-15T09:00:00-04:00"


def test_enrichment_directory_input(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    path = _write_raw(
        raw,
        "wsj-by-name.md",
        {"Source": "WSJ", "URL": "https://x", "Published": "", "Collected": "2026-07-19T04:00:00Z"},
        "By Name",
        "Body.",
    )
    enrich_dir = tmp_path / "pubdates"
    enrich_dir.mkdir()
    (enrich_dir / "override.jsonl").write_text(
        json.dumps({"path": str(path), "published_at": "2026-07-14"}) + "\n",
        encoding="utf-8",
    )
    stats, db = _ingest(tmp_path, raw, enrichment=[enrich_dir])
    assert stats["inserted"] == 1
    with sqlite3.connect(db) as conn:
        published, published_raw = conn.execute(
            "SELECT published_at, published_at_raw FROM news"
        ).fetchone()
    assert published == _epoch("2026-07-14T00:00:00Z")
    assert published_raw == "2026-07-14"


def test_enrichment_does_not_fabricate_midnight_time(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    path = _write_raw(
        raw,
        "reuters-markets-date-only.md",
        {"Source": "Reuters", "URL": "https://x", "Published": "2026-07-14", "Collected": "2026-07-15T04:00:00Z"},
        "Date Only",
        "Body.",
    )
    enrich_file = tmp_path / "enrich.jsonl"
    enrich_file.write_text(
        json.dumps(
            {
                "path": str(path),
                "existing_published": "2026-07-14",
                "published_at": "2026-07-14T00:00:00",
                "precision": "datetime-naive",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _, db = _ingest(tmp_path, raw, enrichment=[enrich_file])
    with sqlite3.connect(db) as conn:
        published, published_raw = conn.execute(
            "SELECT published_at, published_at_raw FROM news"
        ).fetchone()
    assert published == _epoch("2026-07-14T00:00:00Z")
    assert published_raw == "2026-07-14T00:00:00"


@pytest.mark.parametrize("partial_month", ["Sept 2026", "Sept. 2026"])
def test_fallback_enrichment_does_not_expand_partial_month(
    tmp_path: Path, partial_month: str
) -> None:
    raw = tmp_path / "raw"
    path = _write_raw(
        raw,
        "ir-AMZN-month-only.md",
        {
            "Source": "IR",
            "URL": "https://x",
            "Published": partial_month,
            "Collected": "2026-07-15T04:00:00Z",
        },
        "Month Only",
        "Body.",
    )
    enrich_file = tmp_path / "enrich.jsonl"
    enrich_file.write_text(
        json.dumps(
            {
                "path": str(path),
                "existing_published": partial_month,
                "published_at": "2026-09-01",
                "precision": "date",
                "method": "fallback:existing_no_meta",
                "status": "fallback",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stats, db = _ingest(tmp_path, raw, enrichment=[enrich_file])
    assert stats["publication_fallbacks"] == 1
    with sqlite3.connect(db) as conn:
        published, published_raw = conn.execute(
            "SELECT published_at, published_at_raw FROM news"
        ).fetchone()
    assert published == _epoch("2026-07-15T00:00:00Z")
    assert published_raw == partial_month


# ---------------------------------------------------------------------------
# 8. small end-to-end backfill
# ---------------------------------------------------------------------------
def test_end_to_end_backfill(tmp_path: Path) -> None:
    # Two dated dirs under a mini news root, with summaries. Verify --all-style
    # backfill produces the expected row count and machine-readable stats.
    for day, filename, title, published in [
        ("2026-07-17", "wsj-a.md", "Alpha", "July 17, 2026"),
        ("2026-07-17", "economist-b.md", "Beta", "Jul 17th 2026"),
        ("2026-07-18", "ir-AMZN-c.md", "Gamma", "2026-07-18"),
        ("2026-07-18", "ir-BRK-B-d.md", "Delta", "July 18, 2026 8:00 AM EDT"),
    ]:
        raw = tmp_path / day / "raw"
        summaries = tmp_path / day / "summaries"
        _write_raw(
            raw,
            filename,
            {"Source": "test", "URL": "https://x", "Published": published, "Collected": f"{day}T04:00:00Z"},
            title,
            "Body.",
        )
        summaries.mkdir(exist_ok=True, parents=True)
        (summaries / filename).write_text(f"Summary of {title}.", encoding="utf-8")

    db = tmp_path / "backfill.db"
    result = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        all_dates=True,
    )
    assert result.stats["eligible"] == 4
    assert result.stats["inserted"] == 4
    assert result.stats["duplicates"] == 0
    assert result.stats["missing_summaries"] == 0
    assert result.stats["db_total"] == 4

    with sqlite3.connect(db) as conn:
        sources = {row[0] for row in conn.execute("SELECT source FROM news")}
        rows = conn.execute(
            "SELECT title, published_at, published_at_raw, summary, "
            "typeof(published_at) FROM news ORDER BY title"
        ).fetchall()
    assert sources == {"wsj", "economist", "ir-AMZN", "ir-BRK-B"}
    assert rows == [
        (
            "Alpha",
            _epoch("2026-07-17T00:00:00Z"),
            "July 17, 2026",
            "Summary of Alpha.",
            "integer",
        ),
        (
            "Beta",
            _epoch("2026-07-17T00:00:00Z"),
            "Jul 17th 2026",
            "Summary of Beta.",
            "integer",
        ),
        (
            "Delta",
            _epoch("2026-07-18T12:00:00Z"),
            "July 18, 2026 8:00 AM EDT",
            "Summary of Delta.",
            "integer",
        ),
        (
            "Gamma",
            _epoch("2026-07-18T00:00:00Z"),
            "2026-07-18",
            "Summary of Gamma.",
            "integer",
        ),
    ]

    rerun = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        all_dates=True,
    )
    assert rerun.stats["inserted"] == 0
    assert rerun.stats["duplicates"] == 4
    assert rerun.stats["db_total"] == 4
