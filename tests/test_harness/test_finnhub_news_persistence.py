"""Regression coverage for post-crawler Finnhub news persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from harness import news as news_domain
from harness.commands.brief import prep_command
from harness.config import HarnessSettings, get_settings
from harness.morning_brief import (
    MAX_FINNHUB_SUMMARY_CHARS,
    collect_market,
    ensure_daily_run_layout,
    prepare_evidence,
)
from harness.morning_brief_synthesis import (
    ROUTING_AUTO_PORTFOLIO,
    build_source_collection_line,
    build_title_universe,
    partition_candidates,
    query_automatic_evidence,
    synthesize_morning_brief,
)
from harness.news_store import (
    FINNHUB_SUMMARY_ONLY_SECTION,
    ensure_canonical_news_schema,
)
from harness.portfolio_state import ensure_portfolio_layout, portfolio_paths

RUN_DATE = date(2026, 8, 12)
COLLECTED_AT = "2026-08-12T10:15:00Z"


def _timestamp(hour: int) -> int:
    return int(
        datetime(
            RUN_DATE.year,
            RUN_DATE.month,
            RUN_DATE.day,
            hour,
            tzinfo=UTC,
        ).timestamp()
    )


def _write_payload(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_duplicate_payload(path: Path, *, long_summary: bool = False) -> None:
    market_summary = (
        "m" * (MAX_FINNHUB_SUMMARY_CHARS + 500)
        if long_summary
        else "Rates moved after the inflation release."
    )
    _write_payload(
        path,
        {
            "indexes": [
                {
                    "symbol": "SPY",
                    "change_pct": 1.2,
                    "headline": "SPY moved 1.20%",
                }
            ],
            "news": [
                {
                    "headline": "Markets digest inflation data",
                    "datetime": _timestamp(8),
                    "source": "Reuters",
                    "url": "https://www.example.com/markets/story",
                    "summary": market_summary,
                },
                {
                    "headline": "Markets digest inflation data",
                    "datetime": _timestamp(8),
                    "source": "Reuters",
                    "url": "https://example.com/markets/story/?utm_medium=api",
                    "summary": market_summary,
                },
            ],
            "company_news": [
                {
                    "headline": "Shared product update",
                    "datetime": _timestamp(9),
                    "source": "CNBC",
                    "url": "https://example.com/company/update",
                    "summary": "The company described the product update.",
                    "_security_id": "NVDA",
                },
                {
                    "headline": "Shared product update",
                    "datetime": _timestamp(9),
                    "source": "CNBC",
                    "url": "https://example.com/company/update?utm_source=finnhub",
                    "summary": "The company described the product update.",
                    "_security_id": "MSFT",
                },
            ],
        },
    )


def _collect(
    workspace: Path, payload_path: Path, *, collected_at: str = COLLECTED_AT
) -> dict:
    with patch("harness.morning_brief.now_utc_iso", return_value=collected_at):
        return collect_market(
            workspace,
            run_date=RUN_DATE,
            source=str(payload_path),
            provider="file",
        )


def _set_universe(workspace: Path) -> None:
    ensure_portfolio_layout(workspace)
    portfolio_paths(workspace).universe.write_text(
        json.dumps(
            [
                {
                    "security_id": "NVDA",
                    "ticker": "NVDA",
                    "source_kind": "holding",
                },
                {
                    "security_id": "MSFT",
                    "ticker": "MSFT",
                    "source_kind": "watchlist",
                },
            ]
        ),
        encoding="utf-8",
    )


def _prepared_path(workspace: Path) -> Path:
    return (
        ensure_daily_run_layout(workspace, RUN_DATE).structured_dir
        / "prepared-evidence.json"
    )


def test_collect_defers_persistence_until_prep_and_prep_is_idempotent(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "finnhub-market.json"
    _write_duplicate_payload(payload_path, long_summary=True)
    db_path = tmp_path / "custom" / "invest.db"

    collected = _collect(tmp_path, payload_path)

    assert collected["event_count"] == 5
    assert not db_path.exists()
    assert not (tmp_path / "data" / "04-database" / "invest.db").exists()
    raw_payload = json.loads(Path(collected["raw_path"]).read_text(encoding="utf-8"))
    assert "news_persistence" not in raw_payload
    assert all(
        "persisted_article_key" not in event for event in raw_payload["events"]
    )

    first = prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT article_key, published_at, published_at_raw, title, content, "
        "summary, source, section, collected_at FROM news ORDER BY source"
    ).fetchall()
    connection.close()
    assert first["news_inserted_count"] == 2
    assert first["news_duplicate_count"] == 2
    assert len(rows) == 2
    assert {row[6] for row in rows} == {"Reuters", "CNBC"}
    assert {row[7] for row in rows} == {FINNHUB_SUMMARY_ONLY_SECTION}
    assert all(row[4] == row[5] for row in rows)
    assert all(len(row[4]) <= MAX_FINNHUB_SUMMARY_CHARS for row in rows)
    assert {row[8] for row in rows} == {COLLECTED_AT}
    assert all(row[1] in {_timestamp(8), _timestamp(9)} for row in rows)
    assert all(row[2] in {str(_timestamp(8)), str(_timestamp(9))} for row in rows)

    rewritten_raw = json.loads(
        Path(collected["raw_path"]).read_text(encoding="utf-8")
    )
    persisted_events = [
        event
        for event in rewritten_raw["events"]
        if event["event_type"] in {"market-news", "company-news"}
    ]
    assert all(event.get("persisted_article_key") for event in persisted_events)
    assert len({event["persisted_article_key"] for event in persisted_events}) == 2
    assert rewritten_raw["news_persistence"]["inserted"] == 2

    second = prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)
    connection = sqlite3.connect(db_path)
    rerun_count = connection.execute("SELECT count(*) FROM news").fetchone()[0]
    connection.close()

    assert second["news_inserted_count"] == 0
    assert second["news_duplicate_count"] == 4
    assert rerun_count == 2


def test_collecting_prices_only_never_touches_the_database(tmp_path: Path) -> None:
    payload_path = tmp_path / "prices-only.json"
    _write_payload(
        payload_path,
        {
            "indexes": [
                {
                    "symbol": "SPY",
                    "change_pct": -0.4,
                    "headline": "SPY moved -0.40%",
                }
            ]
        },
    )

    result = _collect(tmp_path, payload_path)

    assert result["event_count"] == 1
    assert not (tmp_path / "data" / "04-database" / "invest.db").exists()


def test_exact_url_security_associations_survive_collect_prep_and_synthesis(
    tmp_path: Path,
) -> None:
    _set_universe(tmp_path)
    article_url = "https://example.com/shared-story"
    payload_path = tmp_path / "exact-duplicate-urls.json"
    _write_payload(
        payload_path,
        {
            "news": [
                {
                    "headline": "General version of shared story",
                    "datetime": _timestamp(8),
                    "source": "CNBC",
                    "url": article_url,
                    "summary": "A general provider summary.",
                }
            ],
            "company_news": [
                {
                    "headline": "Shared story affects two companies",
                    "datetime": _timestamp(8),
                    "source": "CNBC",
                    "url": article_url,
                    "summary": "A company-linked provider summary.",
                    "_security_id": "NVDA",
                },
                {
                    "headline": "Shared story affects two companies",
                    "datetime": _timestamp(8),
                    "source": "CNBC",
                    "url": article_url,
                    "summary": "A company-linked provider summary.",
                    "_security_id": "MSFT",
                },
            ],
        },
    )
    db_path = tmp_path / "invest.db"

    _collect(tmp_path, payload_path)
    prep = prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)
    prepared_path = _prepared_path(tmp_path)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    linked_events = [
        event
        for event in prepared["events"]
        if event.get("reference_url") == article_url
    ]

    assert prep["news_inserted_count"] == 1
    assert prep["news_duplicate_count"] == 2
    assert {event["security_id"] for event in linked_events} == {"NVDA", "MSFT"}
    assert {event["event_type"] for event in linked_events} == {"company-news"}
    assert len({event["persisted_article_key"] for event in linked_events}) == 1
    assert any(
        item["reason"] == "duplicate-url-unlinked"
        for item in prepared["suppressed"]
    )

    candidates = build_title_universe(db_path, prepared_path, RUN_DATE)
    plan = partition_candidates(candidates)
    assert len(candidates) == 1
    source_line = build_source_collection_line(candidates)
    assert source_line.startswith("*Source Collection:* 1 article record —")
    assert "CNBC 1" in source_line
    assert candidates[0].title_record()["article_candidate_class"] == (
        "secondary_finnhub_summary_only"
    )
    assert candidates[0].title_record()["evidence_depth"] == "summary_only"
    assert plan.article_candidates == ()
    assert len(plan.automatic_events) == 1
    assert plan.automatic_events[0].routing_class == ROUTING_AUTO_PORTFOLIO

    prompts: list[str] = []

    def model_call(**kwargs) -> str:
        prompts.append(kwargs["prompt"])
        if "PASS 1" in kwargs["prompt"]:
            return '{"ids":[]}'
        return (
            "*Portfolio / Watchlist Events*\n"
            "• Shared story affects NVDA and MSFT.\n\n"
            "*Worth Knowing Today*\n"
            "• No additional selected articles."
        )

    brief = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        model_call=model_call,
    )
    evidence_payload = json.loads(
        prompts[1].split("SHORTLISTED_EVIDENCE_JSON:\n", 1)[1]
    )
    evidence = evidence_payload["evidence"]

    assert brief.count("Shared story affects NVDA and MSFT") == 1
    assert "Finnhub summary-only rows contain only a provider summary" in prompts[0]
    assert "do not treat any as full-text reporting" in prompts[1]
    assert len(evidence) == 1
    assert evidence[0]["evidence_kind"] == "summary_only"
    assert evidence[0]["article_candidate_class"] == (
        "secondary_finnhub_summary_only"
    )
    contexts = evidence[0]["details"]["prepared_event_contexts"]
    assert {(item["security_id"], item["portfolio_role"]) for item in contexts} == {
        ("NVDA", "holding"),
        ("MSFT", "watchlist"),
    }


def test_prepare_prefers_matching_rich_crawler_row_without_inserting_summary(
    tmp_path: Path,
) -> None:
    _set_universe(tmp_path)
    article_url = "https://example.com/company/rich-story"
    payload_path = tmp_path / "matching-finnhub.json"
    _write_payload(
        payload_path,
        {
            "company_news": [
                {
                    "headline": "Finnhub version of rich story",
                    "datetime": _timestamp(9),
                    "source": "Reuters",
                    "url": article_url,
                    "summary": "Thin Finnhub provider summary.",
                    "_security_id": "NVDA",
                }
            ]
        },
    )
    db_path = tmp_path / "invest.db"
    connection = sqlite3.connect(db_path)
    ensure_canonical_news_schema(connection)
    connection.execute(
        "INSERT INTO news VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "crawler-rich-key",
            _timestamp(9),
            "2026-08-12T09:00:00Z",
            "Crawler full-text version of rich story",
            "RICH CRAWLER FULL TEXT with reporting details.",
            "Crawler-generated rich summary.",
            "reuters-markets",
            article_url,
            "markets",
            COLLECTED_AT,
        ),
    )
    connection.commit()
    connection.close()

    _collect(tmp_path, payload_path)
    prep = prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)
    prepared = json.loads(_prepared_path(tmp_path).read_text(encoding="utf-8"))
    event = next(
        item for item in prepared["events"] if item.get("event_type") == "company-news"
    )

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT article_key, content, summary, section FROM news"
    ).fetchall()
    connection.close()
    assert prep["news_inserted_count"] == 0
    assert prep["news_duplicate_count"] == 1
    assert rows == [
        (
            "crawler-rich-key",
            "RICH CRAWLER FULL TEXT with reporting details.",
            "Crawler-generated rich summary.",
            "markets",
        )
    ]
    assert event["persisted_article_key"] == "crawler-rich-key"

    candidates = build_title_universe(db_path, _prepared_path(tmp_path), RUN_DATE)
    plan = partition_candidates(candidates)
    evidence = query_automatic_evidence(db_path, plan.automatic_events)
    assert len(candidates) == 1
    assert candidates[0].metadata["summary_only"] is False
    assert evidence[0]["article_candidate_class"] == "collected_sqlite_article"
    assert evidence[0]["evidence_kind"] == "summary"
    assert evidence[0]["evidence"] == "Crawler-generated rich summary."
    assert "Thin Finnhub provider summary." not in json.dumps(evidence)


def test_backdated_persistence_uses_run_date_for_fresh_queries(tmp_path: Path) -> None:
    payload_path = tmp_path / "backdated.json"
    _write_payload(
        payload_path,
        {
            "news": [
                {
                    "headline": "Backdated run story",
                    "datetime": _timestamp(7),
                    "source": "Reuters",
                    "url": "https://example.com/backdated",
                    "summary": "Provider summary.",
                }
            ]
        },
    )
    db_path = tmp_path / "invest.db"

    _collect(tmp_path, payload_path, collected_at="2030-01-02T23:30:00-05:00")
    prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)

    connection = sqlite3.connect(db_path)
    collected_at = connection.execute("SELECT collected_at FROM news").fetchone()[0]
    connection.close()
    assert collected_at == "2026-08-12T23:30:00-05:00"
    candidates = build_title_universe(db_path, _prepared_path(tmp_path), RUN_DATE)
    assert len(candidates) == 1
    assert build_source_collection_line(candidates).startswith(
        "*Source Collection:* 1 article record —"
    )


def test_invest_db_environment_override_flows_through_brief_prep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_path = tmp_path / "override.json"
    _write_payload(
        payload_path,
        {
            "news": [
                {
                    "headline": "Override path story",
                    "datetime": _timestamp(7),
                    "source": "Reuters",
                    "url": "https://example.com/override",
                    "summary": "Provider summary.",
                }
            ]
        },
    )
    override = tmp_path / "override-db" / "custom.db"
    monkeypatch.setenv("MINERVA_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("INVEST_DB", str(override))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        _collect(tmp_path, payload_path)

        result = prep_command(run_date=RUN_DATE, settings=settings)

        assert result.exit_code == 0
        assert override.is_file()
        assert not (tmp_path / "data" / "04-database" / "invest.db").exists()
    finally:
        get_settings.cache_clear()


def test_collect_does_not_fail_before_supported_legacy_schema_migration(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "legacy-order.json"
    _write_payload(
        payload_path,
        {
            "news": [
                {
                    "headline": "Legacy ordering story",
                    "datetime": _timestamp(7),
                    "source": "Reuters",
                    "url": "https://example.com/legacy-order",
                    "summary": "Provider summary.",
                }
            ]
        },
    )
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
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
        )
        """
    )
    connection.commit()
    connection.close()

    _collect(tmp_path, payload_path)
    connection = sqlite3.connect(db_path)
    assert "published_at_raw" not in {
        row[1] for row in connection.execute("PRAGMA table_info(news)")
    }
    connection.close()

    raw_dir = tmp_path / "empty-raw"
    summaries_dir = tmp_path / "empty-summaries"
    raw_dir.mkdir()
    summaries_dir.mkdir()
    migrated = news_domain.ingest(
        db_path=db_path,
        news_root=tmp_path,
        news_sources_path=tmp_path / "missing-news-sources.json",
        ir_registry_path=tmp_path / "missing-ir-registry.json",
        explicit_raw=raw_dir,
        explicit_summaries=summaries_dir,
    )
    assert migrated.stats["eligible"] == 0

    prep = prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)
    assert prep["news_inserted_count"] == 1


