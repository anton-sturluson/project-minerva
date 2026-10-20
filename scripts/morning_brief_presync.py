#!/usr/bin/env python3
"""Sync configured portfolio inputs before admitting the morning-brief agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, TextIO
from uuid import UUID
from zoneinfo import ZoneInfo

from harness.portfolio_state import PortfolioPaths, portfolio_paths


type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]

ROOT: Path = Path(__file__).resolve().parents[1]
RECEIPT_NAME: str = "portfolio-sync.receipt.json"
MAX_RECEIPT_AGE: timedelta = timedelta(hours=6)
SOURCE_NAMES: tuple[str, ...] = ("holdings", "transactions", "watchlist")


def artifact_paths(workspace: Path) -> dict[str, Path]:
    """Use the same portfolio layout as the sync command."""
    paths: PortfolioPaths = portfolio_paths(workspace)
    return {
        "holdings": paths.holdings,
        "transactions": paths.transactions,
        "watchlist": paths.watchlist,
        "universe": paths.universe,
    }


def artifact_hashes(workspace: Path) -> dict[str, JSONValue]:
    """Hash exact current bytes, not re-serialized portfolio values."""
    name: str
    path: Path
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in artifact_paths(workspace).items()
    }


def validate_receipt(workspace: Path, phase_dir: Path, as_of: date) -> None:
    """Reject missing, expired, malformed, or changed portfolio evidence."""
    receipt_path: Path = phase_dir / RECEIPT_NAME
    payload: JSONValue = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1:
        raise ValueError("unsupported portfolio receipt version")
    if payload.get("as_of") != as_of.isoformat():
        raise ValueError("portfolio receipt date does not match requested date")
    completed_at: JSONValue = payload.get("completed_at")
    if not isinstance(completed_at, str):
        raise ValueError("portfolio receipt has no completion time")
    completed: datetime = datetime.fromisoformat(completed_at)
    if completed.tzinfo is None or completed.utcoffset() != timedelta(0):
        raise ValueError("portfolio receipt completion time must be UTC")
    age: timedelta = datetime.now(timezone.utc) - completed
    if age < timedelta(0) or age > MAX_RECEIPT_AGE:
        raise ValueError("portfolio receipt is stale or has a future completion time (limit: 6h)")
    if payload.get("portfolio") != "Main":
        raise ValueError("portfolio receipt must describe Main-only state")
    if payload.get("artifacts") != artifact_hashes(workspace):
        raise ValueError("portfolio artifacts do not match receipt hashes; run scheduled pre-sync again")
    universe_override: str | None = os.environ.get("MINERVA_PORTFOLIO_UNIVERSE")
    if universe_override and Path(universe_override).resolve() != portfolio_paths(workspace).universe:
        raise ValueError("MINERVA_PORTFOLIO_UNIVERSE must use the receipted current universe")


def write_json(path: Path, payload: dict[str, JSONValue]) -> None:
    """Write a complete JSON artifact with an atomic replacement."""
    temporary: Path = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_status(phase_dir: Path, phase: str, exit_status: int) -> None:
    """Preserve the existing pipeline's phase status format."""
    write_json(
        phase_dir / f"{phase}.status.json",
        {
            "exit_status": exit_status,
            "phase": phase,
            "status": "ok" if exit_status == 0 else "failed",
            "stdout": str(phase_dir / f"{phase}.json"),
            "stderr": str(phase_dir / f"{phase}.stderr.log"),
        },
    )


def diagnostic_tail(path: Path) -> str:
    """Read at most 8 KiB and return at most twenty diagnostic lines."""
    stream: BinaryIO
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - 8192))
        return "\n".join(stream.read().decode("utf-8", errors="replace").splitlines()[-20:]).strip()


def diagnostics(phase_dir: Path, phase: str) -> str:
    """Prefer stderr, but surface stdout-only CLI failures too."""
    path: Path
    tail: str
    for path in (phase_dir / f"{phase}.stderr.log", phase_dir / f"{phase}.json"):
        tail = diagnostic_tail(path)
        if tail:
            return f"diagnostics: {path}\n{tail}"
    return f"diagnostics: {phase_dir / (phase + '.status.json')} (no command output)"


