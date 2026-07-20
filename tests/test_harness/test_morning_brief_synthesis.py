"""Focused tests for isolated post-ingest morning-brief synthesis."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from harness.morning_brief_synthesis import (
    MAX_ARTICLE_CONTENT_CHARS,
    SynthesisError,
    main,
    parse_shortlist_output,
    synthesize_morning_brief,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = date(2026, 7, 19)
FINAL_BRIEF = (
    "*Worth Knowing Today*\n"
    "• Material development <https://example.com/story|Reuters>\n\n"
    "*Portfolio / Watchlist Events*\n"
    "• Portfolio item <https://example.com/ir|PORT IR>"
)


def _epoch(day: str) -> int:
    return int(datetime.fromisoformat(f"{day}T12:00:00+00:00").timestamp())


def _make_inputs(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "invest.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE news (
            article_key TEXT PRIMARY KEY,
            published_at INTEGER NOT NULL,
            published_at_raw TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            summary TEXT,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            section TEXT,
            collected_at TEXT NOT NULL
        );
        """
    )
    rows = [
        (
            "key-reuters",
            _epoch("2026-07-19"),
            "2026-07-19T08:00:00Z",
            "Rates move after inflation data",
            "UNSELECTED-CONTENT",
            "UNSELECTED-SUMMARY",
            "reuters",
            "https://example.com/story",
            "markets",
            "2026-07-19T09:00:00Z",
        ),
        (
            "key-ir",
            _epoch("2026-07-18"),
            "July 18, 2026 4:05 PM ET",
            "Portfolio company announces acquisition",
            "IR full content " + ("x" * (MAX_ARTICLE_CONTENT_CHARS + 500)),
            None,
            "ir-PORT",
            "https://example.com/ir",
            "press release",
            "2026-07-19T09:01:00-04:00",
        ),
        (
            "key-ft",
            _epoch("2026-07-19"),
            "2026-07-19",
            "Manufacturing survey improves",
            "FT-CONTENT",
            "FT-SUMMARY",
            "ft",
            "https://example.com/ft",
            "economy",
            "2026-07-19T09:02:00Z",
        ),
        (
            "key-old-run",
            _epoch("2026-07-19"),
            "2026-07-19",
            "Previously collected title",
            "OLD-CONTENT",
            "OLD-SUMMARY",
            "wsj",
            "https://example.com/old",
            "markets",
            "2026-07-18T23:59:00Z",
        ),
    ]
    connection.executemany(
        """
        INSERT INTO news (
            article_key, published_at, published_at_raw, title, content, summary,
            source, url, section, collected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    connection.close()

    prepared_path = tmp_path / "prepared-evidence.json"
    prepared_path.write_text(
        json.dumps(
            {
                "date": RUN_DATE.isoformat(),
                "universe": [
                    {
                        "security_id": "PORT",
                        "ticker": "PORT",
                        "source_kind": "holding",
                    }
                ],
                "events": [
                    {
                        "source": "earnings",
                        "source_name": "earnings",
                        "event_type": "earnings",
                        "event_date": RUN_DATE.isoformat(),
                        "security_id": "PORT",
                        "relationship": "monitored",
                        "group": "company-specific",
                        "headline": "PORT reports before the open",
                        "timing": "bmo",
                        "reference_url": "https://example.com/calendar",
                        "summary": "Consensus expects revenue growth.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return db_path, prepared_path


def _payload_from_prompt(prompt: str, marker: str) -> dict:
    return json.loads(prompt.split(marker, 1)[1].strip())


def test_all_fresh_titles_reach_pass_1_and_only_valid_shortlist_reaches_pass_2(
    tmp_path: Path,
) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    prompts: list[str] = []
    model_calls: list[dict] = []

    def model_call(**kwargs) -> str:
        model_calls.append(kwargs)
        prompt = kwargs["prompt"]
        prompts.append(prompt)
        if "PASS 1" in prompt:
            universe = _payload_from_prompt(prompt, "TITLE_UNIVERSE_JSON:")
            article_ids = [
                item["id"] for item in universe["candidates"] if item["kind"] == "article"
            ]
            event_id = next(
                item["id"] for item in universe["candidates"] if item["kind"] == "event"
            )
            # Fenced JSON, duplicate IDs, and an invented ID are tolerated, but
            # deterministic validation must keep only supplied universe IDs.
            return (
                "shortlist follows\n```json\n"
                + json.dumps(
                    {
                        "shortlist_ids": [
                            article_ids[1],
                            event_id,
                            "article:not-in-universe",
                            article_ids[1],
                        ]
                    }
                )
                + "\n```"
            )
        return FINAL_BRIEF

    brief = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        model_call=model_call,
    )

    assert brief == FINAL_BRIEF
    assert len(prompts) == 2
    assert {call["model"] for call in model_calls} == {"gpt-5.6-sol"}
    assert {call["reasoning"] for call in model_calls} == {"high"}
    title_universe = _payload_from_prompt(prompts[0], "TITLE_UNIVERSE_JSON:")
    article_records = [
        item for item in title_universe["candidates"] if item["kind"] == "article"
    ]
    assert {item["title"] for item in article_records} == {
        "Rates move after inflation data",
        "Portfolio company announces acquisition",
        "Manufacturing survey improves",
    }
    assert "Previously collected title" not in prompts[0]
    assert any(item["source"] == "ir-PORT" for item in article_records)
    assert all(
        {"id", "article_key", "source", "published", "title"} <= item.keys()
        for item in article_records
    )
    assert "UNSELECTED-SUMMARY" not in prompts[0]
    assert "UNSELECTED-CONTENT" not in prompts[0]

    shortlisted = _payload_from_prompt(prompts[1], "SHORTLISTED_EVIDENCE_JSON:")
    assert shortlisted["shortlisted_count"] == 2
    assert [item["kind"] for item in shortlisted["evidence"]] == ["article", "event"]
    assert {item["id"] for item in shortlisted["evidence"]} == {
        "article:key-ir",
        next(
            item["id"]
            for item in title_universe["candidates"]
            if item["kind"] == "event"
        ),
    }
    assert "article:not-in-universe" not in prompts[1]
    assert "UNSELECTED-SUMMARY" not in prompts[1]
    fallback = shortlisted["evidence"][0]
    assert fallback["evidence_kind"] == "bounded_content_fallback"
    assert len(fallback["evidence"]) <= MAX_ARTICLE_CONTENT_CHARS + 50


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"ids":["article:a","event:b"]}', ["article:a", "event:b"]),
        (
            '```json\n{"selected_ids":["article:a","article:a"]}\n```',
            ["article:a"],
        ),
        (
            'Here is the broad list: {"shortlist_ids":["event:b"]} done.',
            ["event:b"],
        ),
        ('[{"id":"article:a"},{"id":"event:b"}]', ["article:a", "event:b"]),
        (
            '{"article_ids":["article:a"],"event_ids":["event:b"]}',
            ["article:a", "event:b"],
        ),
    ],
)
def test_broad_shortlist_parsing_is_robust(raw: str, expected: list[str]) -> None:
    assert parse_shortlist_output(raw) == expected


def test_invalid_pass_1_output_is_retried_once(tmp_path: Path) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    pass_1_attempts = 0

    def model_call(**kwargs) -> str:
        nonlocal pass_1_attempts
        if "PASS 1" in kwargs["prompt"]:
            pass_1_attempts += 1
            if pass_1_attempts == 1:
                return "not JSON"
            universe = _payload_from_prompt(
                kwargs["prompt"], "TITLE_UNIVERSE_JSON:"
            )
            return json.dumps({"ids": [universe["candidates"][0]["id"]]})
        return FINAL_BRIEF

    result = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        model_call=model_call,
    )

    assert result == FINAL_BRIEF
    assert pass_1_attempts == 2


def test_empty_shortlist_for_nonempty_universe_fails_after_retry(tmp_path: Path) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    calls = 0

    def model_call(**kwargs) -> str:
        nonlocal calls
        calls += 1
        return '{"ids":[]}'

    with pytest.raises(SynthesisError, match="no valid IDs"):
        synthesize_morning_brief(
            db_path=db_path,
            prepared_path=prepared_path,
            run_date=RUN_DATE,
            model_call=model_call,
        )

    assert calls == 2


def test_empty_universe_preserves_explicit_evidence_thin_brief(tmp_path: Path) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    connection = sqlite3.connect(db_path)
    connection.execute("DELETE FROM news")
    connection.commit()
    connection.close()
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    prepared["events"] = []
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    prompts: list[str] = []
    thin_brief = (
        "*Worth Knowing Today*\n"
        "• Evidence is thin; no supported material items."
    )

    def model_call(**kwargs) -> str:
        prompts.append(kwargs["prompt"])
        if "PASS 1" in kwargs["prompt"]:
            return '{"ids":[]}'
        return thin_brief

    result = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        model_call=model_call,
    )

    assert result == thin_brief
    shortlisted = _payload_from_prompt(prompts[1], "SHORTLISTED_EVIDENCE_JSON:")
    assert shortlisted == {
        "run_date": RUN_DATE.isoformat(),
        "shortlisted_count": 0,
        "evidence": [],
    }


def test_cli_stdout_and_artifact_are_final_text_only_and_no_temp_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    output_path = tmp_path / "report" / "notes" / "slack-brief.md"
    system_tmp = tmp_path / "system-tmp"
    system_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(system_tmp))

    def model_call(**kwargs) -> str:
        if "PASS 1" in kwargs["prompt"]:
            universe = _payload_from_prompt(kwargs["prompt"], "TITLE_UNIVERSE_JSON:")
            return json.dumps({"ids": [universe["candidates"][0]["id"]]})
        return f"```mrkdwn\n{FINAL_BRIEF}\n```"

    status = main(
        [
            "--date",
            RUN_DATE.isoformat(),
            "--db",
            str(db_path),
            "--prepared-evidence",
            str(prepared_path),
            "--output",
            str(output_path),
        ],
        model_call=model_call,
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == f"{FINAL_BRIEF}\n"
    assert captured.err == ""
    assert output_path.read_text(encoding="utf-8") == f"{FINAL_BRIEF}\n"
    assert not list(system_tmp.rglob("*.json"))
    assert not any(system_tmp.iterdir())


def _write_fake_wrapper_commands(tmp_path: Path, *, pipeline_status: int) -> tuple[Path, Path]:
    pipeline = tmp_path / "fake-pipeline.sh"
    pipeline.write_text(
        "#!/usr/bin/env bash\n"
        "echo pipeline >> \"$ORDER_LOG\"\n"
        "echo collection-log-line\n"
        + (
            "mkdir -p \"$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/"
            f"{RUN_DATE.isoformat()}/data/rendered\"\n"
            "echo evidence > \"$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/"
            f"{RUN_DATE.isoformat()}/data/rendered/test.md\"\n"
            if pipeline_status == 0
            else ""
        )
        + f"exit {pipeline_status}\n",
        encoding="utf-8",
    )
    pipeline.chmod(0o755)

    synthesis = tmp_path / "fake-synthesis.sh"
    synthesis.write_text(
        "#!/usr/bin/env bash\n"
        "echo sol >> \"$ORDER_LOG\"\n"
        "printf '%s\\n' '*Worth Knowing Today*' '• item'\n",
        encoding="utf-8",
    )
    synthesis.chmod(0o755)
    return pipeline, synthesis


def _wrapper_env(
    tmp_path: Path, pipeline: Path, synthesis: Path, order_log: Path
) -> dict[str, str]:
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(fake_home),
            "ORDER_LOG": str(order_log),
            "MINERVA_MORNING_BRIEF_PIPELINE_SCRIPT": str(pipeline),
            "MINERVA_SYNTHESIS_RUNNER": str(synthesis),
            "MINERVA_WORKSPACE_ROOT": str(tmp_path / "workspace"),
            "MINERVA_MORNING_BRIEF_LOG": str(tmp_path / "logs" / "pipeline.log"),
            "MINERVA_MORNING_BRIEF_SYNTHESIS_LOG": str(
                tmp_path / "logs" / "synthesis.log"
            ),
        }
    )
    return env


def test_wrapper_invokes_sol_only_after_pipeline_success(tmp_path: Path) -> None:
    order_log = tmp_path / "order.log"
    pipeline, synthesis = _write_fake_wrapper_commands(tmp_path, pipeline_status=0)

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "run_morning_brief_with_synthesis.sh"),
            RUN_DATE.isoformat(),
        ],
        cwd=REPO_ROOT,
        env=_wrapper_env(tmp_path, pipeline, synthesis, order_log),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert order_log.read_text(encoding="utf-8").splitlines() == ["pipeline", "sol"]
    assert result.stdout == "*Worth Knowing Today*\n• item\n"
    assert result.stderr == ""
    assert not (tmp_path / "logs" / "pipeline.log").exists()
    assert not (tmp_path / "logs" / "synthesis.log").exists()


def test_wrapper_retries_pipeline_once_before_invoking_sol(tmp_path: Path) -> None:
    order_log = tmp_path / "order.log"
    attempt_file = tmp_path / "attempt"
    _, synthesis = _write_fake_wrapper_commands(tmp_path, pipeline_status=0)
    pipeline = tmp_path / "flaky-pipeline.sh"
    pipeline.write_text(
        "#!/usr/bin/env bash\n"
        "echo pipeline >> \"$ORDER_LOG\"\n"
        "attempt=1\n"
        "[[ -f \"$ATTEMPT_FILE\" ]] && attempt=2\n"
        "touch \"$ATTEMPT_FILE\"\n"
        "if [[ \"$attempt\" -eq 1 ]]; then exit 17; fi\n"
        "mkdir -p \"$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/"
        f"{RUN_DATE.isoformat()}/data/rendered\"\n"
        "echo evidence > \"$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/"
        f"{RUN_DATE.isoformat()}/data/rendered/test.md\"\n",
        encoding="utf-8",
    )
    pipeline.chmod(0o755)
    env = _wrapper_env(tmp_path, pipeline, synthesis, order_log)
    env["ATTEMPT_FILE"] = str(attempt_file)

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "run_morning_brief_with_synthesis.sh"),
            RUN_DATE.isoformat(),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert order_log.read_text(encoding="utf-8").splitlines() == [
        "pipeline",
        "pipeline",
        "sol",
    ]


def test_pipeline_failure_prevents_sol_invocation(tmp_path: Path) -> None:
    order_log = tmp_path / "order.log"
    pipeline, synthesis = _write_fake_wrapper_commands(tmp_path, pipeline_status=17)

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "run_morning_brief_with_synthesis.sh"),
            RUN_DATE.isoformat(),
        ],
        cwd=REPO_ROOT,
        env=_wrapper_env(tmp_path, pipeline, synthesis, order_log),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert order_log.read_text(encoding="utf-8").splitlines() == [
        "pipeline",
        "pipeline",
    ]
    assert result.stdout == ""
    assert "Sol was not invoked" in result.stderr
    assert "pipeline log:" in result.stderr
