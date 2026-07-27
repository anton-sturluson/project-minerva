"""Behavioral coverage for direct-ingest morning-brief news collectors."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "run_morning_brief.sh"


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_minerva(tmp_path: Path) -> Path:
    """Fake `minerva` that logs invocations and skips real work.

    Aggregate downloads (`news download-finnhub`, `news download-market-data`)
    just log. `news exist` returns an empty-seen response so collectors treat
    every candidate as unseen. `news ingest` writes the piped article into a
    real SQLite `news` table so the current-evidence gate sees rows.
    """
    script = r"""#!/usr/bin/env bash
set -euo pipefail
subcommand="${1:-}"
action="${2:-}"
printf '%s\n' "$*" >> "${MINERVA_CALL_LOG}"

if [[ "${subcommand}" == "news" && "${action}" == "exist" ]]; then
  printf '{"seen":[],"unseen":[]}\n'
  exit 0
fi
if [[ "${subcommand}" == "news" && "${action}" == "ingest" ]]; then
  db=""
  from_stdin=0
  shift 2
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --db) db="$2"; shift 2 ;;
      --input) if [[ "$2" == "-" ]]; then from_stdin=1; fi; shift 2 ;;
      *) shift ;;
    esac
  done
  if [[ "${from_stdin}" -ne 1 ]]; then
    echo "test fake minerva only supports --input -" >&2
    exit 2
  fi
  payload="$(cat)"
  DB_PATH="${db}" ARTICLE_JSON="${payload}" python3 - <<'PY'
import json
import os
import sqlite3
from datetime import datetime, timezone

db = os.environ["DB_PATH"]
payload = json.loads(os.environ["ARTICLE_JSON"])
conn = sqlite3.connect(db)
try:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS news ("
        "article_key TEXT PRIMARY KEY, "
        "published_at INTEGER, "
        "published_at_raw TEXT, "
        "title TEXT, "
        "content TEXT, "
        "summary TEXT, "
        "source TEXT, "
        "url TEXT, "
        "section TEXT, "
        "collected_at TEXT)"
    )
    key = f"{payload['source_id']}::{payload['url']}"
    published_raw = payload.get("published_at", "")
    try:
        parsed = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        epoch = int(parsed.timestamp())
    except (ValueError, AttributeError):
        epoch = None
    conn.execute(
        "INSERT OR REPLACE INTO news "
        "(article_key, published_at, published_at_raw, title, content, "
        "summary, source, url, section, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            epoch,
            published_raw,
            payload["title"],
            payload["content"],
            None,
            payload["source_id"],
            payload["url"],
            payload.get("section"),
            payload.get("collected_at"),
        ),
    )
    conn.commit()
finally:
    conn.close()
print(json.dumps({"status": "inserted", "article_key": key}))
PY
  exit 0
fi

# Aggregate downloads (finnhub, market-data), brief filings/earnings/market/
# prep, portfolio sync: just log and succeed.
exit 0
"""
    return _write_executable(tmp_path / "fake-minerva", script)


def _fake_openclaw(tmp_path: Path) -> Path:
    """Fake OpenClaw that mimics a collector agent.

    Parses `SOURCE_ROOT`, `INVEST_DB`, and `news ingest` command out of the
    prompt, then either fails (for the broken source id) or invokes
    `minerva news ingest --input -` via MINERVA_RUNNER so the wrapper's
    contract with the news CLI is exercised end-to-end.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    return _write_executable(
        fake_bin / "openclaw",
        r"""#!/usr/bin/env bash
set -euo pipefail
message=""
timeout=""
agent=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --message) message="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    --agent) agent="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Extract the isolated metadata root and the news-ingest command rendered in
# the prompt. Both are stable, verbatim substrings emitted by the script.
source_root=$(printf '%s\n' "${message}" | \
  sed -n 's/^Your isolated metadata root is `\([^`]*\)`.*/\1/p' | head -n 1)
source_id="${source_root##*/}"
invest_db=$(printf '%s\n' "${message}" | \
  sed -n 's|.*--db "\([^"]*\)".*|\1|p' | head -n 1)

printf '%s|%s\n' "${source_id}" "${timeout}" >> "${TIMEOUT_LOG}"
printf '%s\n' "${agent}" >> "${AGENT_LOG}"
printf '%s\n' "${source_id}" >> "${COLLECTOR_START_LOG}"

if [[ "${source_id}" == "${BROKEN_SOURCE:-__unset__}" ]]; then
  exit 7
fi

# The prompt must include the direct-ingest command surface. Assert it here so
# any regression surfaces as a collector failure with a clear diagnostic.
if ! printf '%s\n' "${message}" | grep -q "news ingest --input -"; then
  echo "prompt missing direct-ingest command" >&2
  exit 8
fi

# Perform the direct-ingest that a real collector would perform.
article_json=$(SOURCE_ID="${source_id}" python3 - <<'PY'
import json
import os
from datetime import datetime, timezone

source_id = os.environ["SOURCE_ID"]
now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
print(json.dumps({
    "title": f"Article from {source_id}",
    "source_id": source_id,
    "url": f"https://example.test/{source_id}/story",
    "published_at": os.environ.get("PUBLISHED_AT", now),
    "content": f"Body from {source_id}",
    "collected_at": now,
}))
PY
)
printf '%s\n' "${article_json}" | "${MINERVA_RUNNER}" news ingest \
  --input - --db "${invest_db}" >/dev/null
""",
    )


