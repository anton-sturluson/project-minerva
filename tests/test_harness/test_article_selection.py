"""Focused tests for the bounded Terra article-selection stage."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness import article_selection


def _record(key: str, source: str = "wsj", published_at: int = 100) -> dict[str, object]:
    return {
        "article_key": key,
        "url": f"https://example.test/{key}",
        "title": f"Title {key}",
        "source": source,
        "published_at": published_at,
        "summary": f"Summary for {key}",
    }


# ---------------------------------------------------------------------------
# balanced_batches
# ---------------------------------------------------------------------------


def test_balanced_batches_empty_returns_empty_list() -> None:
    assert article_selection.balanced_batches([]) == []


def test_balanced_batches_never_exceeds_max_and_preserves_order() -> None:
    records = [_record(f"k{index:02d}") for index in range(11)]

    batches = article_selection.balanced_batches(records, max_batches=4)

    assert len(batches) == 4
    assert [len(batch) for batch in batches] == [3, 3, 3, 2]
    flat = [row["article_key"] for batch in batches for row in batch]
    assert flat == [record["article_key"] for record in records]


def test_balanced_batches_uses_fewer_batches_when_records_are_scarce() -> None:
    records = [_record(f"k{index}") for index in range(3)]

    batches = article_selection.balanced_batches(records, max_batches=4)

    assert [len(batch) for batch in batches] == [1, 1, 1]


def test_balanced_batches_rejects_non_positive_max() -> None:
    with pytest.raises(ValueError):
        article_selection.balanced_batches([_record("k0")], max_batches=0)


# ---------------------------------------------------------------------------
# parse_batch_selection
# ---------------------------------------------------------------------------


def test_parse_batch_selection_grounds_urls_from_records_and_dedupes_keys() -> None:
    records = [_record("a"), _record("b")]
    text = json.dumps(
        {
            "selected_developments": [
                {
                    "section": "portfolio_watchlist",
                    "takeaway": "Something material",
                    "materiality": "Long-term earnings",
                    "article_keys": ["a", "b", "a"],
                    "urls": ["https://model-hallucinated.example/nope"],
                }
            ]
        }
    )

    parsed = article_selection.parse_batch_selection(text, records, batch_number=1)

    assert len(parsed) == 1
    development = parsed[0]
    assert development["article_keys"] == ["a", "b"]
    assert development["urls"] == [
        "https://example.test/a",
        "https://example.test/b",
    ]
    assert development["batch"] == 1
    assert development["section"] == "portfolio_watchlist"


def test_parse_batch_selection_rejects_unknown_article_keys() -> None:
    records = [_record("a")]
    text = json.dumps(
        {
            "selected_developments": [
                {
                    "section": "worth_knowing",
                    "takeaway": "t",
                    "materiality": "m",
                    "article_keys": ["a", "ghost"],
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="unknown article key"):
        article_selection.parse_batch_selection(text, records, batch_number=2)


def test_parse_batch_selection_rejects_invalid_section() -> None:
    records = [_record("a")]
    text = json.dumps(
        {
            "selected_developments": [
                {
                    "section": "off_topic",
                    "takeaway": "t",
                    "materiality": "m",
                    "article_keys": ["a"],
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="invalid section"):
        article_selection.parse_batch_selection(text, records, batch_number=3)


def test_parse_batch_selection_rejects_missing_article_keys() -> None:
    records = [_record("a")]
    text = json.dumps(
        {
            "selected_developments": [
                {
                    "section": "worth_knowing",
                    "takeaway": "t",
                    "materiality": "m",
                    "article_keys": [],
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="article_keys"):
        article_selection.parse_batch_selection(text, records, batch_number=4)


def test_parse_batch_selection_accepts_empty_selection() -> None:
    records = [_record("a")]
    text = json.dumps({"selected_developments": []})

    assert article_selection.parse_batch_selection(text, records, batch_number=5) == []


# ---------------------------------------------------------------------------
# select_articles_from_handoff — end-to-end with a fake extract-files runner
# ---------------------------------------------------------------------------


def _seed_db(db: Path, records: list[dict[str, object]]) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE news ("
            "article_key TEXT PRIMARY KEY, url TEXT, title TEXT, source TEXT, "
            "published_at INTEGER, content TEXT, summary TEXT)"
        )
        connection.executemany(
            "INSERT INTO news VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record["article_key"],
                    record["url"],
                    record["title"],
                    record["source"],
                    record["published_at"],
                    "content",
                    record["summary"],
                )
                for record in records
            ],
        )


def _fixed_epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def _build_handoff(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    db = tmp_path / "invest.db"
    _seed_db(db, records)
    holdings = tmp_path / "holdings.json"
    watchlist = tmp_path / "watchlist.json"
    holdings.write_text(
        json.dumps(
            [{"security_id": "AAPL", "ticker": "AAPL", "company_name": "Apple"}]
        ),
        encoding="utf-8",
    )
    watchlist.write_text(
        json.dumps(
            [{"security_id": "MSFT", "ticker": "MSFT", "company_name": "Microsoft"}]
        ),
        encoding="utf-8",
    )
    shortlist = tmp_path / "article-shortlist.json"
    handoff = tmp_path / "handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "status": "ready",
                "db": str(db),
                "holdings_path": str(holdings),
                "watchlist_path": str(watchlist),
                "article_shortlist": str(shortlist),
                "window_start": "2026-07-26T04:00:00-04:00",
                "window_end": "2026-07-27T04:00:00-04:00",
            }
        ),
        encoding="utf-8",
    )
    return handoff


def test_select_articles_from_handoff_writes_grounded_shortlist(
    tmp_path: Path,
) -> None:
    lower = _fixed_epoch("2026-07-26T04:00:00-04:00")
    records = [
        _record("a", source="wsj", published_at=lower + 60),
        _record("b", source="reuters", published_at=lower + 120),
        _record("c", source="wsj", published_at=lower + 180),
    ]
    handoff_path = _build_handoff(tmp_path, records)
    calls: list[list[str]] = []

    def fake_runner(command, cwd, capture_output, text, check):
        calls.append(list(command))
        out_index = command.index("--out")
        out_root = Path(command[out_index + 1])
        out_root.mkdir(parents=True, exist_ok=True)

        batch_paths = [command[i + 1] for i, tok in enumerate(command) if tok == "--files"]
        entries = []
        for number, batch_path in enumerate(batch_paths, start=1):
            batch_payload = json.loads(Path(batch_path).read_text(encoding="utf-8"))
            first_key = batch_payload["articles"][0]["article_key"]
            result = {
                "selected_developments": [
                    {
                        "section": "portfolio_watchlist" if number == 1 else "worth_knowing",
                        "takeaway": f"takeaway-{number}",
                        "materiality": f"materiality-{number}",
                        "article_keys": [first_key],
                    }
                ]
            }
            output_path = out_root / f"result-{number}.md"
            output_path.write_text(json.dumps(result), encoding="utf-8")
            entries.append(
                {
                    "source": str(Path(batch_path).resolve()),
                    "output": str(output_path),
                    "status": "ok",
                }
            )
        (out_root / "manifest.json").write_text(
            json.dumps({"entries": entries}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    shortlist = article_selection.select_articles_from_handoff(
        handoff_path, command_runner=fake_runner
    )

    assert calls, "extract-files was not invoked"
    command = calls[0]
    assert "extract-files" in command
    assert "--model" in command and command[command.index("--model") + 1] == "gpt-5.6-terra"
    assert "--thinking" in command and command[command.index("--thinking") + 1] == "high"
    assert "--concurrency" in command and command[command.index("--concurrency") + 1] == "4"

    # Shortlist file was written and matches returned payload.
    written = json.loads(
        Path(json.loads(handoff_path.read_text())["article_shortlist"]).read_text(
            encoding="utf-8"
        )
    )
    assert written == shortlist
    assert shortlist["status"] == "ready"
    assert shortlist["counts"]["input_articles"] == 3
    assert shortlist["counts"]["batches"] >= 1
    assert shortlist["counts"]["selected_developments"] == shortlist["counts"]["batches"]

    selected_keys = {row["article_key"] for row in shortlist["selected_articles"]}
    for development in shortlist["selected_developments"]:
        for key in development["article_keys"]:
            assert key in selected_keys
        # URLs are pulled from the SQLite records, not from any model text.
        for url in development["urls"]:
            assert url.startswith("https://example.test/")

    provenance = shortlist["provenance"]
    assert provenance["model"] == "gpt-5.6-terra"
    assert provenance["thinking"] == "high"
    assert provenance["concurrency"] == 4
    assert provenance["extractor"] == "uv run minerva extract-files"


def test_select_articles_from_handoff_raises_when_command_fails(tmp_path: Path) -> None:
    lower = _fixed_epoch("2026-07-26T04:00:00-04:00")
    handoff_path = _build_handoff(
        tmp_path, [_record("a", published_at=lower + 60)]
    )

    def failing_runner(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(
            command, returncode=2, stdout="", stderr="boom"
        )

    with pytest.raises(RuntimeError, match="extract-files failed"):
        article_selection.select_articles_from_handoff(
            handoff_path, command_runner=failing_runner
        )


def test_select_articles_from_handoff_rejects_incomplete_manifest(tmp_path: Path) -> None:
    lower = _fixed_epoch("2026-07-26T04:00:00-04:00")
    records = [
        _record("a", published_at=lower + 60),
        _record("b", published_at=lower + 120),
    ]
    handoff_path = _build_handoff(tmp_path, records)

    def incomplete_runner(command, cwd, capture_output, text, check):
        out_index = command.index("--out")
        out_root = Path(command[out_index + 1])
        out_root.mkdir(parents=True, exist_ok=True)
        # Report only one entry even though multiple batches were requested.
        entries = [{"source": "unrelated", "output": "unrelated.md", "status": "ok"}]
        (out_root / "manifest.json").write_text(
            json.dumps({"entries": entries}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    with pytest.raises(ValueError):
        article_selection.select_articles_from_handoff(
            handoff_path, command_runner=incomplete_runner
        )


def test_select_articles_from_handoff_requires_complete_summaries(tmp_path: Path) -> None:
    lower = _fixed_epoch("2026-07-26T04:00:00-04:00")
    records = [_record("a", published_at=lower + 60)]
    records[0]["summary"] = ""
    handoff_path = _build_handoff(tmp_path, records)

    with pytest.raises(ValueError, match="complete summaries"):
        article_selection.select_articles_from_handoff(
            handoff_path, command_runner=lambda *a, **k: None  # type: ignore[arg-type]
        )


def test_select_articles_from_handoff_handles_empty_window(tmp_path: Path) -> None:
    handoff_path = _build_handoff(tmp_path, [])

    def sentinel_runner(*_args, **_kwargs):
        raise AssertionError("runner should not be invoked with no records")

    shortlist = article_selection.select_articles_from_handoff(
        handoff_path, command_runner=sentinel_runner
    )

    assert shortlist["counts"] == {
        "batches": 0,
        "excluded_articles": 0,
        "input_articles": 0,
        "selected_articles": 0,
        "selected_developments": 0,
        "sources": {},
    }
    assert shortlist["selected_developments"] == []
    assert shortlist["selected_articles"] == []
    assert shortlist["status"] == "ready"


# ---------------------------------------------------------------------------
# Prompt and handoff sanity
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_selection_prompt_captures_required_policy() -> None:
    body = article_selection.DEFAULT_PROMPT.read_text(encoding="utf-8")
    for term in (
        "portfolio_watchlist",
        "worth_knowing",
        "article_keys",
        "materiality",
        "Materiality",
    ):
        assert term in body, f"selection prompt missing `{term}`"
    lower = body.lower()
    assert "exclude" in lower
    assert "price" in lower
    assert "filings" in lower


def test_synthesis_prompt_consumes_shortlist_not_openclaw_agent() -> None:
    prompt = (REPO_ROOT / "scripts" / "prompts" / "morning_brief_synthesis.md").read_text(
        encoding="utf-8"
    )
    assert "openclaw agent" not in prompt
    assert "--agent main --model terra" not in prompt
    assert "brief select-news" in prompt
    assert "article_shortlist" in prompt
