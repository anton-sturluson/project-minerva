"""Focused tests for deterministic morning-brief orchestration helpers."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "scripts" / "morning_brief_helper.py"
SPEC = importlib.util.spec_from_file_location("morning_brief_helper", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_parse_run_date_is_strict_and_previous_date_cli_logic_is_exact() -> None:
    assert helper.parse_run_date("2026-03-01") == date(2026, 3, 1)
    with pytest.raises(ValueError, match="ISO date"):
        helper.parse_run_date("2026-02-30")
    with pytest.raises(ValueError, match="ISO date"):
        helper.parse_run_date("2026-3-1")


def test_brief_window_uses_exact_four_am_new_york_bounds_across_dst() -> None:
    start, end = helper.brief_window(date(2026, 11, 1))

    assert start.isoformat() == "2026-10-31T04:00:00-04:00"
    assert end.isoformat() == "2026-11-01T04:00:00-05:00"
    assert int(end.timestamp()) - int(start.timestamp()) == 25 * 60 * 60


def test_render_prompt_does_not_expand_placeholders_inside_metadata() -> None:
    template = "source={{SOURCE_NAME}} date={{DATE}} unknown={{UNKNOWN}}"
    rendered = helper.render_prompt(
        template,
        {"SOURCE_NAME": "literal {{DATE}} metadata", "DATE": "2026-07-27"},
    )

    assert rendered == (
        "source=literal {{DATE}} metadata date=2026-07-27 unknown={{UNKNOWN}}"
    )


def test_build_ir_batches_uses_universe_for_inclusion_and_registry_for_feeds() -> None:
    security_ids = [f"C{index:02d}" for index in range(11)]
    universe = [
        {
            "security_id": security_id,
            "ticker": security_id,
            "company_name": f"Universe {security_id}",
        }
        for security_id in reversed(security_ids)
    ]
    registry = [
        {
            "security_id": security_id,
            "company_name": f"Registry {security_id}",
            "feeds": [{"url": f"https://example.test/{security_id}"}],
        }
        for security_id in security_ids
    ] + [
        {
            "security_id": "STALE",
            "feeds": [{"url": "https://example.test/stale"}],
        }
    ]

    batches = helper.build_ir_batches(universe, registry)

    assert [len(batch) for batch in batches] == [10, 1]
    companies = [company for batch in batches for company in batch]
    assert [company["security_id"] for company in companies] == security_ids
    assert all(company["company_name"].startswith("Universe ") for company in companies)
    assert all(company["feeds"][0]["format"] == "html" for company in companies)
    assert "STALE" not in {company["security_id"] for company in companies}


def test_window_evidence_is_half_open_and_requires_full_text(tmp_path: Path) -> None:
    db = tmp_path / "invest.db"
    run_date = date(2026, 7, 27)
    start, end = helper.brief_window(run_date)
    lower = int(start.timestamp())
    upper = int(end.timestamp())
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE news (published_at INTEGER, content TEXT, summary TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO news VALUES (?, ?, ?, ?)",
            [
                (lower - 1, "too early", None, "wsj"),
                (lower, "eligible one", None, "wsj"),
                (upper - 1, "eligible two", "ready", "reuters-markets"),
                (upper - 1, "  ", None, "wsj"),
                (upper, "too late", None, "wsj"),
            ],
        )

    result = helper.window_evidence(db, run_date)

    assert result["eligible_rows"] == 2
    assert result["null_or_blank_summaries"] == 1
    assert result["sources"] == {"reuters-markets": 1, "wsj": 1}
    assert result["lower_epoch"] == lower
    assert result["upper_epoch"] == upper


def test_window_evidence_retries_transient_wal_open_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "invest.db"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE news (published_at INTEGER, content TEXT, summary TEXT, source TEXT)"
        )

    original_connect = helper.sqlite3.connect
    attempts: list[str] = []

    def flaky_connect(database: str, *args: object, **kwargs: object):
        attempts.append(database)
        if len(attempts) <= 6:
            raise sqlite3.OperationalError("unable to open database file")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(helper.sqlite3, "connect", flaky_connect)
    monkeypatch.setattr(helper.time_module, "sleep", lambda _seconds: None)

    result = helper.window_evidence(db, date(2026, 7, 27))

    assert result["eligible_rows"] == 0
    assert len(attempts) == 7
    assert all(path.endswith("?mode=rw") for path in attempts)


def test_synthesis_handoff_has_neutral_contract_fields(tmp_path: Path) -> None:
    payload = helper.synthesis_handoff(
        run_date=date(2026, 7, 27),
        db=tmp_path / "invest.db",
        prepared_evidence=tmp_path / "prepared.json",
        slack_brief_output=tmp_path / "slack.md",
        evidence_stats=tmp_path / "window.json",
        collector_stats=tmp_path / "collectors.json",
        holdings_path=tmp_path / "holdings.json",
        watchlist_path=tmp_path / "watchlist.json",
        instructions=tmp_path / "instructions.md",
        article_shortlist=tmp_path / "article-shortlist.json",
    )

    assert payload["status"] == "ready"
    assert payload["window_start"] == "2026-07-26T04:00:00-04:00"
    assert payload["window_end"] == "2026-07-27T04:00:00-04:00"
    assert payload["collector_stats"].endswith("collectors.json")
    assert payload["holdings_path"].endswith("holdings.json")
    assert payload["watchlist_path"].endswith("watchlist.json")
    assert payload["slack_brief_output"].endswith("slack.md")
    assert payload["article_shortlist"].endswith("article-shortlist.json")
    assert [key for key in payload if key.endswith("_output")] == [
        "slack_brief_output"
    ]
    assert "agent" not in " ".join(payload).lower()
    assert "openclaw" not in " ".join(payload["steps"]).lower()
    assert "minerva summarize" in " ".join(payload["steps"])
    assert "minerva brief select-news" in " ".join(payload["steps"])


def test_collector_summary_reports_missing_artifact(tmp_path: Path) -> None:
    launched = tmp_path / "launched.txt"
    launched.write_text("wsj\neconomist\n", encoding="utf-8")
    artifact_root = tmp_path / "collectors"
    (artifact_root / "wsj").mkdir(parents=True)
    (artifact_root / "wsj" / "status.json").write_text(
        json.dumps({"source_id": "wsj", "status": "ok"}), encoding="utf-8"
    )

    result = helper.collector_summary(launched, artifact_root)

    assert result["status"] == "degraded"
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["failures"][0]["source_id"] == "economist"