def _run_wrapper(
    tmp_path: Path,
    *,
    sources: list[dict[str, object]],
    ir_entries: list[dict[str, object]] | None = None,
    extra_env: dict[str, str] | None = None,
    run_date: str | None = None,
) -> subprocess.CompletedProcess[str]:
    ir_entries = ir_entries or []
    sources_path = tmp_path / "news-sources.json"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")
    ir_path = tmp_path / "ir-registry.json"
    ir_path.write_text(json.dumps(ir_entries), encoding="utf-8")

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    temp_state = tmp_path / "tmp"
    temp_state.mkdir(exist_ok=True)
    coordinator = tmp_path / "coordinator"
    coordinator.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    fake_openclaw = (
        bin_dir / "openclaw" if bin_dir.is_dir() else _fake_openclaw(tmp_path)
    )
    fake_minerva_path = tmp_path / "fake-minerva"
    fake_minerva = (
        fake_minerva_path if fake_minerva_path.is_file() else _fake_minerva(tmp_path)
    )
    workspace = tmp_path / "workspace"
    invest_db = tmp_path / "invest.db"
    call_log = coordinator / "minerva-calls.log"
    call_log.touch()

    env = os.environ.copy()
    env.pop("MINERVA_NEWS_COLLECTOR_AGENT", None)
    env.update(
        {
            "HOME": str(fake_home),
            "PATH": f"{fake_openclaw.parent}:{env['PATH']}",
            "TMPDIR": str(temp_state),
            "MINERVA_RUNNER": str(fake_minerva),
            "MINERVA_NEWS_SOURCES": str(sources_path),
            "MINERVA_IR_REGISTRY": str(ir_path),
            "MINERVA_SKIP_STATUS_CHECK": "1",
            "MINERVA_WORKSPACE_ROOT": str(workspace),
            "INVEST_DB": str(invest_db),
            "MINERVA_CALL_LOG": str(call_log),
            "TIMEOUT_LOG": str(coordinator / "timeouts.log"),
            "AGENT_LOG": str(coordinator / "agents.log"),
            "COLLECTOR_START_LOG": str(coordinator / "collector-starts.log"),
        }
    )
    if extra_env:
        env.update(extra_env)

    resolved_run_date = run_date or date.today().isoformat()
    return subprocess.run(
        ["bash", str(PIPELINE_SCRIPT), resolved_run_date],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _phase_dir(tmp_path: Path, run_date: str) -> Path:
    return (
        tmp_path
        / "workspace"
        / "reports"
        / "03-daily-news"
        / run_date
        / "data"
        / "structured"
        / "news-pipeline"
    )


# ---------------------------------------------------------------------------
# Timeout / validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("MINERVA_BROWSER_TIMEOUT", "0"),
        ("MINERVA_BROWSER_TIMEOUT", "not-a-number"),
        ("MINERVA_WEBFETCH_TIMEOUT", "-1"),
        ("MINERVA_MAX_COLLECTORS", "0"),
    ],
)
def test_collector_timeout_validation_precedes_temp_state(
    tmp_path: Path, variable: str, value: str
) -> None:
    temp_state = tmp_path / "tmp"
    temp_state.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(fake_home), "TMPDIR": str(temp_state), variable: value})

    result = subprocess.run(
        ["bash", str(PIPELINE_SCRIPT), "test-invalid-timeout"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 1
    assert f"{variable} must be a positive integer" in result.stderr
    assert list(temp_state.iterdir()) == []


# ---------------------------------------------------------------------------
# Collector agent selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("collector_agent", "expected"),
    [(None, "main"), ("steve", "steve")],
)
def test_collector_agent_defaults_and_can_be_overridden(
    tmp_path: Path, collector_agent: str | None, expected: str
) -> None:
    extra_env = (
        {"MINERVA_NEWS_COLLECTOR_AGENT": collector_agent}
        if collector_agent is not None
        else None
    )
    run_date = date.today().isoformat()
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "test-source",
                "name": "Test Source",
                "url": "https://example.test/news",
                "access": "web_fetch",
            }
        ],
        extra_env=extra_env,
        run_date=run_date,
    )

    assert result.returncode == 0, result.stderr
    agents = (tmp_path / "coordinator" / "agents.log").read_text(
        encoding="utf-8"
    ).splitlines()
    assert agents == [expected]


