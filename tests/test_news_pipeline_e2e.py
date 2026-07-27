"""End-to-end orchestration tests for the safe agent news pipeline."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_news_pipeline_e2e.sh"
ARTICLE_URL = "https://example.test/controlled-article"
NEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
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
)
"""


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_minerva(tmp_path: Path) -> Path:
    return _write_executable(
        tmp_path / "fake-minerva.py",
        f'''#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["COMMAND_LOG"]).open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")

if args and args[0] == "summarize":
    content = sys.stdin.read().strip()
    if not content:
        raise SystemExit(12)
    print("Stub investor summary: " + content[:60])
    raise SystemExit(0)

if args[:2] == ["news", "download-finnhub"]:
    if os.environ.get("FAIL_PHASE") == "finnhub":
        print("stub Finnhub failure", file=sys.stderr)
        raise SystemExit(17)
    db = Path(args[args.index("--db") + 1])
    run_date = args[args.index("--date") + 1]
    with sqlite3.connect(db) as conn:
        conn.execute({NEWS_SCHEMA!r})
        conn.execute(
            "INSERT INTO news VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
            ("finnhub-key", 1784505600, run_date, "Stub Finnhub headline",
             "Stub Finnhub article content.", "stubwire",
             "https://example.test/finnhub", "finnhub-company",
             run_date + "T12:00:00Z"),
        )
    print('{{"inserted":1}}')
    raise SystemExit(0)

if args[:2] == ["news", "download-market-data"]:
    if os.environ.get("FAIL_PHASE") == "market-data":
        print("stub market failure", file=sys.stderr)
        raise SystemExit(18)
    db = Path(args[args.index("--db") + 1])
    run_date = args[args.index("--date") + 1]
    symbol = args[args.index("--symbol") + 1].upper()
    index = args[args.index("--index") + 1].upper()
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY, ticker TEXT, as_of TEXT,
                current REAL, previous_close REAL, change_pct REAL,
                instrument_type TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO prices "
            "(ticker, as_of, current, previous_close, change_pct, instrument_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(symbol, run_date, 110.0, 100.0, 10.0, "security"),
             (index, run_date, 5100.0, 5000.0, 2.0, "index")],
        )
    print('{{"written":2}}')
    raise SystemExit(0)

print("unexpected fake minerva command: " + repr(args), file=sys.stderr)
raise SystemExit(99)
''',
    )


def _fake_openclaw(tmp_path: Path) -> Path:
    return _write_executable(
        tmp_path / "fake-openclaw.py",
        f'''#!/usr/bin/env python3
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
def option(name):
    return args[args.index(name) + 1]
message = option("--message")
record = {{
    "agent": option("--agent"),
    "model": option("--model"),
    "thinking": option("--thinking"),
    "timeout": option("--timeout"),
    "message": message,
}}
with Path(os.environ["AGENT_LOG"]).open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")

if record["agent"] == os.environ["EXPECTED_COLLECTOR_AGENT"]:
    if os.environ.get("FAIL_PHASE") == "collector":
        raise SystemExit(19)
    db = Path(re.search(r"Scratch database: `([^`]+)`", message).group(1))
    url = re.search(r"Article URL: `([^`]+)`", message).group(1)
    with sqlite3.connect(db) as conn:
        conn.execute({NEWS_SCHEMA!r})
        conn.execute(
            "INSERT INTO news VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
            ("collector-key", 1784505600, "2026-07-19",
             "Controlled collector article", "Normalized collector body.",
             "e2e-collector", url, "e2e-controlled-article",
             "2026-07-19T12:00:00Z"),
        )
    print("collector stub complete")
    raise SystemExit(0)

if record["agent"] == os.environ["EXPECTED_SOL_AGENT"]:
    if os.environ.get("FAIL_PHASE") == "sol":
        raise SystemExit(20)
    db = Path(re.search(r"Scratch database: `([^`]+)`", message).group(1))
    brief = Path(re.search(r"Brief artifact: `([^`]+)`", message).group(1))
    if os.environ.get("LEAVE_NULL_SUMMARIES") != "1":
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT article_key, content FROM news "
                "WHERE summary IS NULL OR trim(summary) = '' "
                "ORDER BY published_at, article_key"
            ).fetchall()
        generated = []
        runner = shlex.split(os.environ["MINERVA_RUNNER"])
        for key, content in rows:
            result = subprocess.run(
                runner + ["summarize", "--model", os.environ["EXPECTED_SUMMARY_MODEL"]],
                input=content, text=True, capture_output=True, check=False,
            )
            if result.returncode or not result.stdout.strip():
                raise SystemExit(21)
            generated.append((result.stdout.strip(), key))
        with sqlite3.connect(db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for summary, key in generated:
                cursor = conn.execute(
                    "UPDATE news SET summary=? WHERE article_key=? "
                    "AND (summary IS NULL OR trim(summary) = '')",
                    (summary, key),
                )
                if cursor.rowcount != 1:
                    raise SystemExit(22)
            conn.commit()
    brief.write_text(
        "# Dry-run brief\\n\\nDry run — not posted to Slack.\\n\\n"
        "Stub news and market movements.\\n",
        encoding="utf-8",
    )
    print("sol stub complete")
    raise SystemExit(0)

print("unexpected agent", file=sys.stderr)
raise SystemExit(98)
''',
    )