def test_unsupported_schema_error_does_not_claim_ingest_can_fix_it(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "malformed-schema.json"
    _write_payload(
        payload_path,
        {
            "news": [
                {
                    "headline": "Malformed schema story",
                    "datetime": _timestamp(7),
                    "source": "Reuters",
                    "url": "https://example.com/malformed",
                    "summary": "Provider summary.",
                }
            ]
        },
    )
    db_path = tmp_path / "malformed.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE news (
            article_key TEXT,
            published_at INTEGER NOT NULL,
            published_at_raw TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            summary TEXT,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            section TEXT,
            collected_at TEXT NOT NULL
        )
        """
    )

    connection.commit()
    connection.close()
    _collect(tmp_path, payload_path)

    with pytest.raises(RuntimeError, match="unsupported schema") as exc_info:
        prepare_evidence(tmp_path, run_date=RUN_DATE, db_path=db_path)

    message = str(exc_info.value)
    assert "article_key is not the primary key" in message
    assert "repair or recreate" in message
    assert "ingest_news" not in message

    result = prep_command(
        run_date=RUN_DATE,
        settings=HarnessSettings(workspace_root=tmp_path, invest_db=db_path),
    )
    command_message = result.stderr.decode("utf-8")
    assert result.exit_code == 1
    assert "repair or recreate the malformed news database" in command_message
    assert "ingest_news" not in command_message