# ---------------------------------------------------------------------------
# Aggregate download phases
# ---------------------------------------------------------------------------


def test_aggregate_download_phases_run_before_agent_collectors(
    tmp_path: Path,
) -> None:
    run_date = date.today().isoformat()
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "source-a",
                "name": "Source A",
                "url": "https://example.test/a",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
    )

    assert result.returncode == 0, result.stderr
    calls = (
        tmp_path / "coordinator" / "minerva-calls.log"
    ).read_text(encoding="utf-8").splitlines()

    subcommands = [line for line in calls if line]
    # Finnhub and market-data downloads share the invest.db and RUN_DATE.
    finnhub = next(c for c in subcommands if c.startswith("news download-finnhub"))
    assert f"--date {run_date}" in finnhub
    assert "--db " in finnhub
    assert "--symbol" not in finnhub

    market = next(
        c for c in subcommands if c.startswith("news download-market-data")
    )
    assert f"--date {run_date}" in market
    assert "--db " in market
    assert "--index" not in market

    # Finnhub download precedes agent-collector ingests.
    finnhub_idx = subcommands.index(finnhub)
    ingest_indices = [
        i for i, line in enumerate(subcommands) if line.startswith("news ingest")
    ]
    assert ingest_indices, "expected at least one direct-ingest call"
    assert finnhub_idx < min(ingest_indices)

    # No legacy batch-ingest / extract-files invocations.
    for banned in ("extract-files", "--raw-dir", "--summaries-dir"):
        assert not any(banned in line for line in subcommands), banned


# ---------------------------------------------------------------------------
# Collector orchestration
# ---------------------------------------------------------------------------


