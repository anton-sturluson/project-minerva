"""Synthetic end-to-end coverage for the deterministic portfolio boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO
from zoneinfo import ZoneInfo

import pytest


type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]

ROOT: Path = Path(__file__).resolve().parents[1]
PRESYNC: Path = ROOT / "scripts" / "morning_brief_presync.py"
PIPELINE: Path = ROOT / "scripts" / "run_morning_brief.sh"
RUN_DATE: str = "2026-04-08"
JOB_ID: str = "00000000-0000-4000-8000-000000000001"
RECEIPT_NAME: str = "portfolio-sync.receipt.json"


def executable(path: Path, content: str) -> None:
    """Install a fake external process, not a patched application function."""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Keep every input and output local and replace all external agents."""
    key: str
    value: str
    environment: dict[str, str] = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("MINERVA_", "UV_", "OPENCLAW_")) and key != "INVEST_DB"
    }
    home: Path = tmp_path / "home"
    home.mkdir()
    sources: Path = tmp_path / "synthetic inputs with spaces"
    sources.mkdir()
    (sources / "holdings.csv").write_text(
        "Ticker,Shares,Portfolio\nALFA,2,Main\nBETA,3,Other\n", encoding="utf-8",
    )
    (sources / "transactions.csv").write_text(
        "Date,Type,Symbol,Shares,Price (USD),Total (USD),Portfolio\n"
        "04/08/2026,Buy,ALFA,2,10,20,Main\n"
        "04/08/2026,Buy,BETA,3,10,30,Other\n", encoding="utf-8",
    )
    bin_dir: Path = tmp_path / "bin"
    bin_dir.mkdir()
    executable(
        bin_dir / "openclaw",
        f"#!{sys.executable}\n" + '''"""Record admission observations without contacting a gateway."""
import json
import os
import sys
from pathlib import Path
from typing import TextIO

workspace: Path = Path(os.environ["MINERVA_WORKSPACE_ROOT"])
phase_dir: Path = Path(os.environ["MINERVA_NEWS_ARTIFACT_DIR"])
syncs: list[str] = (workspace / "data/01-portfolio/history/sync-log.jsonl").read_text().splitlines()
stream: TextIO
with Path(os.environ["KICKOFF_LOG"]).open("a") as stream:
    stream.write(json.dumps({"args": sys.argv[1:], "sync_count": len(syncs),
                            "receipt_exists": (phase_dir / "portfolio-sync.receipt.json").is_file()}) + "\\n")
print(os.environ["KICKOFF_OUTPUT"])
sys.exit(int(os.environ.get("KICKOFF_EXIT", "0")))
''',
    )
    executable(
        bin_dir / "pipeline-minerva",
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$PHASE_LOG\"\n"
        "if [[ \"${FAIL_PIPELINE:-0}\" == 1 ]]; then\n"
        "  echo 'synthetic stdout-only phase failure'\n"
        "  exit 7\n"
        "fi\n",
    )
    environment.update({
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{environment['PATH']}",
        "UV_PROJECT_ENVIRONMENT": str(ROOT / ".venv"),
        "UV_CACHE_DIR": str(ROOT / ".tmp" / "uv-cache"),
        "MINERVA_WORKSPACE_ROOT": str(tmp_path / "workspace"),
        "MINERVA_NEWS_ARTIFACT_DIR": str(tmp_path / "artifacts"),
        "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": str(sources / "holdings.csv"),
        "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": str(sources / "transactions.csv"),
        "MINERVA_SKIP_NEWS": "1",
        "MINERVA_SKIP_STATUS_CHECK": "1",
        "MINERVA_RUNNER": str(bin_dir / "pipeline-minerva"),
        "PHASE_LOG": str(tmp_path / "phases.log"),
        "KICKOFF_LOG": str(tmp_path / "kickoffs.jsonl"),
        "KICKOFF_OUTPUT": json.dumps({
            "ok": True, "enqueued": True, "runId": f"manual:{JOB_ID}:123:1",
            "processInstanceId": "synthetic-process",
        }),
    })
    return environment


