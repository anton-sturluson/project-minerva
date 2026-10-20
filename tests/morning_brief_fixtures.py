"""Local command doubles for the single-entry-point morning brief tests."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FIXTURE_DIR: Path = REPO_ROOT / "tests/fixtures/morning_brief"
SYNTHESIS_JOB_ID: str = "synthetic-synthesis-job"


def write_executable(path: Path, content: str) -> Path:
    """Write a command double without changing any installed command."""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def pipeline_env(tmp_path: Path, run_date: str) -> dict[str, str]:
    """Isolate configuration and replace every external orchestration command."""
    env: dict[str, str] = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("MINERVA_", "UV_", "TEST_"))
        and key not in {"INVEST_DB", "BASH_ENV", "ENV"}
    }
    bin_dir: Path = tmp_path / "bin"
    directory: Path
    for directory in (bin_dir, tmp_path / "home", tmp_path / "tmp", tmp_path / "coordinator"):
        directory.mkdir(exist_ok=True)
    env.update({
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "TMPDIR": str(tmp_path / "tmp"),
        "MINERVA_RUNNER": "/bin/false",
        "MINERVA_WORKSPACE_ROOT": str(tmp_path / "workspace"),
        "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": str(FIXTURE_DIR / "holdings.csv"),
        "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": str(FIXTURE_DIR / "transactions.csv"),
        "INVEST_DB": str(tmp_path / "invest.db"),
        "MINERVA_CALL_LOG": str(tmp_path / "coordinator/minerva-calls.log"),
        "TEST_REPO_ROOT": str(REPO_ROOT),
        "TEST_RUN_DATE": run_date,
        "TEST_PYTHON": sys.executable,
        "TEST_FIXTURES": str(Path(__file__).resolve()),
        "TEST_GIT_LOG": str(tmp_path / "coordinator/git.log"),
        "TEST_SYNTHESIS_LOG": str(tmp_path / "coordinator/synthesis.log"),
    })
    write_executable(bin_dir / "git", r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$TEST_GIT_LOG"
case "$*" in
  'rev-parse --git-dir')
    if [[ "${TEST_GIT_CASE:-}" == linked-worktree ]]; then echo ../primary/.git/worktrees/test; else echo .git; fi ;;
  'rev-parse --show-toplevel')
    if [[ "${TEST_GIT_CASE:-}" == wrong-root ]]; then echo /synthetic/wrong-root; else echo "$TEST_REPO_ROOT"; fi ;;
  'symbolic-ref --quiet --short HEAD')
    [[ "${TEST_GIT_CASE:-}" != detached ]] || exit 9
    if [[ "${TEST_GIT_CASE:-}" == wrong-branch ]]; then echo feature; else echo main; fi ;;
  'status --porcelain --untracked-files=all')
    [[ "${TEST_GIT_CASE:-}" != status-failed ]] || exit 9
    if [[ "${TEST_GIT_CASE:-}" == dirty ]] ||
       { [[ "${TEST_GIT_CASE:-}" == dirty-after-ff ]] && grep -q '^merge ' "$TEST_GIT_LOG"; }; then
      echo ' M synthetic-file'
    fi ;;
  'fetch --quiet origin refs/heads/main:refs/remotes/origin/main')
    [[ "${TEST_GIT_CASE:-}" != fetch-failed ]] || exit 21 ;;
  'merge --ff-only --quiet origin/main')
    [[ "${TEST_GIT_CASE:-}" != ff-failed ]] || exit 22 ;;
  'rev-parse --verify HEAD') echo abc123 ;;
  'rev-parse --verify refs/remotes/origin/main')
    if [[ "${TEST_GIT_CASE:-}" == unequal-refs ]]; then echo def456; else echo abc123; fi ;;
  *) echo "unexpected synthetic git command: $*" >&2; exit 90 ;;
esac
''')
    real_date: str = shutil.which("date") or "/bin/date"
    write_executable(bin_dir / "date", r'''#!/usr/bin/env bash
set -euo pipefail
if [[ "$#" == 1 && "$1" == +%F ]]; then
  [[ "${TZ:-}" == America/New_York ]] || exit 92
  printf '%s\n' "$TEST_RUN_DATE"
else
  exec ''' + shlex.quote(real_date) + ''' "$@"
fi
''')
    write_executable(bin_dir / "uv", r'''#!/usr/bin/env bash
set -euo pipefail
[[ "$#" -ge 5 && "$1" == run && "$2" == --project &&
   "$3" == "$TEST_REPO_ROOT" && "$4" == python &&
   "$5" == "$TEST_REPO_ROOT/scripts/morning_brief_helper.py" ]] || exit 93
shift 4
exec "$TEST_PYTHON" "$@"
''')
    write_executable(bin_dir / "openclaw", r'''#!/usr/bin/env bash
exec "$TEST_PYTHON" "$TEST_FIXTURES" "$@"
''')
    write_executable(bin_dir / "browser", "#!/usr/bin/env bash\necho 'unexpected browser call' >&2\nexit 94\n")
    return env


def prepare_fixture() -> None:
    """Create minimal local prep outputs for the real manifest and handoff helpers."""
    report: Path = (
        Path(os.environ["MINERVA_WORKSPACE_ROOT"])
        / "reports/03-daily-news" / os.environ["TEST_RUN_DATE"]
    )
    prepared: Path = report / "data/structured/prepared-evidence.json"
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_text(json.dumps({"date": os.environ["TEST_RUN_DATE"], "grouped_events": {}}))
    manifest: Path = report / "data/raw/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    mode: str = os.environ.get("TEST_MANIFEST_MODE", "success")
    sources: dict[str, dict[str, str]] = {
        name: {"status": "success"} for name in ("filings", "earnings", "market", "prep")
    }
    if mode == "error":
        sources["prep"]["status"] = "error"
    elif mode == "missing":
        del sources["market"]
    manifest.write_text(json.dumps({"sources": sources}))


def final_writer(args: list[str]) -> int:
    """Reject premature handoffs instead of ever starting a real agent."""
    with Path(os.environ["TEST_SYNTHESIS_LOG"]).open("a") as log:
        log.write(shlex.join(args) + "\n")
    assert args == ["automations", "run", SYNTHESIS_JOB_ID, "--json"], args
    phase_dir: Path = (
        Path(os.environ["MINERVA_WORKSPACE_ROOT"])
        / "reports/03-daily-news" / os.environ["TEST_RUN_DATE"]
        / "data/structured/news-pipeline"
    )
    handoff: dict[str, str] = json.loads((phase_dir / "synthesis-handoff.json").read_text())
    assert handoff["status"] == "ready"
    assert handoff["date"] == os.environ["TEST_RUN_DATE"]
    assert Path(handoff["prepared_evidence"]).is_file()
    assert Path(handoff["evidence_stats"]).is_file()
    assert json.loads((phase_dir / "manifest-check.status.json").read_text())["status"] == "ok"
    exit_code: int = int(os.environ.get("TEST_ADMISSION_EXIT", "0"))
    print("synthetic admission error" if exit_code else "synthetic final writer admitted")
    return exit_code


if __name__ == "__main__":
    if sys.argv[1:] == ["prepare"]:
        prepare_fixture()
    else:
        sys.exit(final_writer(sys.argv[1:]))
