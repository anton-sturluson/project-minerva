"""Tests for the first-class news CLI and read-only existence lookup."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from typer.testing import CliRunner

from harness import news
from harness.cli import app, dispatch_command
from harness.commands import news as news_commands
from harness.config import HarnessSettings

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]


def _create_lookup_db(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    db_path = tmp_path / "invest.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE news (article_key TEXT PRIMARY KEY, url TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO news (article_key, url) VALUES (?, ?)", rows
        )
    return db_path


def _candidate(
    *,
    title: str = "A Big Story",
    url: str = "https://example.test/new",
    published: str = "2026-07-19",
) -> dict[str, str]:
    return {"title": title, "url": url, "published": published}


def _article(**overrides: object) -> dict[str, object]:
    article: dict[str, object] = {
        "title": "A Big Story",
        "source_id": "reuters-markets",
        "url": "https://example.test/story",
        "published_at": "2026-07-19T09:30:00-04:00",
        "content": "Normalized article body.",
    }
    article.update(overrides)
    return article


def _write_raw(raw_dir: Path, *, title: str = "A   Big Story") -> Path:
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "wsj-story.md"
    raw_path.write_text(
        f"""# {title}

Source: WSJ
URL: https://example.test/story
Published:
Collected: 2026-07-19T04:00:00Z
Section: markets