def presync(env: dict[str, str], *args: str, with_date: bool = True) -> subprocess.CompletedProcess[str]:
    """Run the real helper and portfolio CLI against synthetic local files."""
    return subprocess.run(
        [sys.executable, str(PRESYNC), *(["--date", RUN_DATE] if with_date else []), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )


def pipeline(env: dict[str, str], *, synced: bool = True) -> subprocess.CompletedProcess[str]:
    """Use real receipt validation but no live structured/news collectors."""
    return subprocess.run(
        ["bash", str(PIPELINE), RUN_DATE, *(["--use-synced-portfolio"] if synced else [])],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )


def artifact(env: dict[str, str], name: str) -> Path:
    """Locate an artifact from this isolated test run."""
    return Path(env["MINERVA_NEWS_ARTIFACT_DIR"]) / name


def test_sync_then_one_admission_and_consume_without_duplicate_sync(env: dict[str, str]) -> None:
    """The agent sees Main-only state, and consuming does not touch sources."""
    result: subprocess.CompletedProcess[str] = presync(env, "--handoff-job", JOB_ID)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "NO_REPLY\n"
    line: str
    observations: list[dict[str, JSONValue]] = [
        json.loads(line) for line in Path(env["KICKOFF_LOG"]).read_text().splitlines()
    ]
    assert observations == [{
        "args": ["automations", "run", JOB_ID, "--json"],
        "sync_count": 1, "receipt_exists": True,
    }]
    workspace: Path = Path(env["MINERVA_WORKSPACE_ROOT"])
    row: dict[str, JSONValue]
    holdings: list[dict[str, JSONValue]] = json.loads((workspace / "data/01-portfolio/current/holdings.json").read_text())
    transactions: list[dict[str, JSONValue]] = json.loads((workspace / "data/01-portfolio/transactions.json").read_text())
    assert [row["ticker"] for row in holdings] == ["ALFA"]
    assert [row["ticker"] for row in transactions] == ["ALFA"]
    receipt_text: str = artifact(env, RECEIPT_NAME).read_text()
    assert env["MINERVA_PORTFOLIO_HOLDINGS_SOURCE"] not in receipt_text
    assert env["MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE"] not in receipt_text
    assert '"local-watchlist"' in receipt_text
    status_before: str = artifact(env, "portfolio-sync.status.json").read_text()
    assert json.loads(status_before) == {
        "phase": "portfolio-sync", "status": "ok", "exit_status": 0,
        "stdout": str(artifact(env, "portfolio-sync.json")),
        "stderr": str(artifact(env, "portfolio-sync.stderr.log")),
    }
    # Deliberately remove the original files and source configuration. A consumer
    # must need only the receipt and synced data, not regenerated source URLs.
    Path(env.pop("MINERVA_PORTFOLIO_HOLDINGS_SOURCE")).unlink()
    Path(env.pop("MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE")).unlink()
    result = pipeline(env)
    assert result.returncode == 0, result.stderr
    assert Path(env["PHASE_LOG"]).read_text().splitlines() == [
        f"brief filings --date {RUN_DATE}",
        f"brief earnings --date {RUN_DATE} --provider finnhub",
        f"brief market --date {RUN_DATE} --provider finnhub",
        f"brief prep --date {RUN_DATE}",
    ]
    assert len((workspace / "data/01-portfolio/history/sync-log.jsonl").read_text().splitlines()) == 1
    assert artifact(env, "portfolio-sync.status.json").read_text() == status_before
    assert artifact(env, RECEIPT_NAME).read_text() == receipt_text


def test_sync_failure_invalidates_old_receipt_and_surfaces_stdout(env: dict[str, str]) -> None:
    """A real schema error cannot leave success evidence or start the child."""
    assert presync(env, "--sync-only").returncode == 0
    Path(env["MINERVA_PORTFOLIO_HOLDINGS_SOURCE"]).write_text("Ticker,Portfolio\nBETA,Other\n")
    result: subprocess.CompletedProcess[str] = presync(env, "--handoff-job", JOB_ID)
    assert result.returncode != 0
    assert not artifact(env, RECEIPT_NAME).exists()
    assert not Path(env["KICKOFF_LOG"]).exists()
    assert "zero valid Main" in result.stderr
    assert str(artifact(env, "portfolio-sync.json")) in result.stderr
    assert artifact(env, "portfolio-sync.stderr.log").read_text() == ""
    assert json.loads(artifact(env, "portfolio-sync.status.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("source", ["HOLDINGS", "TRANSACTIONS"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_source_fails_closed_with_cached_state(env: dict[str, str], source: str, value: str | None) -> None:
    """Cached data and an old receipt do not replace required input sources."""
    assert presync(env, "--sync-only").returncode == 0
    key: str = f"MINERVA_PORTFOLIO_{source}_SOURCE"
    if value is None:
        del env[key]
    else:
        env[key] = value
    result: subprocess.CompletedProcess[str] = presync(env, "--handoff-job", JOB_ID)
    assert result.returncode != 0
    assert key in result.stderr
    assert json.loads(artifact(env, "portfolio-sync.status.json").read_text())["status"] == "failed"
    assert not artifact(env, RECEIPT_NAME).exists()
    assert not Path(env["KICKOFF_LOG"]).exists()


@pytest.mark.parametrize("damage", [
    "missing", "malformed", "version", "date", "stale", "future", "naive",
    "holdings", "transactions", "watchlist", "universe", "universe-override",
])
def test_bad_receipt_stops_consumer_before_any_phase(env: dict[str, str], damage: str) -> None:
    """Every covered receipt failure rejects instead of falling back to sync."""
    assert presync(env, "--sync-only").returncode == 0
    receipt: Path = artifact(env, RECEIPT_NAME)
    payload: dict[str, JSONValue] = json.loads(receipt.read_text())
    if damage == "missing":
        receipt.unlink()
    elif damage == "malformed":
        receipt.write_text("not JSON")
    elif damage == "universe-override":
        env["MINERVA_PORTFOLIO_UNIVERSE"] = str(receipt.parent / "different-universe.json")
    elif damage in ("holdings", "transactions", "watchlist", "universe"):
        relative: str = "transactions.json" if damage == "transactions" else f"current/{damage}.json"
        path: Path = Path(env["MINERVA_WORKSPACE_ROOT"]) / "data/01-portfolio" / relative
        path.write_text("[]\n")
        # The default watchlist is already empty; change its exact bytes too.
        if damage == "watchlist":
            path.write_text("[ ]\n")
    else:
        if damage == "version":
            payload["version"] = 2
        elif damage == "date":
            payload["as_of"] = "2026-04-07"
        elif damage == "stale":
            payload["completed_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        elif damage == "future":
            payload["completed_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        elif damage == "naive":
            payload["completed_at"] = datetime.now().isoformat()
        receipt.write_text(json.dumps(payload))
    result: subprocess.CompletedProcess[str] = pipeline(env)
    assert result.returncode != 0
    assert "error[portfolio-presync]" in result.stderr
    assert not Path(env["PHASE_LOG"]).exists()
    assert not Path(env["KICKOFF_LOG"]).exists()


@pytest.mark.parametrize(("output", "exit_status"), [
    ('{"ok":true,"ran":false,"reason":"already-running"}', "0"),
    ('{"ok":true,"enqueued":true}', "0"),
    ('{"ok":false,"enqueued":true,"runId":"synthetic"}', "0"),
    ("synthetic gateway unavailable", "7"),
    ("not JSON", "0"),
])
def test_kickoff_failure_reports_separate_stdout_diagnostics(env: dict[str, str], output: str, exit_status: str) -> None:
    """A zero exit or ok flag alone is not admission; no polling is performed."""
    env.update({"KICKOFF_OUTPUT": output, "KICKOFF_EXIT": exit_status})
    result: subprocess.CompletedProcess[str] = presync(env, "--handoff-job", JOB_ID)
    assert result.returncode != 0
    assert "NO_REPLY" not in result.stdout
    assert output in result.stderr
    assert str(artifact(env, "portfolio-handoff.json")) in result.stderr
    assert artifact(env, RECEIPT_NAME).is_file()
    assert json.loads(artifact(env, "portfolio-sync.status.json").read_text())["status"] == "ok"
    assert json.loads(artifact(env, "portfolio-handoff.status.json").read_text())["status"] == "failed"
    assert len(Path(env["KICKOFF_LOG"]).read_text().splitlines()) == 1


def test_default_date_is_new_york_and_sync_only_has_no_kickoff(env: dict[str, str]) -> None:
    """Controlled verification defaults to the market's calendar date."""
    result: subprocess.CompletedProcess[str] = presync(env, "--sync-only", with_date=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(artifact(env, RECEIPT_NAME).read_text())["as_of"] == datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    assert not Path(env["KICKOFF_LOG"]).exists()


def test_existing_pipeline_reports_stdout_only_error(env: dict[str, str]) -> None:
    """Default mode still syncs, and retains useful CLI errors on stdout."""
    env["FAIL_PIPELINE"] = "1"
    result: subprocess.CompletedProcess[str] = pipeline(env, synced=False)
    assert result.returncode == 7
    assert "synthetic stdout-only phase failure" in result.stderr
    assert str(artifact(env, "portfolio-sync.json")) in result.stderr
    assert Path(env["PHASE_LOG"]).read_text().startswith("portfolio sync ")


def git(directory: Path, *args: str) -> str:
    """Use only local Git fixtures; do not create commits or contact remotes."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(directory), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("state", ["clean", "behind", "dirty", "untracked", "branch", "detached", "ahead", "fetch-failure", "runner-failure"])
def test_scheduled_clean_main_preflight(env: dict[str, str], tmp_path: Path, state: str) -> None:
    """Real local Git rejects unsafe state before any project runner starts."""
    # Reuse existing public repository history read-only. No commits or pushes
    # are needed, and every ref/checkout mutation below is inside tmp_path.
    origin: Path = tmp_path / "origin.git"
    checkout: Path = tmp_path / "checkout"
    git(tmp_path, "clone", "--quiet", "--bare", "--shared", str(ROOT), str(origin))
    git(origin, "update-ref", "refs/heads/main", "HEAD")
    git(tmp_path, "clone", "--quiet", "--shared", "--branch", "main", str(origin), str(checkout))
    expected_head: str = git(origin, "rev-parse", "main")
    if state == "behind":
        git(checkout, "reset", "--hard", "HEAD^")
    elif state == "dirty":
        (checkout / "README.md").write_text("synthetic unexpected edit\n")
    elif state == "untracked":
        git(checkout, "config", "status.showUntrackedFiles", "no")
        (checkout / "unexpected.txt").write_text("synthetic untracked file\n")
    elif state == "branch":
        git(checkout, "switch", "-c", "synthetic-feature")
    elif state == "detached":
        git(checkout, "checkout", "--detach")
    elif state == "ahead":
        git(origin, "update-ref", "refs/heads/main", "main^")
        git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD^")
    elif state == "fetch-failure":
        git(checkout, "remote", "set-url", "origin", str(tmp_path / "nonexistent-origin"))
    head_before: str = git(checkout, "rev-parse", "HEAD")
    launcher: Path = checkout / "scripts/synthetic-scheduled.sh"
    launcher.write_text((ROOT / "scripts/run_morning_brief_scheduled.sh").read_text())
    stream: TextIO
    with (checkout / ".git/info/exclude").open("a") as stream:
        stream.write("\n/scripts/synthetic-scheduled.sh\n")
    uv_marker: Path = tmp_path / "uv-invocation"
    env["UV_MARKER"] = str(uv_marker)
    env["SYNTHETIC_UV_FAIL"] = "1" if state == "runner-failure" else "0"
    executable(
        tmp_path / "bin/uv",
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$UV_PROJECT_ENVIRONMENT\" \"$*\" > \"$UV_MARKER\"\n"
        "echo 'synthetic dependency setup' >&2\n"
        "if [[ \"$SYNTHETIC_UV_FAIL\" == 1 ]]; then echo 'synthetic runner failure' >&2; exit 9; fi\n"
        "echo NO_REPLY\n",
    )
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["bash", str(launcher), "--handoff-job", JOB_ID],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    if state in ("clean", "behind"):
        assert result.returncode == 0, result.stderr
        assert result.stdout == "NO_REPLY\n"
        assert result.stderr == ""
        assert git(checkout, "rev-parse", "HEAD") == expected_head
        assert git(checkout, "status", "--porcelain") == ""
        assert uv_marker.read_text().splitlines() == [
            str(checkout / ".venv"),
            f"run --project {checkout} python {checkout}/scripts/morning_brief_presync.py --handoff-job {JOB_ID}",
        ]
    elif state == "runner-failure":
        assert result.returncode == 9
        assert result.stdout == ""
        assert "synthetic runner failure" in result.stderr
        assert uv_marker.exists()
        assert git(checkout, "rev-parse", "HEAD") == head_before
    else:
        assert result.returncode != 0
        assert not uv_marker.exists()
        assert git(checkout, "rev-parse", "HEAD") == head_before
        if state == "dirty":
            assert (checkout / "README.md").read_text() == "synthetic unexpected edit\n"
        if state == "untracked":
            assert (checkout / "unexpected.txt").read_text() == "synthetic untracked file\n"


def test_scheduled_launcher_refuses_linked_worktree(env: dict[str, str], tmp_path: Path) -> None:
    """The scheduled entry point must stop before fetch, uv, or source access."""
    checkout: Path = tmp_path / "linked"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: synthetic-unused-location\n")
    launcher: Path = checkout / "scripts/run_morning_brief_scheduled.sh"
    launcher.write_text((ROOT / "scripts/run_morning_brief_scheduled.sh").read_text())
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["bash", str(launcher), "--sync-only"],
        cwd=checkout, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "primary checkout" in result.stderr
    assert not artifact(env, RECEIPT_NAME).exists()
    assert not Path(env["KICKOFF_LOG"]).exists()
