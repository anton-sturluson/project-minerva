"""Focused tests for deterministic morning-brief orchestration helpers."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
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


def _selection_command(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the same helper entry point used by the synthesis agent."""
    return subprocess.run(
        [sys.executable, str(HELPER_PATH), *args], capture_output=True, text=True
    )


def _selection_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create two selection batches and boundary/premium examples."""
    db = tmp_path / "news.db"
    directory = tmp_path / "selection"
    directory.mkdir()
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE news (article_key TEXT PRIMARY KEY, url TEXT, title TEXT, "
            "source TEXT, published_at INTEGER, summary TEXT)"
        )
        rows = [
            (f"{i:064x}", f"https://example.com/{i}", f"Article {i}",
             None if i == 0 else "reuters", i % 100, "Complete summary")
            for i in range(31)
        ]
        rows.extend([
            (f"{100:064x}", "https://example.com/wsj", "WSJ", "wsj", 99, "Complete"),
            (f"{101:064x}", "https://example.com/economist", "Economist", "economist", 0, "Complete"),
            (f"{102:064x}", "https://example.com/end", "End", "reuters", 100, "Complete"),
            (f"{103:064x}", "https://example.com/before", "Before", "wsj", -1, "Complete"),
            (f"{104:064x}", "https://example.com/blank", "Blank", "reuters", 50, "   "),
        ])
        connection.executemany("INSERT INTO news VALUES (?, ?, ?, ?, ?, ?)", rows)
    result = _selection_command(
        "selection-export", str(db), "1970-01-01T00:00:00+00:00",
        "1970-01-01T00:01:40+00:00", str(directory),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2"
    return db, directory


def test_selection_commands_resolve_local_ids_and_auto_advance_premium(tmp_path: Path) -> None:
    db, directory = _selection_fixture(tmp_path)
    batches = sorted((directory / "batches").iterdir())
    first = [json.loads(line) for line in batches[0].read_text().splitlines()]
    second = [json.loads(line) for line in batches[1].read_text().splitlines()]
    assert len(first) == 30
    assert len(second) == 1
    assert first[0]["article_id"] == second[0]["article_id"] == 1
    assert "article_key" not in first[0]
    assert all(row["source"] not in ("wsj", "economist") for row in first + second)

    results = directory / "results"
    results.mkdir()
    (results / "batch-000.md").write_text('{"article_id":1,"rationale":"Relevant"}\n')
    (results / "batch-001.md").write_text('{"article_id":1,"rationale":"Relevant"}\n')
    resolved = _selection_command("selection-resolve", str(directory))
    assert resolved.returncode == 0, resolved.stderr
    keys = [json.loads(line)["article_key"] for line in resolved.stdout.splitlines()]
    with sqlite3.connect(db) as connection:
        selected = connection.execute(
            f"SELECT title FROM news WHERE article_key IN ({','.join('?' for _ in keys)}) ORDER BY title",
            keys,
        ).fetchall()
    assert selected == [("Article 0",), ("Article 30",), ("Economist",), ("WSJ",)]


@pytest.mark.parametrize(
    "result",
    [
        "", "not json\n", '{}\n', '{"article_id":true}\n',
        '{"article_id":"1"}\n', '{"article_id":0}\n', '{"article_id":31}\n',
        '{"article_id":1}\n{"article_id":1}\n',
        '{"article_id":null}\n{"article_id":1}\n',
    ],
)
def test_selection_rejects_bad_results_without_partial_keys(tmp_path: Path, result: str) -> None:
    _, directory = _selection_fixture(tmp_path)
    results = directory / "results"
    results.mkdir()
    (results / "batch-000.md").write_text(result)
    (results / "batch-001.md").write_text('{"article_id":null}\n')
    resolved = _selection_command("selection-resolve", str(directory))
    assert resolved.returncode != 0
    assert resolved.stdout == ""
    assert "batch-000.md" in resolved.stderr


def test_selection_rejects_id_from_another_batch_and_missing_result(tmp_path: Path) -> None:
    _, directory = _selection_fixture(tmp_path)
    results = directory / "results"
    results.mkdir()
    (results / "batch-000.md").write_text('{"article_id":null}\n')
    (results / "batch-001.md").write_text('{"article_id":2}\n')
    invalid = _selection_command("selection-resolve", str(directory))
    assert invalid.returncode != 0
    assert invalid.stdout == ""
    assert "batch-001.md" in invalid.stderr
    (results / "batch-001.md").unlink()
    missing = _selection_command("selection-resolve", str(directory))
    assert missing.returncode != 0
    assert missing.stdout == ""


def test_selection_accepts_no_model_selections_and_keeps_premium(tmp_path: Path) -> None:
    _, directory = _selection_fixture(tmp_path)
    results = directory / "results"
    results.mkdir()
    for batch in ("batch-000.md", "batch-001.md"):
        (results / batch).write_text('{"article_id":null,"rationale":"None"}\n')
    resolved = _selection_command("selection-resolve", str(directory))
    assert resolved.returncode == 0, resolved.stderr
    assert {json.loads(line)["article_key"] for line in resolved.stdout.splitlines()} == {
        f"{100:064x}", f"{101:064x}"
    }


def test_selection_empty_window_returns_no_keys_without_results(tmp_path: Path) -> None:
    db, _ = _selection_fixture(tmp_path)
    directory = tmp_path / "empty"
    directory.mkdir()
    exported = _selection_command(
        "selection-export", str(db), "1970-01-01T00:03:20+00:00",
        "1970-01-01T00:05:00+00:00", str(directory),
    )
    assert exported.returncode == 0, exported.stderr
    assert exported.stdout.strip() == "0"
    resolved = _selection_command("selection-resolve", str(directory))
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == ""


@pytest.mark.parametrize("stop_reason", ["completed", "end_turn", "stop"])
def test_validate_openclaw_result_accepts_exact_collector_report(
    stop_reason: str,
) -> None:
    report = {
        "status": "ok",
        "inserted": 2,
        "updated": 1,
        "duplicate": 3,
        "skipped": 4,
        "failed": 0,
    }
    payload = {
        "status": "ok",
        "result": {
            "payloads": [
                {"text": json.dumps(report, separators=(",", ":"))}
            ],
            "meta": {"aborted": False, "stopReason": stop_reason},
        },
    }

    assert helper.validate_openclaw_result(json.dumps(payload)) == "ok"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "invalid_json"),
        ("{}{}", "invalid_json"),
        ("[]", "status_error"),
        ('{"status":"error"}', "status_error"),
        ('{"status":"ok","result":{}}', "invalid_result"),
        ('{"status":"ok","result":{"payloads":[],"meta":{"aborted":true,"stopReason":"end_turn"}}}', "aborted"),
        ('{"status":"ok","result":{"payloads":[],"meta":{"error":"boom","stopReason":"end_turn"}}}', "agent_error"),
        ('{"status":"ok","result":{"payloads":[],"meta":{"timeoutPhase":"model","stopReason":"end_turn"}}}', "timeout"),
        ('{"status":"ok","result":{"payloads":[{"isError":true}],"meta":{"stopReason":"end_turn"}}}', "error_payload"),
        ('{"status":"ok","result":{"payloads":[],"meta":{"stopReason":"length"}}}', "incomplete"),
    ],
)
def test_validate_openclaw_result_rejects_incomplete_or_invalid_results(
    text: str, expected: str
) -> None:
    assert helper.validate_openclaw_result(text) == expected


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ("", "invalid_report"),
        ("not json", "invalid_report"),
        ('{"status":"ok"}', "invalid_report"),
        ('{"status":"ok","inserted":0,"updated":0,"duplicate":0,"skipped":0,"failed":0,"note":"extra"}', "invalid_report"),
        ('{"status":"unknown","inserted":0,"updated":0,"duplicate":0,"skipped":0,"failed":0}', "invalid_report"),
        ('{"status":"failed","inserted":0,"updated":0,"duplicate":0,"skipped":0,"failed":0}', "collector_failed"),
        ('{"status":"ok","inserted":0,"updated":0,"duplicate":0,"skipped":0,"failed":1}', "collector_failed"),
        ('{"status":"ok","inserted":-1,"updated":0,"duplicate":0,"skipped":0,"failed":0}', "invalid_counts"),
        ('{"status":"ok","inserted":true,"updated":0,"duplicate":0,"skipped":0,"failed":0}', "invalid_counts"),
    ],
)
def test_validate_openclaw_result_rejects_failed_or_malformed_collector_reports(
    report: str, expected: str
) -> None:
    payload = {
        "status": "ok",
        "result": {
            "payloads": [{"text": report}],
            "meta": {"stopReason": "end_turn"},
        },
    }

    assert helper.validate_openclaw_result(json.dumps(payload)) == expected


def test_validate_openclaw_result_rejects_missing_or_ambiguous_reports() -> None:
    def envelope(payloads: list[dict[str, str]]) -> str:
        return json.dumps(
            {
                "status": "ok",
                "result": {
                    "payloads": payloads,
                    "meta": {"stopReason": "end_turn"},
                },
            }
        )

    valid_report = '{"status":"ok","inserted":0,"updated":0,"duplicate":0,"skipped":0,"failed":0}'
    assert helper.validate_openclaw_result(envelope([])) == "invalid_report"
    assert (
        helper.validate_openclaw_result(
            envelope([{"text": valid_report}, {"text": valid_report}])
        )
        == "invalid_report"
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
    )

    assert payload["status"] == "ready"
    assert payload["window_start"] == "2026-07-26T04:00:00-04:00"
    assert payload["window_end"] == "2026-07-27T04:00:00-04:00"
    assert payload["collector_stats"].endswith("collectors.json")
    assert payload["holdings_path"].endswith("holdings.json")
    assert payload["watchlist_path"].endswith("watchlist.json")
    assert payload["slack_brief_output"].endswith("slack.md")
    assert [key for key in payload if key.endswith("_output")] == [
        "slack_brief_output"
    ]
    assert "agent" not in " ".join(payload).lower()
    assert "minerva summarize" in " ".join(payload["steps"])


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
