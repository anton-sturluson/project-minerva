"""Focused tests for isolated post-ingest morning-brief synthesis."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from harness.morning_brief_synthesis import (
    MAX_ARTICLE_CONTENT_CHARS,
    MAX_SHORTLIST_IDS,
    CandidateTitle,
    SynthesisError,
    build_source_collection_line,
    main,
    normalize_final_brief,
    parse_openclaw_json_output,
    parse_shortlist_output,
    synthesize_morning_brief,
    validate_shortlist_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = date(2026, 7, 19)
MODEL_BRIEF = (
    "*Market Snapshot*\n"
    "• SPY moved 1.25% <https://example.com/spy|Market>\n\n"
    "*Portfolio / Watchlist Events*\n"
    "• Portfolio item <https://example.com/ir|PORT IR>\n\n"
    "*Worth Knowing Today*\n"
    "• Material development <https://example.com/story|Reuters>"
)
SOURCE_COLLECTION_LINE = (
    "*Source Collection:* 5 article records — Reuters 2 · CNBC 1 · Economist 0 · "
    "WSJ 0 · FT 1 · Company IR 1 · BLS/BEA/Fed 0; plus 1 market-price observation."
)
EMPTY_SOURCE_COLLECTION_LINE = (
    "*Source Collection:* 0 article records — Reuters 0 · Economist 0 · WSJ 0 · "
    "Company IR 0 · BLS/BEA/Fed 0; plus 0 market-price observations."
)
FINAL_BRIEF = f"{SOURCE_COLLECTION_LINE}\n{MODEL_BRIEF}"


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
                    },
                    {
                        "security_id": "WATCH",
                        "ticker": "WATCH",
                        "source_kind": "watchlist",
                    },
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
                    },
                    {
                        "source": "ir",
                        "source_name": "ir",
                        "event_type": "company-news",
                        "event_date": RUN_DATE.isoformat(),
                        "security_id": "WATCH",
                        "relationship": "monitored",
                        "group": "company-specific",
                        "headline": "WATCH schedules an investor day",
                        "reference_url": "https://example.com/watch-ir",
                        "summary": "The prepared event gives the scheduled time.",
                        "news_source": "CNBC",
                    },
                    {
                        "source": "market",
                        "source_name": "market",
                        "event_type": "market",
                        "event_date": RUN_DATE.isoformat(),
                        "security_id": "SPY",
                        "relationship": "market",
                        "group": "market-context",
                        "headline": "SPY moved 1.25%",
                        "change_pct": 1.25,
                        "reference_url": "https://example.com/spy",
                    },
                    {
                        "source": "macro",
                        "source_name": "macro",
                        "event_type": "macro-release",
                        "event_date": RUN_DATE.isoformat(),
                        "security_id": "",
                        "relationship": "market",
                        "group": "macro-policy",
                        "headline": "Employment report due at 08:30 ET",
                        "reference_url": "https://example.com/macro",
                        "summary": "The release is scheduled for 08:30 ET.",
                    },
                    {
                        "source": "market",
                        "source_name": "market",
                        "event_type": "market-news",
                        "event_date": RUN_DATE.isoformat(),
                        "security_id": "",
                        "relationship": "market",
                        "group": "market-context",
                        "headline": "Thin wire record covers a bank merger",
                        "reference_url": "https://example.com/market-news",
                        "summary": "A short prepared summary of the merger report.",
                        "news_source": "Reuters",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return db_path, prepared_path


def _payload_from_prompt(prompt: str, marker: str) -> dict:
    return json.loads(prompt.split(marker, 1)[1].strip())


def test_source_collection_counts_all_article_records_without_double_counting() -> None:
    article_url = "https://example.com/reuters-exclusive"
    candidates = [
        CandidateTitle(
            id="article:reuters",
            kind="article",
            title="Rates move after inflation data",
            source="reuters-markets",
            published=RUN_DATE.isoformat(),
            article_key="reuters",
            metadata={"url": article_url, "published_at": RUN_DATE.isoformat()},
        ),
        CandidateTitle(
            id="article:reuters-update",
            kind="article",
            title="Rates move after inflation data — update",
            source="reuters-markets",
            published=RUN_DATE.isoformat(),
            article_key="reuters-update",
            metadata={"url": article_url, "published_at": RUN_DATE.isoformat()},
        ),
        CandidateTitle(
            id="article:economist",
            kind="article",
            title="The productivity puzzle",
            source="economist-business",
            published=RUN_DATE.isoformat(),
            article_key="economist",
            metadata={"url": "https://example.com/economist"},
        ),
        CandidateTitle(
            id="article:ir-port",
            kind="article",
            title="PORT announces an acquisition",
            source="ir-PORT",
            published=RUN_DATE.isoformat(),
            article_key="ir-port",
            metadata={"url": "https://example.com/port"},
        ),
        CandidateTitle(
            id="article:ir-watch",
            kind="article",
            title="WATCH schedules an investor day",
            source="ir-WATCH",
            published=RUN_DATE.isoformat(),
            article_key="ir-watch",
            metadata={"url": "https://example.com/watch"},
        ),
        CandidateTitle(
            id="article:bls",
            kind="article",
            title="Employment situation released",
            source="bls-calendar",
            published=RUN_DATE.isoformat(),
            article_key="bls",
            metadata={"url": "https://example.com/bls"},
        ),
        CandidateTitle(
            id="event:duplicate-reuters",
            kind="event",
            title="Rates move after inflation data",
            source="market",
            published=RUN_DATE.isoformat(),
            metadata={
                "event_type": "market-news",
                "news_source": "Reuters",
                "reference_url": f"{article_url}/?utm_source=finnhub",
            },
        ),
        CandidateTitle(
            id="event:yahoo",
            kind="event",
            title="A distinct market story",
            source="market",
            published=RUN_DATE.isoformat(),
            metadata={
                "event_type": "market-news",
                "news_source": "Yahoo Finance",
                "reference_url": "https://example.com/yahoo",
            },
        ),
        CandidateTitle(
            id="event:bloomberg",
            kind="event",
            title="A distinct company story",
            source="market",
            published=RUN_DATE.isoformat(),
            metadata={
                "event_type": "company-news",
                "news_source": "Bloomberg News",
                "reference_url": "https://example.com/bloomberg",
            },
        ),
        CandidateTitle(
            id="event:spy-one",
            kind="event",
            title="SPY moved 1.25%",
            source="market",
            published=RUN_DATE.isoformat(),
            metadata={"event_type": "market", "security_id": "SPY"},
        ),
        CandidateTitle(
            id="event:spy-duplicate",
            kind="event",
            title="SPY moved 1.25%",
            source="market",
            published=RUN_DATE.isoformat(),
            metadata={"event_type": "market", "security_id": "SPY"},
        ),
        CandidateTitle(
            id="event:qqq",
            kind="event",
            title="QQQ moved 1.50%",
            source="market",
            published=RUN_DATE.isoformat(),
            metadata={"event_type": "market", "security_id": "QQQ"},
        ),
        CandidateTitle(
            id="event:earnings",
            kind="event",
            title="PORT reports before the open",
            source="earnings",
            published=RUN_DATE.isoformat(),
            metadata={"event_type": "earnings", "security_id": "PORT"},
        ),
    ]

    line = build_source_collection_line(candidates)

    assert line == (
        "*Source Collection:* 8 article records — Reuters 2 · Yahoo 1 · Bloomberg 1 · "
        "Economist 1 · WSJ 0 · Company IR 2 · BLS/BEA/Fed 1; plus 2 "
        "market-price observations."
    )
    assert "earnings" not in line.casefold()
    assert "\n" not in line
    assert not line.startswith(("•", "-", "* "))


def test_weighted_routing_partitions_pass_1_and_labels_all_pass_2_evidence(
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
                item["id"]
                for item in universe["candidates"]
                if item["kind"] == "article"
            ]
            market_news_id = next(
                item["id"]
                for item in universe["candidates"]
                if item.get("event_type") == "market-news"
            )
            # Fenced JSON, reasons, duplicate IDs, and an invented ID are
            # tolerated; validation keeps only supplied IDs.
            return (
                "shortlist follows\n```json\n"
                + json.dumps(
                    {
                        "selections": [
                            {
                                "id": article_ids[1],
                                "reason": "Richer IR evidence; punctuation: [] {}.",
                            },
                            {
                                "id": market_news_id,
                                "reason": "Distinct merger story.",
                            },
                            {
                                "id": "article:not-in-universe",
                                "reason": "Invented and rejected.",
                            },
                            {
                                "id": article_ids[1],
                                "reason": "Duplicate and rejected.",
                            },
                        ]
                    }
                )
                + "\n```"
            )
        return MODEL_BRIEF

    brief = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        model_call=model_call,
    )

    assert brief == FINAL_BRIEF
    assert brief.startswith(f"{SOURCE_COLLECTION_LINE}\n*Market Snapshot*")
    assert brief.count("*Source Collection:*") == 1
    assert not brief.startswith(("•", "-", "* "))
    assert len(prompts) == 2
    assert {call["model"] for call in model_calls} == {"gpt-5.6-sol"}
    assert {call["reasoning"] for call in model_calls} == {"high"}
    session_keys = {call["session_key"] for call in model_calls}
    assert len(session_keys) == 1
    assert next(iter(session_keys)).startswith(
        f"daily-news-sol-{RUN_DATE.isoformat()}-"
    )
    assert all("DO NOT use or call any tools" in prompt for prompt in prompts)
    assert all(
        "DO NOT browse, search, or fetch anything" in prompt for prompt in prompts
    )
    assert all(
        "DO NOT read, create, edit, or write any files" in prompt for prompt in prompts
    )

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
    market_news_records = [
        item
        for item in title_universe["candidates"]
        if item.get("event_type") == "market-news"
    ]
    assert len(market_news_records) == 1
    assert market_news_records[0]["article_candidate_class"] == (
        "secondary_prepared_market_news"
    )
    assert title_universe["candidate_count"] == 4
    assert "PORT reports before the open" not in prompts[0]
    assert "WATCH schedules an investor day" not in prompts[0]
    assert "SPY moved 1.25%" not in prompts[0]
    assert "Employment report due at 08:30 ET" not in prompts[0]
    assert "UNSELECTED-SUMMARY" not in prompts[0]
    assert "UNSELECTED-CONTENT" not in prompts[0]
    assert "targeting 15-25" in prompts[0]
    assert "HARD MAXIMUM: select no more than 30 IDs" in prompts[0]
    assert "Semantically deduplicate" in prompts[0]
    assert "Reject lifestyle" in prompts[0]

    shortlisted = _payload_from_prompt(prompts[1], "SHORTLISTED_EVIDENCE_JSON:")
    assert shortlisted["shortlisted_count"] == 2
    assert shortlisted["automatic_event_count"] == 4
    assert shortlisted["evidence_count"] == 6
    evidence = shortlisted["evidence"]
    assert [item["routing_class"] for item in evidence[:2]] == [
        "selected_article",
        "selected_article",
    ]
    auto_by_title = {item["title"]: item for item in evidence[2:]}
    assert set(auto_by_title) == {
        "PORT reports before the open",
        "WATCH schedules an investor day",
        "SPY moved 1.25%",
        "Employment report due at 08:30 ET",
    }
    assert auto_by_title["PORT reports before the open"]["routing_class"] == (
        "auto_portfolio_watchlist"
    )
    assert auto_by_title["WATCH schedules an investor day"]["routing_class"] == (
        "auto_portfolio_watchlist"
    )
    assert auto_by_title["SPY moved 1.25%"]["routing_class"] == "auto_market_move"
    assert auto_by_title["Employment report due at 08:30 ET"]["routing_class"] == (
        "other_auto_event"
    )
    selected_market_news = next(
        item
        for item in evidence
        if item.get("article_candidate_class") == "secondary_prepared_market_news"
    )
    assert selected_market_news["url"] == "https://example.com/market-news"
    assert selected_market_news["evidence"] == (
        "A short prepared summary of the merger report."
    )
    assert selected_market_news["evidence_kind"] == "prepared_event"
    assert "article:not-in-universe" not in prompts[1]
    assert "UNSELECTED-SUMMARY" not in prompts[1]
    fallback = evidence[0]
    assert fallback["evidence_kind"] == "bounded_content_fallback"
    assert len(fallback["evidence"]) <= MAX_ARTICLE_CONTENT_CHARS + 50
    assert "represent EVERY record" in prompts[1]
    assert "exactly ONE compact bullet/line" in prompts[1]
    assert "Do not write a Source Collection line or any source counts" in prompts[1]
    assert (
        "Use section order: *Market Snapshot* first when its routed evidence exists, "
        "then *Portfolio / Watchlist Events* when its routed evidence exists, then "
        "*Worth Knowing Today* (required)"
    ) in prompts[1]
    assert (
        "Emit this section if and only if auto_portfolio_watchlist evidence exists."
        in prompts[1]
    )
    assert (
        "Emit this section if and only if auto_market_move evidence exists."
        in prompts[1]
    )


def test_final_brief_validation_enforces_market_portfolio_worth_order() -> None:
    assert (
        normalize_final_brief(
            MODEL_BRIEF,
            has_market_move_evidence=True,
            has_portfolio_watchlist_evidence=True,
        )
        == MODEL_BRIEF
    )
    prior_order = (
        "*Worth Knowing Today*\n• Article\n\n"
        "*Portfolio / Watchlist Events*\n• Portfolio event\n\n"
        "*Market Snapshot*\n• Market move"
    )

    with pytest.raises(
        SynthesisError,
        match=(
            "expected Market Snapshot, Portfolio / Watchlist Events, then Worth "
            "Knowing Today"
        ),
    ):
        normalize_final_brief(
            prior_order,
            has_market_move_evidence=True,
            has_portfolio_watchlist_evidence=True,
        )


def test_model_cannot_add_a_second_source_collection_line() -> None:
    with pytest.raises(SynthesisError, match="deterministic code owns"):
        normalize_final_brief(
            f"*Source Collection:* invented counts\n{MODEL_BRIEF}",
            has_market_move_evidence=True,
            has_portfolio_watchlist_evidence=True,
        )


def test_model_cannot_put_a_preamble_between_collection_and_market() -> None:
    with pytest.raises(SynthesisError, match="text before its first Slack section"):
        normalize_final_brief(
            f"Good morning.\n\n{MODEL_BRIEF}",
            has_market_move_evidence=True,
            has_portfolio_watchlist_evidence=True,
        )


@pytest.mark.parametrize(
    (
        "brief",
        "has_market_move_evidence",
        "has_portfolio_watchlist_evidence",
        "message",
    ),
    [
        (
            "*Worth Knowing Today*\n• Article",
            True,
            False,
            "omitted required Market Snapshot section",
        ),
        (
            "*Market Snapshot*\n• Move\n\n*Worth Knowing Today*\n• Article",
            False,
            False,
            "included Market Snapshot section without auto_market_move evidence",
        ),
        (
            "*Worth Knowing Today*\n• Article",
            False,
            True,
            "omitted required Portfolio / Watchlist Events section",
        ),
        (
            "*Portfolio / Watchlist Events*\n• Event\n\n"
            "*Worth Knowing Today*\n• Article",
            False,
            False,
            "included Portfolio / Watchlist Events section without "
            "auto_portfolio_watchlist evidence",
        ),
    ],
)
def test_final_brief_sections_follow_automatic_evidence(
    brief: str,
    has_market_move_evidence: bool,
    has_portfolio_watchlist_evidence: bool,
    message: str,
) -> None:
    with pytest.raises(SynthesisError, match=re.escape(message)):
        normalize_final_brief(
            brief,
            has_market_move_evidence=has_market_move_evidence,
            has_portfolio_watchlist_evidence=has_portfolio_watchlist_evidence,
        )


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
        (
            json.dumps(
                {
                    "selections": [
                        {
                            "id": "article:a",
                            "reason": 'JSON-safe reason with quotes: "important".',
                        },
                        {"id": "event:b", "reason": "Distinct read-through."},
                    ]
                }
            ),
            ["article:a", "event:b"],
        ),
    ],
)
def test_broad_shortlist_parsing_is_robust(raw: str, expected: list[str]) -> None:
    assert parse_shortlist_output(raw) == expected


def test_shortlist_validation_rejects_more_than_hard_maximum() -> None:
    candidates = [
        CandidateTitle(
            id=f"article:{index}",
            kind="article",
            title=f"Article {index}",
            source="wire",
            published=RUN_DATE.isoformat(),
            article_key=str(index),
        )
        for index in range(MAX_SHORTLIST_IDS + 5)
    ]

    with pytest.raises(
        SynthesisError,
        match=rf"returned {MAX_SHORTLIST_IDS + 5} valid IDs; hard maximum is {MAX_SHORTLIST_IDS}",
    ):
        validate_shortlist_ids(
            [candidate.id for candidate in reversed(candidates)], candidates
        )


def test_invalid_pass_1_output_is_retried_once(tmp_path: Path) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    pass_1_attempts = 0

    def model_call(**kwargs) -> str:
        nonlocal pass_1_attempts
        if "PASS 1" in kwargs["prompt"]:
            pass_1_attempts += 1
            if pass_1_attempts == 1:
                return "not JSON"
            universe = _payload_from_prompt(kwargs["prompt"], "TITLE_UNIVERSE_JSON:")
            return json.dumps({"ids": [universe["candidates"][0]["id"]]})
        return MODEL_BRIEF

    result = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        model_call=model_call,
    )

    assert result == FINAL_BRIEF
    assert pass_1_attempts == 2


def test_empty_shortlist_for_nonempty_universe_fails_after_retry(
    tmp_path: Path,
) -> None:
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
        "*Worth Knowing Today*\n• Evidence is thin; no supported material items."
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

    assert result == f"{EMPTY_SOURCE_COLLECTION_LINE}\n{thin_brief}"
    shortlisted = _payload_from_prompt(prompts[1], "SHORTLISTED_EVIDENCE_JSON:")
    assert shortlisted == {
        "run_date": RUN_DATE.isoformat(),
        "shortlisted_count": 0,
        "automatic_event_count": 0,
        "evidence_count": 0,
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

    model_calls: list[dict] = []

    def model_call(**kwargs) -> str:
        model_calls.append(kwargs)
        if "PASS 1" in kwargs["prompt"]:
            universe = _payload_from_prompt(kwargs["prompt"], "TITLE_UNIVERSE_JSON:")
            return json.dumps({"ids": [universe["candidates"][0]["id"]]})
        return f"```mrkdwn\n{MODEL_BRIEF}\n```"

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
            "--session-key",
            "daily-news-sol-manual-test",
        ],
        model_call=model_call,
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == f"{FINAL_BRIEF}\n"
    assert captured.err == ""
    assert {call["session_key"] for call in model_calls} == {
        "daily-news-sol-manual-test"
    }
    assert output_path.read_text(encoding="utf-8") == f"{FINAL_BRIEF}\n"
    assert not list(system_tmp.rglob("*.json"))
    assert not any(system_tmp.iterdir())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"payloads":[{"text":"top-level reply"}]}', "top-level reply"),
        (
            '{"status":"ok","result":{"payloads":[{"text":"first"},{"text":"second"}]}}',
            "first\n\nsecond",
        ),
        (
            '{"payloads":[{"isReasoning":true,"text":"hidden"},{"text":"visible"}]}',
            "visible",
        ),
    ],
)
def test_openclaw_json_payload_parsing(raw: str, expected: str) -> None:
    assert parse_openclaw_json_output(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "empty JSON stdout"),
        ("not-json", "invalid JSON stdout"),
        ('{"status":"error","summary":"gateway exploded"}', "gateway exploded"),
        ('{"result":{}}', "contained no payloads"),
        ('{"payloads":{}}', "payloads` must be a list"),
        ('{"payloads":[{"text":""}]}', "no visible text payload"),
        (
            '{"payloads":[{"isError":true,"text":"model unavailable"}]}',
            "model unavailable",
        ),
    ],
)
def test_openclaw_json_payload_errors_are_clear(raw: str, message: str) -> None:
    with pytest.raises(SynthesisError, match=message):
        parse_openclaw_json_output(raw)


def test_default_workflow_uses_two_main_agent_turns_in_one_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], *, capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is False
        commands.append(command)
        prompt = command[command.index("--message") + 1]
        if "PASS 1" in prompt:
            universe = _payload_from_prompt(prompt, "TITLE_UNIVERSE_JSON:")
            reply = json.dumps({"ids": [universe["candidates"][0]["id"]]})
            stdout = json.dumps({"payloads": [{"text": reply}]})
        else:
            stdout = json.dumps(
                {"status": "ok", "result": {"payloads": [{"text": MODEL_BRIEF}]}}
            )
        return subprocess.CompletedProcess(
            command, 0, stdout=stdout, stderr="diagnostic"
        )

    monkeypatch.setattr("harness.morning_brief_synthesis.subprocess.run", fake_run)

    brief = synthesize_morning_brief(
        db_path=db_path,
        prepared_path=prepared_path,
        run_date=RUN_DATE,
        session_key="daily-news-sol-known-audit-key",
    )

    assert brief == FINAL_BRIEF
    assert len(commands) == 2
    for command in commands:
        assert command[:2] == ["openclaw", "agent"]
        assert command[command.index("--agent") + 1] == "main"
        assert command[command.index("--model") + 1] == "gpt-5.6-sol"
        assert command[command.index("--thinking") + 1] == "high"
        assert command[command.index("--session-key") + 1] == (
            "daily-news-sol-known-audit-key"
        )
        assert "--json" in command
        assert "--deliver" not in command


def test_openclaw_subprocess_failure_surfaces_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, prepared_path = _make_inputs(tmp_path)

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0], 17, stdout="", stderr="gateway connection failed"
        )

    monkeypatch.setattr("harness.morning_brief_synthesis.subprocess.run", fake_run)

    with pytest.raises(SynthesisError, match="status 17: gateway connection failed"):
        synthesize_morning_brief(
            db_path=db_path,
            prepared_path=prepared_path,
            run_date=RUN_DATE,
            retry_count=0,
        )


def _write_fake_wrapper_commands(
    tmp_path: Path, *, pipeline_status: int
) -> tuple[Path, Path]:
    pipeline = tmp_path / "fake-pipeline.sh"
    pipeline.write_text(
        "#!/usr/bin/env bash\n"
        'echo pipeline >> "$ORDER_LOG"\n'
        "echo collection-log-line\n"
        + (
            'mkdir -p "$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/'
            f'{RUN_DATE.isoformat()}/data/rendered"\n'
            'echo evidence > "$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/'
            f'{RUN_DATE.isoformat()}/data/rendered/test.md"\n'
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
        'echo sol >> "$ORDER_LOG"\n'
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
        'echo pipeline >> "$ORDER_LOG"\n'
        "attempt=1\n"
        '[[ -f "$ATTEMPT_FILE" ]] && attempt=2\n'
        'touch "$ATTEMPT_FILE"\n'
        'if [[ "$attempt" -eq 1 ]]; then exit 17; fi\n'
        'mkdir -p "$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/'
        f'{RUN_DATE.isoformat()}/data/rendered"\n'
        'echo evidence > "$MINERVA_WORKSPACE_ROOT/reports/03-daily-news/'
        f'{RUN_DATE.isoformat()}/data/rendered/test.md"\n',
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