def test_collectors_are_isolated_and_ingest_directly(tmp_path: Path) -> None:
    run_date = date.today().isoformat()
    sources = [
        {
            "id": "reuters-markets",
            "name": "Reuters Markets",
            "url": "https://example.test/reuters",
            "access": "browser",
        },
        {
            "id": "web-source",
            "name": "Web Source",
            "url": "https://example.test/web",
            "access": "web_fetch",
        },
    ]
    ir_entries = [
        {
            "security_id": "AMD",
            "company_name": "AMD",
            "feeds": [{"url": "https://example.test/AMD"}],
        },
        {
            "security_id": "NVDA",
            "company_name": "NVDA",
            "feeds": [{"url": "https://example.test/NVDA"}],
        },
    ]

    result = _run_wrapper(
        tmp_path,
        sources=sources,
        ir_entries=ir_entries,
        run_date=run_date,
        extra_env={"MINERVA_MAX_COLLECTORS": "4"},
    )

    assert result.returncode == 0, result.stderr

    # Every collector launched, each got its own timeout row.
    starts = (
        tmp_path / "coordinator" / "collector-starts.log"
    ).read_text(encoding="utf-8").splitlines()
    assert set(starts) == {"reuters-markets", "web-source", "ir-AMD", "ir-NVDA"}

    timeouts = dict(
        line.split("|", 1)
        for line in (
            tmp_path / "coordinator" / "timeouts.log"
        ).read_text(encoding="utf-8").splitlines()
    )
    assert timeouts["reuters-markets"] == "900"
    assert timeouts["web-source"] == "300"
    assert timeouts["ir-AMD"] == "900"

    # Every collector's status.json reports ok.
    collector_dir = _phase_dir(tmp_path, run_date) / "collectors"
    for source_id in ("reuters-markets", "web-source", "ir-AMD", "ir-NVDA"):
        status = json.loads(
            (collector_dir / source_id / "status.json").read_text(encoding="utf-8")
        )
        assert status["status"] == "ok"
        assert status["exit_status"] == 0
        assert status["source_id"] == source_id

    # collectors.json aggregates success totals.
    aggregate = json.loads(
        (_phase_dir(tmp_path, run_date) / "collectors.json").read_text(
            encoding="utf-8"
        )
    )
    assert aggregate["status"] == "ok"
    assert aggregate["failed"] == 0
    assert aggregate["succeeded"] == 4

    # Every collector wrote one row directly to SQLite.
    with sqlite3.connect(tmp_path / "invest.db") as conn:
        rows = {
            row[0]
            for row in conn.execute(
                "SELECT source FROM news ORDER BY source"
            ).fetchall()
        }
    assert rows == {"reuters-markets", "web-source", "ir-AMD", "ir-NVDA"}

    # No .md files or raw-dir aggregation happen for direct-ingest collectors.
    for source_id in ("reuters-markets", "web-source", "ir-AMD", "ir-NVDA"):
        source_files = list((collector_dir / source_id).iterdir())
        assert all(
            path.suffix != ".md" for path in source_files
        ), f"unexpected markdown file under {source_id}: {source_files}"


def test_failed_collector_reports_status_without_blocking_pipeline(
    tmp_path: Path,
) -> None:
    run_date = date.today().isoformat()
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "healthy",
                "name": "Healthy",
                "url": "https://example.test/healthy",
                "access": "web_fetch",
            },
            {
                "id": "broken-feed",
                "name": "Broken",
                "url": "https://example.test/broken",
                "access": "web_fetch",
            },
        ],
        run_date=run_date,
        extra_env={"BROKEN_SOURCE": "broken-feed"},
    )

    assert result.returncode == 0, result.stderr

    collector_dir = _phase_dir(tmp_path, run_date) / "collectors"
    broken_status = json.loads(
        (collector_dir / "broken-feed" / "status.json").read_text(encoding="utf-8")
    )
    healthy_status = json.loads(
        (collector_dir / "healthy" / "status.json").read_text(encoding="utf-8")
    )
    assert broken_status["status"] == "failed"
    assert broken_status["exit_status"] == 7
    assert healthy_status["status"] == "ok"

    aggregate = json.loads(
        (_phase_dir(tmp_path, run_date) / "collectors.json").read_text(
            encoding="utf-8"
        )
    )
    assert aggregate["status"] == "degraded"
    assert aggregate["failed"] == 1
    assert aggregate["succeeded"] == 1
    failed_ids = {row["source_id"] for row in aggregate["failures"]}
    assert failed_ids == {"broken-feed"}

    # The degraded run is still reported on stdout for the operator.
    assert "collector error" in result.stdout


# ---------------------------------------------------------------------------
# Current-date evidence gate
# ---------------------------------------------------------------------------


def test_thin_brief_refused_when_no_current_evidence(tmp_path: Path) -> None:
    """With every collector broken and no override, script exits non-zero."""
    run_date = date.today().isoformat()
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "broken-feed",
                "name": "Broken",
                "url": "https://example.test/broken",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
        extra_env={"BROKEN_SOURCE": "broken-feed"},
    )

    assert result.returncode != 0
    assert "no eligible current-date news evidence" in result.stderr
    assert "MINERVA_ALLOW_THIN_BRIEF=1" in result.stderr


def test_thin_brief_allowed_when_override_set(tmp_path: Path) -> None:
    run_date = date.today().isoformat()
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "broken-feed",
                "name": "Broken",
                "url": "https://example.test/broken",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
        extra_env={
            "BROKEN_SOURCE": "broken-feed",
            "MINERVA_ALLOW_THIN_BRIEF": "1",
        },
    )

    assert result.returncode == 0, result.stderr