def _run(
    tmp_path: Path,
    *,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_root = tmp_path / "runs"
    fake_minerva = _fake_minerva(tmp_path)
    fake_openclaw = _fake_openclaw(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "MINERVA_RUNNER": str(fake_minerva),
            "MINERVA_E2E_OPENCLAW": str(fake_openclaw),
            "MINERVA_E2E_RUN_ROOT": str(run_root),
            "COMMAND_LOG": str(tmp_path / "commands.jsonl"),
            "AGENT_LOG": str(tmp_path / "agents.jsonl"),
            "EXPECTED_COLLECTOR_AGENT": "collector-test",
            "EXPECTED_SOL_AGENT": "sol-test",
            "EXPECTED_SUMMARY_MODEL": "summary-test-model",
        }
    )
    (tmp_path / "home").mkdir()
    if extra_env:
        env.update(extra_env)
    args = [
        "bash",
        str(SCRIPT),
        "--stubbed",
        "--date",
        "2026-07-19",
        "--article-url",
        ARTICLE_URL,
        "--symbol",
        "nvda",
        "--index",
        "^gspc",
        "--collector-agent",
        "collector-test",
        "--collector-model",
        "collector-test-model",
        "--sol-agent",
        "sol-test",
        "--sol-model",
        "sol-test-model",
        "--summary-model",
        "summary-test-model",
    ]
    args.extend(extra_args or [])
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def _run_dir(result: subprocess.CompletedProcess[str]) -> Path:
    match = re.search(r"run_dir=([^\s]+)", result.stderr)
    assert match, result.stderr
    return Path(match.group(1))


def test_default_refuses_network_or_agent_execution(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--article-url", ARTICLE_URL],
        cwd=REPO_ROOT,
        env={**os.environ, "MINERVA_E2E_RUN_ROOT": str(tmp_path / "runs")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "disabled by default" in result.stderr
    assert not (tmp_path / "runs").exists()


def test_stubbed_pipeline_constructs_commands_and_verifies_outputs(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "brief_nonempty": True,
        "collector_rows": 1,
        "finnhub_rows": 1,
        "market_rows": 2,
        "null_summaries": 0,
        "ok": True,
        "run_dir": payload["run_dir"],
    }
    run_dir = Path(payload["run_dir"])
    assert run_dir.is_dir()
    assert json.loads((run_dir / "result.json").read_text(encoding="utf-8")) == payload
    assert "Dry run — not posted to Slack" in (
        run_dir / "dry-run-brief.md"
    ).read_text(encoding="utf-8")

    commands = [
        json.loads(line)
        for line in (tmp_path / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert commands[:2] == [
        [
            "news", "download-finnhub", "--date", "2026-07-19", "--db",
            str(run_dir / "scratch.db"), "--symbol", "nvda",
        ],
        [
            "news", "download-market-data", "--date", "2026-07-19", "--db",
            str(run_dir / "scratch.db"), "--index", "^gspc", "--symbol", "nvda",
        ],
    ]
    assert commands[2:] == [
        ["summarize", "--model", "summary-test-model"],
        ["summarize", "--model", "summary-test-model"],
    ]

    agents = [
        json.loads(line)
        for line in (tmp_path / "agents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(item["agent"], item["model"]) for item in agents] == [
        ("collector-test", "collector-test-model"),
        ("sol-test", "sol-test-model"),
    ]
    assert "news ingest --input - --db" in agents[0]["message"]
    assert str(tmp_path / "fake-minerva.py") in agents[0]["message"]
    assert "summarize --model summary-test-model" in agents[1]["message"]


def test_provider_failure_is_phase_specific_and_preserves_artifacts(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, extra_env={"FAIL_PHASE": "market-data"})

    assert result.returncode == 18
    assert "error[market-data]: failed with status 18" in result.stderr
    run_dir = _run_dir(result)
    assert run_dir.is_dir()
    assert (run_dir / "scratch.db").is_file()
    assert (run_dir / "logs" / "market-data.stderr").read_text(
        encoding="utf-8"
    ).strip() == "stub market failure"
    assert not (run_dir / "prompts" / "sol.md").exists()


def test_verification_rejects_null_summaries_and_keeps_run_for_inspection(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, extra_env={"LEAVE_NULL_SUMMARIES": "1"})

    assert result.returncode == 1
    assert "error[verify]" in result.stderr
    run_dir = _run_dir(result)
    diagnostics = (run_dir / "logs" / "verify.stderr").read_text(encoding="utf-8")
    assert "news row(s) still lack summaries" in diagnostics
    assert run_dir.is_dir()
    assert (run_dir / "dry-run-brief.md").is_file()
    with sqlite3.connect(run_dir / "scratch.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM news WHERE summary IS NULL").fetchone()[0] == 2