def run_phase(command: list[str], phase_dir: Path, phase: str) -> None:
    """Run one command without a shell and retain its output separately."""
    exit_status: int
    stdout: TextIO
    stderr: TextIO
    with (phase_dir / f"{phase}.json").open("w", encoding="utf-8") as stdout, (
        phase_dir / f"{phase}.stderr.log"
    ).open("w", encoding="utf-8") as stderr:
        try:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                command, cwd=ROOT, stdout=stdout, stderr=stderr, text=True, check=False,
            )
            exit_status = result.returncode
        except OSError as exc:
            stderr.write(str(exc) + "\n")
            exit_status = 1
    write_status(phase_dir, phase, exit_status)
    if exit_status != 0:
        raise RuntimeError(f"{phase} failed with status {exit_status}; {diagnostics(phase_dir, phase)}")


def sync(workspace: Path, phase_dir: Path, as_of: date) -> None:
    """Invalidate old evidence, require live inputs, and receipt a successful sync."""
    receipt_path: Path = phase_dir / RECEIPT_NAME
    receipt_path.unlink(missing_ok=True)
    name: str
    sources: dict[str, str] = {
        name: os.environ.get(f"MINERVA_PORTFOLIO_{name.upper()}_SOURCE", "").strip()
        for name in SOURCE_NAMES
    }
    for name in ("holdings", "transactions"):
        if not sources[name]:
            error: str = f"MINERVA_PORTFOLIO_{name.upper()}_SOURCE must be nonempty; cached inputs are not allowed"
            (phase_dir / "portfolio-sync.json").write_text("", encoding="utf-8")
            (phase_dir / "portfolio-sync.stderr.log").write_text(error + "\n", encoding="utf-8")
            write_status(phase_dir, "portfolio-sync", 1)
            raise ValueError(error)
    command: list[str] = ["uv", "run", "--project", str(ROOT), "minerva", "portfolio", "sync", "--date", as_of.isoformat()]
    source: str
    for name, source in sources.items():
        if source:
            command.extend([f"--{name}-source", source])
    run_phase(command, phase_dir, "portfolio-sync")
    source_metadata: dict[str, JSONValue] = {
        name: {"kind": "configured", "sha256": hashlib.sha256(source.encode()).hexdigest()}
        if source else {"kind": "local-watchlist"}
        for name, source in sources.items()
    }
    write_json(
        receipt_path,
        {
            "version": 1,
            "portfolio": "Main",
            "as_of": as_of.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifact_hashes(workspace),
            "sources": source_metadata,
        },
    )
    try:
        validate_receipt(workspace, phase_dir, as_of)
    except (OSError, ValueError):
        receipt_path.unlink(missing_ok=True)
        raise


def kickoff(phase_dir: Path, job_id: UUID) -> None:
    """Request admission once; admission is not evidence of child completion."""
    phase: str = "portfolio-handoff"
    run_phase(["openclaw", "automations", "run", str(job_id), "--json"], phase_dir, phase)
    payload: JSONValue
    try:
        payload = json.loads((phase_dir / f"{phase}.json").read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or payload.get("enqueued") is not True
            or not isinstance(payload.get("runId"), str)
            or not payload["runId"]
            or payload.get("ran") is False
            or "reason" in payload
            or "error" in payload
        ):
            raise ValueError("automation did not confirm admission")
    except ValueError as exc:
        write_status(phase_dir, phase, 1)
        raise RuntimeError(f"{exc}; {diagnostics(phase_dir, phase)}") from exc


def main() -> int:
    """Run pre-sync or validate the explicit consume-only pipeline boundary."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(ZoneInfo("America/New_York")).date())
    mode: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--handoff-job", type=UUID, help="Disabled agent-only automation UUID")
    mode.add_argument("--sync-only", action="store_true", help="Sync and receipt without starting an agent")
    mode.add_argument("--validate-only", action="store_true", help="Validate existing receipt without syncing")
    args: argparse.Namespace = parser.parse_args()
    workspace: Path = Path(os.environ.get("MINERVA_WORKSPACE_ROOT", str(ROOT / "hard-disk"))).resolve()
    os.environ["MINERVA_WORKSPACE_ROOT"] = str(workspace)
    os.environ["UV_PROJECT_ENVIRONMENT"] = str(ROOT / ".venv")
    report_dir: Path = Path(os.environ.get("MINERVA_REPORT_DIR", str(workspace / "reports" / "03-daily-news" / args.date.isoformat())))
    phase_dir: Path = Path(os.environ.get("MINERVA_NEWS_ARTIFACT_DIR", str(report_dir / "data" / "structured" / "news-pipeline")))
    try:
        if args.validate_only:
            validate_receipt(workspace, phase_dir, args.date)
            return 0
        phase_dir.mkdir(parents=True, exist_ok=True)
        sync(workspace, phase_dir, args.date)
        if args.handoff_job:
            kickoff(phase_dir, args.handoff_job)
        print("NO_REPLY")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error[portfolio-presync]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
