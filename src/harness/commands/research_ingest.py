"""Run the platform's existing SEC holdings importer from Minerva."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from harness.commands.common import elapsed_ms
from harness.output import CommandResult

INGEST_13F_HELP: str = (
    "Fetch, parse and persist quarterly SEC 13F holdings for every stored investor.\n\n"
    "Uses the platform importer and existing DATABASE_URL and EDGAR_IDENTITY configuration.\n"
    "Collection includes investors without verified AUM; activity eligibility is unchanged.\n\n"
    "Example:\n"
    "  minerva sec ingest-13f --quarters 20 --through-quarter 2026-Q2"
)


def ingest_13f_command(*, quarters: int = 20, through_quarter: str | None = None) -> CommandResult:
    """Delegate an explicit inclusive quarter window without copying the SEC parser."""
    start: float = time.perf_counter()
    if quarters < 1:
        return CommandResult.from_text(
            stderr="--quarters must be a positive integer. Use --quarters 20 for five years.",
            exit_code=2,
        )
    if through_quarter is None or re.fullmatch(r"[0-9]{4}-Q[1-4]", through_quarter) is None:
        return CommandResult.from_text(
            stderr="Supply --through-quarter in YYYY-Q1 through YYYY-Q4 format, for example 2026-Q2.",
            exit_code=2,
        )
    project_root: Path = Path(__file__).resolve().parents[3]
    backend: Path = project_root / "investor-platform" / "backend"
    if not (backend / "pyproject.toml").is_file():
        return CommandResult.from_text(
            stderr="Research backend project is unavailable. Use a Minerva source checkout that includes investor-platform/backend.",
            exit_code=1,
        )
    command: list[str] = [
        "uv", "run", "--frozen", "--project", str(backend),
        "investor-research-sync", "--quarters", str(quarters),
        "--through-quarter", through_quarter, "--all-investors",
    ]
    try:
        result: subprocess.CompletedProcess[bytes] = subprocess.run(
            command, cwd=project_root, capture_output=True, check=False,
        )
    except OSError:
        return CommandResult.from_text(
            stderr="Could not start the research importer. Install uv and retry from a Minerva source checkout.",
            exit_code=1,
            duration_ms=elapsed_ms(start),
        )
    return CommandResult(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
        duration_ms=elapsed_ms(start),
    )