Full article body.
""",
        encoding="utf-8",
    )
    return raw_path


def test_news_commands_are_registered_with_exact_help_surface() -> None:
    root_help = runner.invoke(app, ["--help"])
    group_help = runner.invoke(app, ["news", "--help"])
    ingest_help = runner.invoke(app, ["news", "ingest", "--help"])
    exist_help = runner.invoke(app, ["news", "exist", "--help"])

    assert root_help.exit_code == 0
    assert "news" in root_help.stdout
    assert group_help.exit_code == 0
    assert "ingest" in group_help.stdout
    assert "exist" in group_help.stdout
    assert "exists" not in group_help.stdout
    assert ingest_help.exit_code == 0
    assert "--raw-dir" in ingest_help.stdout
    assert "--summaries-dir" in ingest_help.stdout
    assert "--input" in ingest_help.stdout
    assert exist_help.exit_code == 0
    assert "--db" in exist_help.stdout
    assert "--source-id" in exist_help.stdout
    assert "--input" in exist_help.stdout


def test_ingest_cli_preserves_stats_report_summary_and_stable_key(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_path = _write_raw(raw_dir)
    summaries_dir = tmp_path / "summaries"
    summaries_dir.mkdir()
    (summaries_dir / raw_path.name).write_text(
        "Matching investor summary.", encoding="utf-8"
    )
    sources = tmp_path / "news-sources.json"
    sources.write_text(json.dumps([{"id": "wsj"}]), encoding="utf-8")
    registry = tmp_path / "ir-registry.json"
    registry.write_text("[]", encoding="utf-8")
    db_path = tmp_path / "invest.db"
    report_path = tmp_path / "logs" / "ingest.log"

    args = [
        "news",
        "ingest",
        "--raw-dir",
        str(raw_dir),
        "--summaries-dir",
        str(summaries_dir),
        "--db",
        str(db_path),
        "--news-sources",
        str(sources),
        "--ir-registry",
        str(registry),
        "--report",
        str(report_path),
    ]
    first = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout) == {
        "db_total": 1,
        "duplicates": 0,
        "eligible": 1,
        "inserted": 1,
        "missing_summaries": 0,
        "publication_fallbacks": 1,
        "skipped": 0,
    }
    assert "fallback:publication-date" in report_path.read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT article_key, title, summary, content FROM news"
        ).fetchone()
    assert row == (
        "7b8936454d4ca742cc3bc18e9c4d07ff477097563d62aea7f7f46ba723821df2",
        "A   Big Story",
        "Matching investor summary.",
        "Full article body.",
    )

    lookup = runner.invoke(
        app,
        ["news", "exist", "--db", str(db_path), "--source-id", "WSJ"],
        input=json.dumps(
            [{"title": "  a BIG story  ", "url": "", "published": "2026-07-19"}]
        ),
    )
    assert lookup.exit_code == 0, lookup.output
    assert json.loads(lookup.stdout) == {
        "status": "ok",
        "seen": [{"index": 0, "match": "article_key"}],
        "unseen": [],
    }

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["duplicates"] == 1
    assert json.loads(second.stdout)["inserted"] == 0


def test_ingest_cli_accepts_one_article_from_stdin_or_file_and_upserts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "invest.db"
    article = _article(summary="Investor summary.", section="markets")
    args = ["news", "ingest", "--input", "-", "--db", str(db_path)]

    inserted = runner.invoke(app, args, input=json.dumps(article))

    assert inserted.exit_code == 0, inserted.output
    inserted_result = json.loads(inserted.stdout)
    assert inserted_result["status"] == "inserted"
    assert inserted_result["article_key"] == news.article_key(
        "reuters-markets", "2026-07-19", "A Big Story"
    )

    input_file = tmp_path / "article.json"
    input_file.write_text(json.dumps(article), encoding="utf-8")
    duplicate = runner.invoke(
        app,
        ["news", "ingest", "--input", str(input_file), "--db", str(db_path)],
    )
    assert duplicate.exit_code == 0, duplicate.output
    assert json.loads(duplicate.stdout)["status"] == "duplicate"

    article["content"] = "Corrected normalized body."
    input_file.write_text(json.dumps(article), encoding="utf-8")
    updated = runner.invoke(
        app,
        ["news", "ingest", "--input", str(input_file), "--db", str(db_path)],
    )
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.stdout)["status"] == "updated"

    article.update(title="Retitled Story", content="Retitled normalized body.")
    input_file.write_text(json.dumps(article), encoding="utf-8")
    rekeyed = runner.invoke(
        app,
        ["news", "ingest", "--input", str(input_file), "--db", str(db_path)],
    )
    assert rekeyed.exit_code == 0, rekeyed.output
    assert json.loads(rekeyed.stdout) == {
        "article_key": news.article_key(
            "reuters-markets", "2026-07-19", "Retitled Story"
        ),
        "status": "updated",
    }

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT title, content, summary, section, collected_at FROM news"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][:4] == (
        "Retitled Story",
        "Retitled normalized body.",
        "Investor summary.",
        "markets",
    )
    assert rows[0][4].endswith("Z")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must be an object"),
        (_article(content=""), "non-empty string content"),
        (_article(published_at="July 2026"), "parseable published_at"),
        (_article(content="<!doctype html><html></html>"), "raw HTML"),
        (_article(browser_html="<html>raw</html>"), "unknown field"),
    ],
)
def test_ingest_cli_rejects_invalid_single_article_input(
    tmp_path: Path, payload: object, message: str
) -> None:
    db_path = tmp_path / "invest.db"

    result = runner.invoke(
        app,
        ["news", "ingest", "--input", "-", "--db", str(db_path)],
        input=json.dumps(payload),
    )

    assert result.exit_code == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not db_path.exists()


def test_ingest_cli_rejects_conflicting_single_and_batch_modes(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "news",
            "ingest",
            "--input",
            "-",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--db",
            str(tmp_path / "invest.db"),
        ],
        input=json.dumps(_article()),
    )

    assert result.exit_code == 2
    assert "exactly one of --input, --all, --date, or --raw-dir" in result.stderr
    assert not (tmp_path / "invest.db").exists()


def test_single_article_ingest_allows_concurrent_writers(tmp_path: Path) -> None:
    db_path = tmp_path / "invest.db"
    count = 4
    barrier = Barrier(count)

    def write(index: int) -> str:
        article = news.parse_article_input(
            json.dumps(
                _article(
                    title=f"Story {index}",
                    url=f"https://example.test/{index}",
                )
            )
        )
        barrier.wait()
        return news.ingest_article(db_path, article)["status"]

    with ThreadPoolExecutor(max_workers=count) as pool:
        statuses = list(pool.map(write, range(count)))

    assert statuses == ["inserted"] * count
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == count
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_ingest_cli_reports_malformed_source_registry_without_traceback(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir)
    malformed_sources = tmp_path / "news-sources.json"
    malformed_sources.write_text("not-json", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "news",
            "ingest",
            "--raw-dir",
            str(raw_dir),
            "--db",
            str(tmp_path / "invest.db"),
            "--news-sources",
            str(malformed_sources),
            "--ir-registry",
            str(tmp_path / "missing-ir.json"),
        ],
    )

    assert result.exit_code == 1
    assert "malformed news source registry" in result.stderr
    assert "invalid JSON" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "invest.db").exists()


def test_ingest_cli_reports_schema_failure_with_operational_exit_code(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir)
    db_path = tmp_path / "invest.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE news (unexpected TEXT)")

    result = runner.invoke(
        app,
        [
            "news",
            "ingest",
            "--raw-dir",
            str(raw_dir),
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "cannot migrate legacy news table" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("mode_args", [["--all"], ["--date", "2026-07-19"]])
def test_ingest_cli_rejects_summaries_without_raw_dir(
    tmp_path: Path, mode_args: list[str]
) -> None:
    db_path = tmp_path / "invest.db"
    result = runner.invoke(
        app,
        [
            "news",
            "ingest",
            *mode_args,
            "--summaries-dir",
            str(tmp_path / "summaries"),
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 2
    assert "--summaries-dir requires --raw-dir" in result.stderr
    assert "Traceback" not in result.stderr
    assert not db_path.exists()


def test_article_key_and_title_normalization_are_shared_by_exist(
    tmp_path: Path,
) -> None:
    key = news.article_key("wsj", "2026-07-19", "A Big Story")
    db_path = _create_lookup_db(
        tmp_path, [(key, "https://example.test/original")]
    )

    result = news.check_candidates(
        db_path,
        "WSJ",
        [_candidate(title="  a BIG   story  ", url="")],
    )

    assert news.normalized_title_for_key("  a BIG   story  ") == "a big story"
    assert result == {
        "status": "ok",
        "seen": [{"index": 0, "match": "article_key"}],
        "unseen": [],
    }


def test_exist_matches_exact_nonempty_url_before_article_key(tmp_path: Path) -> None:
    key = news.article_key("source", "2026-07-19", "A Big Story")
    db_path = _create_lookup_db(
        tmp_path, [(key, "https://example.test/already-collected")]
    )

    result = news.check_candidates(
        db_path,
        "source",
        [
            _candidate(
                title="A Big Story",
                url="https://example.test/already-collected",
                published="2026-07-19",
            ),
            _candidate(
                title="Different Story",
                url="https://EXAMPLE.test/already-collected",
                published="",
            ),
        ],
    )

    assert result["seen"] == [{"index": 0, "match": "url"}]
    assert result["unseen"] == [1]


def test_exist_returns_unseen_and_allows_empty_url(tmp_path: Path) -> None:
    db_path = _create_lookup_db(tmp_path, [("other", "https://example.test/old")])

    result = news.check_candidates(
        db_path,
        "source",
        [
            _candidate(url="", published=""),
            _candidate(title="Second", url="https://example.test/new", published=""),
        ],
    )

    assert result == {"status": "ok", "seen": [], "unseen": [0, 1]}


def test_exist_deduplicates_batch_before_missing_database_lookup(
    tmp_path: Path,
) -> None:
    result = news.check_candidates(
        tmp_path / "missing.db",
        "source",
        [
            _candidate(url="https://example.test/one"),
            _candidate(url="https://example.test/one"),
            _candidate(url="https://example.test/two"),
            _candidate(title="Different", url="", published="2026-07-20"),
        ],
    )

    assert result == {
        "status": "database_missing",
        "seen": [
            {"index": 1, "match": "batch_url"},
            {"index": 2, "match": "batch_article_key"},
        ],
        "unseen": [0, 3],
    }


def test_exist_preserves_candidate_order_across_batch_and_database_matches(
    tmp_path: Path,
) -> None:
    key = news.article_key("source", "2026-07-19", "A Big Story")
    db_path = _create_lookup_db(
        tmp_path,
        [
            (key, "https://example.test/stored-by-key"),
            ("different-key", "https://example.test/stored-by-url"),
        ],
    )

    result = news.check_candidates(
        db_path,
        "source",
        [
            _candidate(url="https://example.test/new-url"),
            _candidate(url="https://example.test/new-url"),
            _candidate(
                title="Other",
                url="https://example.test/stored-by-url",
                published="",
            ),
        ],
    )

    assert result == {
        "status": "ok",
        "seen": [
            {"index": 0, "match": "article_key"},
            {"index": 1, "match": "batch_url"},
            {"index": 2, "match": "url"},
        ],
        "unseen": [],
    }


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not JSON", "invalid JSON"),
        ('{"title":"not an array"}', "must be an array"),
        ('[{"title":"Missing URL"}]', "string url"),
        (
            '[{"title":"Story","url":"https://x","published":123}]',
            "published must be a string",
        ),
    ],
)
def test_malformed_candidate_json_is_rejected(raw: str, message: str) -> None:
    with pytest.raises(news.CandidateInputError, match=message):
        news.parse_candidates(raw)

    cli_result = runner.invoke(
        app,
        [
            "news",
            "exist",
            "--db",
            "/missing/invest.db",
            "--source-id",
            "source",
        ],
        input=raw,
    )
    assert cli_result.exit_code == 2
    assert message in cli_result.stderr
    assert "Traceback" not in cli_result.stderr
    assert cli_result.stdout == ""


def test_missing_database_and_table_are_all_unseen_without_writes(
    tmp_path: Path,
) -> None:
    candidates = [_candidate(), _candidate(title="Second", url="")]
    missing_db = tmp_path / "does-not-exist.db"

    missing_result = news.check_candidates(missing_db, "source", candidates)

    assert missing_result == {
        "status": "database_missing",
        "seen": [],
        "unseen": [0, 1],
    }
    assert not missing_db.exists()

    no_table = tmp_path / "no-news.db"
    with sqlite3.connect(no_table) as conn:
        conn.execute("CREATE TABLE other (value TEXT)")
    before = no_table.stat().st_mtime_ns

    no_table_result = news.check_candidates(no_table, "source", candidates)

    assert no_table_result == {
        "status": "news_table_missing",
        "seen": [],
        "unseen": [0, 1],
    }
    assert no_table.stat().st_mtime_ns == before
    with sqlite3.connect(no_table) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall() == [("other",)]


def test_exist_cli_reads_stdin_or_input_and_emits_compact_json(
    tmp_path: Path,
) -> None:
    missing_db = tmp_path / "missing.db"
    raw = json.dumps([_candidate()])
    input_file = tmp_path / "candidates.json"
    input_file.write_text(raw, encoding="utf-8")

    for extra_args, stdin in [([], raw), (["--input", str(input_file)], None)]:
        result = runner.invoke(
            app,
            [
                "news",
                "exist",
                "--db",
                str(missing_db),
                "--source-id",
                "source",
                *extra_args,
            ],
            input=stdin,
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == (
            '{"status":"database_missing","seen":[],"unseen":[0]}\n'
        )
    assert not missing_db.exists()


def test_exist_uses_read_only_query_only_database_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _create_lookup_db(
        tmp_path,
        [("other", "https://example.test/already-collected")],
    )
    before_bytes = db_path.read_bytes()
    before_mtime = db_path.stat().st_mtime_ns
    real_connect = sqlite3.connect
    connect_calls: list[tuple[str, dict[str, object]]] = []
    executed: list[tuple[str, object]] = []

    class ConnectionProxy:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def __enter__(self) -> ConnectionProxy:
            return self

        def __exit__(self, *args: object) -> None:
            self.connection.__exit__(*args)

        def execute(self, statement: str, parameters: object = ()) -> sqlite3.Cursor:
            executed.append((statement, parameters))
            return self.connection.execute(statement, parameters)

    def recording_connect(
        database: str, *args: object, **kwargs: object
    ) -> ConnectionProxy:
        connect_calls.append((database, kwargs))
        return ConnectionProxy(real_connect(database, *args, **kwargs))

    monkeypatch.setattr(news.sqlite3, "connect", recording_connect)
    db_path.chmod(0o444)
    try:
        result = news.check_candidates(
            db_path,
            "source",
            [_candidate(url="https://example.test/already-collected")],
        )
    finally:
        db_path.chmod(0o644)

    assert result["seen"] == [{"index": 0, "match": "url"}]
    assert connect_calls == [
        (f"{db_path.resolve().as_uri()}?mode=ro", {"uri": True})
    ]
    assert ("PRAGMA query_only = ON", ()) in executed
    assert any(
        "WHERE url = ?" in statement
        and parameters == ("https://example.test/already-collected",)
        for statement, parameters in executed
    )
    assert all(
        "https://example.test/already-collected" not in statement
        for statement, _ in executed
    )
    assert db_path.read_bytes() == before_bytes
    assert db_path.stat().st_mtime_ns == before_mtime
    assert not Path(f"{db_path}-journal").exists()
    assert not Path(f"{db_path}-wal").exists()


def test_news_is_not_available_to_internal_run_dispatch(tmp_path: Path) -> None:
    result = dispatch_command(
        ["news", "exist"],
        settings=HarnessSettings(workspace_root=tmp_path),
        stdin=b"[]",
    )

    assert result.exit_code == 1
    assert b"unknown command `news`" in result.stderr


def test_ingest_cli_defaults_resolve_from_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir)
    monkeypatch.setattr(
        news_commands,
        "get_settings",
        lambda: HarnessSettings(workspace_root=workspace),
    )

    result = runner.invoke(app, ["news", "ingest", "--raw-dir", str(raw_dir)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["skipped"] == 1
    assert (workspace / "data" / "04-database" / "invest.db").is_file()


def test_morning_brief_shell_and_prompts_use_direct_ingest_contract() -> None:
    """The production script uses direct-ingest collectors and aggregate downloads."""
    script = (REPO_ROOT / "scripts" / "run_morning_brief.sh").read_text(
        encoding="utf-8"
    )
    browser_prompt = (
        REPO_ROOT / "scripts" / "prompts" / "collect_news.md"
    ).read_text(encoding="utf-8")
    webfetch_prompt = (
        REPO_ROOT / "scripts" / "prompts" / "collect_news_webfetch.md"
    ).read_text(encoding="utf-8")
    outer_sol_prompt = (
        REPO_ROOT / "scripts" / "prompts" / "morning_brief_outer_sol.md"
    ).read_text(encoding="utf-8")

    # Aggregate direct-download phases run before collectors and share the DB.
    assert "news download-finnhub" in script
    assert "news download-market-data" in script

    # Collector stdin ingest command is rendered once and shared with agents.
    assert "NEWS_INGEST_COMMAND" in script
    assert "news ingest --input - --db" in script
    assert "printf -v NEWS_INGEST_COMMAND '(cd %q && %s)'" in script
    assert "NEWS_EXIST_COMMAND" in script
    assert '"${MINERVA_RUNNER_ARR[@]}" news exist' in script

    # Configurable collector agent for OpenClaw same-agent isolation.
    assert 'MINERVA_NEWS_COLLECTOR_AGENT="${MINERVA_NEWS_COLLECTOR_AGENT:-main}"' in script
    assert '--agent "${MINERVA_NEWS_COLLECTOR_AGENT}"' in script

    # Bounded parallel collectors, isolated source roots, phase artifacts.
    assert 'MINERVA_BROWSER_TIMEOUT="${MINERVA_BROWSER_TIMEOUT:-900}"' in script
    assert 'MINERVA_WEBFETCH_TIMEOUT="${MINERVA_WEBFETCH_TIMEOUT:-300}"' in script
    assert 'MINERVA_MAX_COLLECTORS="${MINERVA_MAX_COLLECTORS:-8}"' in script
    assert 'wait_for_collectors' in script
    assert "collectors.json" in script
    assert "outer-sol-handoff.json" in script
    assert "current-evidence.json" in script

    # Current-date evidence gate refuses thin briefs unless explicitly allowed.
    assert 'MINERVA_ALLOW_THIN_BRIEF' in script
    assert "refusing a thin brief" in script
    assert 'ZoneInfo("America/New_York")' in script

    # The old batch-ingest architecture has been fully removed.
    for banned in (
        "extract-files",
        "extract_files",
        "aggregate_source_raw",
        "--raw-dir",
        "--summaries-dir",
    ):
        assert banned not in script, banned

    # No inner Sol synthesis: reports/slack are written by the outer cron Sol.
    assert "outer cron Sol" in script or "outer-cron-sol" in script
    assert 'openclaw agent \\\n' in script or script.count("openclaw agent") == 1

    for prompt in (browser_prompt, webfetch_prompt):
        # Deterministic duplicate check remains a mandatory pre-extraction step.
        assert '{{NEWS_EXIST_COMMAND}} --db "{{INVEST_DB}}"' in prompt
        assert '--input "{{CANDIDATE_FILE}}" > "{{LOOKUP_FILE}}"' in prompt
        # Direct-ingest contract: one JSON object per article, piped to stdin.
        assert "{{NEWS_INGEST_COMMAND}}" in prompt
        assert "news ingest --input - --db" in prompt
        # Article/item bodies live in SQLite only. No summary written here.
        assert "isolated metadata root" in prompt
        assert "SQLite" in prompt
        assert "summarizer" in prompt
        assert "outer Sol" in prompt
        # Collectors never emit filesystem article/summary artifacts.
        assert "Do not write article" in prompt
        for forbidden in (".md`", "/raw/", "extract-files"):
            assert forbidden not in prompt, forbidden

    # Browser prompt keeps single-tab, no-additional-window discipline.
    assert "only browser window and tab" in browser_prompt
    assert "one JSON array" in browser_prompt
    assert "Never invoke Slack" in browser_prompt
    assert "web_fetch only" in webfetch_prompt
    assert "Never open a browser" in webfetch_prompt

    # The versioned outer-Sol contract owns bounded summarization and delivery.
    assert "at most four subprocesses" in outer_sol_prompt
    assert "one transaction" in outer_sol_prompt
    assert "Do not call Slack" in outer_sol_prompt
    assert "Return the exact contents" in outer_sol_prompt


def test_morning_brief_hands_summarization_off_to_outer_sol() -> None:
    """No inner summarization: outer cron Sol handles minerva summarize + persistence."""
    script = (REPO_ROOT / "scripts" / "run_morning_brief.sh").read_text(
        encoding="utf-8"
    )
    # Script emits a handoff artifact naming outer-cron-sol as final agent.
    assert '"outer-cron-sol"' in script
    assert "minerva summarize" in script or "`minerva summarize`" in script
    # The script never invokes `minerva summarize` itself (that's the outer agent).
    assert "run summarize" not in script
    assert '"${MINERVA_RUNNER_ARR[@]}" summarize' not in script
    # Handoff explicitly lists final report artifacts.
    assert "morning-brief-report.md" in script
    assert "slack-brief.md" in script
    # No Slack posting from this script.
    assert "curl" not in script or "slack" not in script.lower()