def test_rerun_with_existing_rows_does_not_refuse_thin_brief(tmp_path: Path) -> None:
    """Idempotence: if RUN_DATE rows already exist, zero new inserts is OK."""
    run_date = date.today().isoformat()
    # First run: healthy source populates invest.db.
    first = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "healthy",
                "name": "Healthy",
                "url": "https://example.test/healthy",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
    )
    assert first.returncode == 0, first.stderr

    # Second run: same date, every collector broken, but existing row remains.
    second = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "broken-feed",
                "name": "Broken",
                "url": "https://example.test/broken",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
        extra_env={"BROKEN_SOURCE": "broken-feed"},
    )
    assert second.returncode == 0, second.stderr

    evidence = json.loads(
        (_phase_dir(tmp_path, run_date) / "current-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["current_rows"] >= 1


def test_current_evidence_uses_new_york_day_boundaries(tmp_path: Path) -> None:
    """02:30 UTC on the following date still belongs to the prior ET run day."""
    run_date = "2026-07-27"
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "overnight",
                "name": "Overnight",
                "url": "https://example.test/overnight",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
        extra_env={"PUBLISHED_AT": "2026-07-28T02:30:00Z"},
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(
        (_phase_dir(tmp_path, run_date) / "current-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["current_rows"] == 1


def test_current_evidence_does_not_treat_utc_date_as_market_date(
    tmp_path: Path,
) -> None:
    """02:30 UTC on RUN_DATE belongs to the previous New York market day."""
    run_date = "2026-07-27"
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "prior-market-day",
                "name": "Prior Market Day",
                "url": "https://example.test/prior-market-day",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
        extra_env={
            "MINERVA_ALLOW_THIN_BRIEF": "1",
            "PUBLISHED_AT": "2026-07-27T02:30:00Z",
        },
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(
        (_phase_dir(tmp_path, run_date) / "current-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["current_rows"] == 0


# ---------------------------------------------------------------------------
# Outer-Sol handoff artifact
# ---------------------------------------------------------------------------


def test_outer_sol_handoff_is_emitted_with_summary_instructions(tmp_path: Path) -> None:
    run_date = date.today().isoformat()
    result = _run_wrapper(
        tmp_path,
        sources=[
            {
                "id": "healthy",
                "name": "Healthy",
                "url": "https://example.test/healthy",
                "access": "web_fetch",
            }
        ],
        run_date=run_date,
    )
    assert result.returncode == 0, result.stderr

    handoff = json.loads(
        (_phase_dir(tmp_path, run_date) / "outer-sol-handoff.json").read_text(
            encoding="utf-8"
        )
    )
    assert handoff["final_agent"] == "outer-cron-sol"
    assert handoff["date"] == run_date
    assert handoff["status"] == "ready"
    assert Path(handoff["instructions"]).name == "morning_brief_outer_sol.md"
    assert Path(handoff["instructions"]).is_file()
    # Handoff enumerates the summarize -> persist -> report chain.
    steps_blob = " ".join(handoff["steps"])
    assert "minerva summarize" in steps_blob
    assert "morning-brief-report.md" in handoff["report_output"]
    assert "slack-brief.md" in handoff["slack_brief_output"]

    # The script hands delivery back to the outer cron layer.
    assert "Do not post Slack from this script." in result.stdout


# ---------------------------------------------------------------------------
# Prompt template safety
# ---------------------------------------------------------------------------


def test_prompts_render_direct_ingest_placeholders() -> None:
    """Templates use the shared placeholder set consumed by the wrapper."""
    for name in ("collect_news.md", "collect_news_webfetch.md"):
        text = (REPO_ROOT / "scripts" / "prompts" / name).read_text(
            encoding="utf-8"
        )
        for placeholder in (
            "{{SOURCE_ROOT}}",
            "{{CANDIDATE_FILE}}",
            "{{LOOKUP_FILE}}",
            "{{NEWS_EXIST_COMMAND}}",
            "{{NEWS_INGEST_COMMAND}}",
            "{{INVEST_DB}}",
            "{{SOURCE_ID}}",
            "{{URL}}",
            "{{DATE}}",
        ):
            assert placeholder in text, f"{name} missing {placeholder}"
        # Neither template invokes summarizers, Slack, or article files.
        assert "summarizer" in text
        assert "Slack" in text or "slack" in text
        assert ".md" not in text.split("published")[0]
