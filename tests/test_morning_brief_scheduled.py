"""The scheduled launcher runs sync, then the existing agent job, or stops."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case,events", [
    ("success", ["sync", "agent"]),
    ("sync-failed", ["sync"]),
    ("agent-failed", ["sync", "agent"]),
    ("missing-source", []),
    ("dirty", []),
    ("wrong-branch", []),
    ("git-status-failed", []),
])
def test_scheduled_sync_then_agent(tmp_path: Path, case: str, events: list[str]) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "scripts").mkdir()
    launcher = checkout / "scripts/run_morning_brief_scheduled.sh"
    launcher.write_text((ROOT / "scripts/run_morning_brief_scheduled.sh").read_text())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "git": '''#!/usr/bin/env bash
case "$*" in
  'rev-parse --show-toplevel') echo "$CHECKOUT" ;;
  'symbolic-ref --quiet --short HEAD')
    if [[ "$CASE" == wrong-branch ]]; then echo feature; else echo main; fi ;;
  'status --porcelain --untracked-files=all')
    [[ "$CASE" != git-status-failed ]] || exit 9
    if [[ "$CASE" == dirty ]]; then echo ' M file'; fi ;;
  'rev-parse --verify HEAD'|'rev-parse --verify refs/remotes/origin/main') echo abc123 ;;
  'fetch --quiet origin refs/heads/main:refs/remotes/origin/main'|'merge --ff-only --quiet origin/main')
    echo 'synthetic git progress' >&2 ;;
  *) exit 90 ;;
esac
''',
        "uv": '''#!/usr/bin/env bash
echo sync >> "$EVENTS"
printf '%s\\n' "$@" > "$SYNC_ARGS"
echo 'synthetic sync output'
if [[ "$CASE" == sync-failed ]]; then exit 7; fi
echo 'synthetic dependency setup' >&2
''',
        "openclaw": '''#!/usr/bin/env bash
[[ "$*" == 'automations run synthetic-job --json' ]] || exit 91
echo agent >> "$EVENTS"
if [[ "$CASE" == agent-failed ]]; then echo 'synthetic admission error'; exit 8; fi
echo '{"ok":true,"enqueued":true}'
''',
    }
    for name, content in commands.items():
        path = bin_dir / name
        path.write_text(content)
        path.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MINERVA_", "UV_"))}
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "CHECKOUT": str(checkout), "CASE": case,
        "EVENTS": str(tmp_path / "events"), "SYNC_ARGS": str(tmp_path / "sync-args"),
        "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": "https://example.test/holdings.csv?gid=1&format=csv",
        "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": "https://example.test/transactions.csv",
        "MINERVA_PORTFOLIO_WATCHLIST_SOURCE": str(tmp_path / "watchlist with spaces.json"),
    })
    if case == "missing-source":
        env.pop("MINERVA_PORTFOLIO_HOLDINGS_SOURCE")
    result = subprocess.run(
        ["bash", str(launcher), "--handoff-job", "synthetic-job"],
        env=env, capture_output=True, text=True, check=False,
    )
    event_file = Path(env["EVENTS"])
    assert (event_file.read_text().splitlines() if event_file.exists() else []) == events
    assert (result.returncode == 0) == (case == "success")
    if case == "success":
        assert result.stdout == "NO_REPLY\n"
        assert result.stderr == ""
        args = Path(env["SYNC_ARGS"]).read_text().splitlines()
        assert args[0:6] == ["run", "--project", str(checkout), "minerva", "portfolio", "sync"]
        for flag, name in [("holdings", "HOLDINGS"), ("transactions", "TRANSACTIONS"), ("watchlist", "WATCHLIST")]:
            assert args[args.index(f"--{flag}-source") + 1] == env[f"MINERVA_PORTFOLIO_{name}_SOURCE"]
    else:
        assert result.stderr
        if case == "sync-failed":
            assert "synthetic sync output" in result.stderr
        if case == "agent-failed":
            assert "synthetic admission error" in result.stderr
