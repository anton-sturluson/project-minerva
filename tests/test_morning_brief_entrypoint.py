"""Preflight, sync, collection, and writer gates for the single entry point."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.morning_brief_fixtures import SYNTHESIS_JOB_ID
from tests.test_news_collection import _phase_dir, _run_wrapper

RUN_DATE: str = "2026-04-08"


@pytest.mark.parametrize(("case", "exit_code"), [
    ("linked-worktree", 1),
    ("wrong-root", 1),
    ("wrong-branch", 1),
    ("detached", 1),
    ("dirty", 1),
    ("status-failed", 1),
    ("fetch-failed", 21),
    ("ff-failed", 22),
    ("dirty-after-ff", 1),
    ("unequal-refs", 1),
])
def test_preflight_failure_blocks_all_work(tmp_path: Path, case: str, exit_code: int) -> None:
    """Only a clean primary main, fast-forwarded to origin/main, can collect."""
    result: subprocess.CompletedProcess[str] = _run_wrapper(
        tmp_path, sources=[], run_date=RUN_DATE,
        extra_env={"TEST_GIT_CASE": case, "MINERVA_SKIP_NEWS": "1"},
    )

    assert result.returncode == exit_code, result.stderr
    assert (tmp_path / "coordinator/minerva-calls.log").read_text() == ""
    assert not (tmp_path / "coordinator/synthesis.log").exists()
    assert not (tmp_path / "workspace").exists()
    assert list((tmp_path / "tmp").iterdir()) == []
    if case in {"linked-worktree", "wrong-root", "wrong-branch", "detached", "dirty", "status-failed"}:
        # Reject an unsafe initial checkout before attempting any Git update.
        git_calls: list[str] = (tmp_path / "coordinator/git.log").read_text().splitlines()
        assert not any(call.startswith(("fetch ", "merge ")) for call in git_calls)


@pytest.mark.parametrize("source", ["HOLDINGS", "TRANSACTIONS"])
@pytest.mark.parametrize("value", [None, ""])
def test_required_sources_must_be_configured(
    tmp_path: Path, source: str, value: str | None,
) -> None:
    """Missing or empty inputs fail without refreshing Git or starting work."""
    result: subprocess.CompletedProcess[str] = _run_wrapper(
        tmp_path, sources=[], run_date=RUN_DATE,
        extra_env={f"MINERVA_PORTFOLIO_{source}_SOURCE": value},
    )

    assert result.returncode == 1
    assert f"{source.lower()} source must be configured" in result.stderr
    assert (tmp_path / "coordinator/minerva-calls.log").read_text() == ""
    assert not (tmp_path / "coordinator/git.log").exists()
    assert not (tmp_path / "coordinator/synthesis.log").exists()


@pytest.mark.parametrize("args", [
    [], [""], [SYNTHESIS_JOB_ID, RUN_DATE],
    [SYNTHESIS_JOB_ID, "--use-synced-portfolio"],
    [SYNTHESIS_JOB_ID, "--sync-only"],
])
def test_only_one_synthesis_job_argument_is_accepted(tmp_path: Path, args: list[str]) -> None:
    """Optional dates and removed sync modes are not compatibility paths."""
    result: subprocess.CompletedProcess[str] = _run_wrapper(
        tmp_path, sources=[], run_date=RUN_DATE, args=args,
    )

    assert result.returncode == 1
    assert "SYNTHESIS_JOB_ID" in result.stderr
    assert "usage:" in result.stderr
    assert (tmp_path / "coordinator/minerva-calls.log").read_text() == ""
    assert not (tmp_path / "coordinator/git.log").exists()
    assert not (tmp_path / "coordinator/synthesis.log").exists()


@pytest.mark.parametrize(("extra_env", "phase", "exit_code", "diagnostic"), [
    ({"TEST_FAIL_PHASE": "portfolio sync"}, "portfolio-sync", 7, "synthetic portfolio sync failure"),
    ({"TEST_FAIL_PHASE": "brief earnings"}, "earnings", 7, "synthetic brief earnings failure"),
    ({"TEST_FAIL_PHASE": "brief prep"}, "prep", 7, "synthetic brief prep failure"),
    ({"TEST_MANIFEST_MODE": "error"}, "manifest-check", 1, "blocking morning-brief collection errors"),
    ({"TEST_MANIFEST_MODE": "missing"}, "manifest-check", 1, "missing manifest source entries"),
])
def test_failed_preparation_never_starts_final_writer(
    tmp_path: Path, extra_env: dict[str, str | None], phase: str,
    exit_code: int, diagnostic: str,
) -> None:
    """Phase failures retain diagnostics and stop before handoff or admission."""
    result: subprocess.CompletedProcess[str] = _run_wrapper(
        tmp_path, sources=[], run_date=RUN_DATE,
        extra_env={"MINERVA_SKIP_NEWS": "1", **extra_env},
    )

    assert result.returncode == exit_code
    assert diagnostic in result.stderr
    assert not (tmp_path / "coordinator/synthesis.log").exists()
    phase_dir: Path = _phase_dir(tmp_path, RUN_DATE)
    assert not (phase_dir / "synthesis-handoff.json").exists()
    status: dict[str, str | int] = json.loads((phase_dir / f"{phase}.status.json").read_text())
    assert status["status"] == "failed"
    assert status["exit_status"] == exit_code
    if phase == "portfolio-sync":
        assert len((tmp_path / "coordinator/minerva-calls.log").read_text().splitlines()) == 1


def test_handoff_write_failure_never_starts_final_writer(tmp_path: Path) -> None:
    """A failed handoff write cannot admit synthesis even after successful prep."""
    handoff: Path = _phase_dir(tmp_path, RUN_DATE) / "synthesis-handoff.json"
    handoff.mkdir(parents=True)
    result: subprocess.CompletedProcess[str] = _run_wrapper(
        tmp_path, sources=[], run_date=RUN_DATE,
        extra_env={"MINERVA_SKIP_NEWS": "1"},
    )

    assert result.returncode == 1
    assert "synthesis-handoff.json" in result.stderr
    assert not (tmp_path / "coordinator/synthesis.log").exists()


def test_final_writer_admission_failure_is_the_script_exit_code(tmp_path: Path) -> None:
    """OpenClaw's exit status is authoritative; its output remains visible."""
    result: subprocess.CompletedProcess[str] = _run_wrapper(
        tmp_path, sources=[], run_date=RUN_DATE,
        extra_env={"MINERVA_SKIP_NEWS": "1", "TEST_ADMISSION_EXIT": "8"},
    )

    assert result.returncode == 8
    assert "synthetic admission error" in result.stdout
    assert len((tmp_path / "coordinator/synthesis.log").read_text().splitlines()) == 1
    assert (_phase_dir(tmp_path, RUN_DATE) / "synthesis-handoff.json").is_file()
