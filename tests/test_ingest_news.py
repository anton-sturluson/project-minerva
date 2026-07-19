"""Focused tests for scripts/ingest_news.py."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ingest_news  # noqa: E402


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


def _ingest(tmp_path: Path, raw_dir: Path, *, summaries_dir=None, enrichment=None) -> tuple[dict[str, int], Path]:
    db = tmp_path / "test.db"
    stats = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        explicit_raw=raw_dir,
        explicit_summaries=summaries_dir,
        enrichment_paths=enrichment or [],
    )
    return stats, db


# ---------------------------------------------------------------------------
# 1. schema idempotency
# ---------------------------------------------------------------------------
def test_schema_ensure_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    conn = sqlite3.connect(db)
    try:
        ingest_news.ensure_schema(conn)
        ingest_news.ensure_schema(conn)  # second call must not raise
        cols = [r[1] for r in conn.execute("PRAGMA table_info(news)")]
    finally:
        conn.close()
    assert cols == [
        "article_key",
        "published_at",
        "title",
        "content",
        "summary",
        "source",
        "url",
        "section",
        "collected_at",
    ]


# ---------------------------------------------------------------------------
# 2. article_key is stable across time-precision changes
# ---------------------------------------------------------------------------
def test_article_key_stable_across_time_precision() -> None:
    # Same source, same DATE, same title — different times or offsets must
    # collapse to the same key.
    coarse = ingest_news.article_key("wsj", "2026-07-16", "A Big Story")
    fine = ingest_news.article_key("wsj", "2026-07-16", "A Big Story")
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


def test_published_preserves_explicit_offset() -> None:
    parsed = ingest_news.normalize_published("2026-07-19T04:25:00-04:00")
    assert parsed is not None
    assert parsed.iso == "2026-07-19T04:25:00-04:00"

    compact = ingest_news.normalize_published("2026-07-19T04:25:00-0400")
    assert compact is not None
    assert compact.iso == "2026-07-19T04:25:00-04:00"


def test_published_drops_ambiguous_zone() -> None:
    # "ET" is DST-ambiguous; we must not fabricate an offset.
    parsed = ingest_news.normalize_published("July 16, 2026 9:00 AM ET")
    assert parsed is not None
    assert parsed.iso == "2026-07-16T09:00:00"  # naive time, no offset


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
        (published,) = conn.execute("SELECT published_at FROM news").fetchone()
    assert published == "2026-07-19"


# ---------------------------------------------------------------------------
# 5. nullable summary
# ---------------------------------------------------------------------------
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
    stats2 = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        explicit_raw=raw,
    )
    assert stats2["inserted"] == 0
    assert stats2["duplicates"] == 1
    assert stats2["db_total"] == 1

    with sqlite3.connect(db) as conn:
        (collected,) = conn.execute("SELECT collected_at FROM news").fetchone()
    assert collected == "2026-07-16T09:00:00Z", "original collected_at must survive"


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
        (published,) = conn.execute("SELECT published_at FROM news").fetchone()
    assert published == "2026-07-15T09:00:00-04:00"


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
        (published,) = conn.execute("SELECT published_at FROM news").fetchone()
    assert published == "2026-07-14"


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
        (published,) = conn.execute("SELECT published_at FROM news").fetchone()
    assert published == "2026-07-14"


def test_fallback_enrichment_does_not_expand_partial_date(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    path = _write_raw(
        raw,
        "ir-AMZN-month-only.md",
        {"Source": "IR", "URL": "https://x", "Published": "March 2026", "Collected": "2026-07-15T04:00:00Z"},
        "Month Only",
        "Body.",
    )
    enrich_file = tmp_path / "enrich.jsonl"
    enrich_file.write_text(
        json.dumps(
            {
                "path": str(path),
                "existing_published": "March 2026",
                "published_at": "2026-03-01",
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
        (published,) = conn.execute("SELECT published_at FROM news").fetchone()
    assert published == "2026-07-15"


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
    stats = ingest_news.ingest(
        db_path=db,
        news_root=tmp_path,
        news_sources_path=_sources_json(tmp_path),
        ir_registry_path=_ir_json(tmp_path),
        all_dates=True,
    )
    assert stats["eligible"] == 4
    assert stats["inserted"] == 4
    assert stats["duplicates"] == 0
    assert stats["missing_summaries"] == 0
    assert stats["db_total"] == 4

    with sqlite3.connect(db) as conn:
        sources = {row[0] for row in conn.execute("SELECT source FROM news")}
    assert sources == {"wsj", "economist", "ir-AMZN", "ir-BRK-B"}
