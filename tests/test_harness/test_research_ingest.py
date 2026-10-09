"""Check public ingestion discovery and input errors without network or database writes."""

from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from harness.cli import app, dispatch_command
from harness.config import HarnessSettings
from harness.output import CommandResult

runner: CliRunner = CliRunner()


def test_sec_help_lists_ingestion_and_its_explicit_window() -> None:
    """Expose the importer through the real Minerva command tree."""
    group: Result = runner.invoke(app, ["sec", "--help"])
    detail: Result = runner.invoke(app, ["sec", "ingest-13f", "--help"])
    assert group.exit_code == detail.exit_code == 0
    assert "ingest-13f" in group.stdout
    assert "--through-quarter" in detail.stdout
    assert "--quarters" in detail.stdout
    assert "20" in detail.stdout
    assert "persist" in detail.stdout
    assert "AUM" in detail.stdout


def test_run_path_exposes_the_same_import_workflow() -> None:
    """Discover ingestion through Minerva's actual shell-style run interface."""
    result: Result = runner.invoke(app, ["run", "sec ingest-13f --help"])
    assert result.exit_code == 0
    assert "Fetch, parse and persist" in result.stdout
    assert "--through-quarter 2026-Q2" in result.stdout
    assert "[exit:0" in result.stdout


@pytest.mark.parametrize("arguments", [
    [],
    ["--through-quarter", "2026-Q5"],
    ["--through-quarter", "2026-06-30"],
    ["--through-quarter", "2026-Q2", "--quarters", "0"],
])
def test_direct_ingestion_rejects_missing_or_invalid_window(arguments: list[str]) -> None:
    """Invalid user inputs fail before the importer can access external state."""
    result: Result = runner.invoke(app, ["sec", "ingest-13f", *arguments])
    assert result.exit_code != 0
    assert "--through-quarter" in result.output or "--quarters" in result.output


@pytest.mark.parametrize("arguments", [
    [],
    ["--through-quarter", "2026-Q5"],
    ["--through-quarter", "2026-Q2", "--quarters", "0"],
    ["--through-quarter", "2026-Q2", "--quarters", "many"],
    ["--quarters", "--through-quarter", "2026-Q2"],
    ["--through-quarter", "2026-Q2", "--manager", "example-manager"],
])
def test_dispatch_rejects_invalid_window_and_unsupported_options(arguments: list[str], tmp_path: Path) -> None:
    """Dispatch has the same positive-count, explicit-quarter boundary as the CLI."""
    settings: HarnessSettings = HarnessSettings(workspace_root=tmp_path)
    result: CommandResult = dispatch_command(["sec", "ingest-13f", *arguments], settings=settings)
    assert result.exit_code != 0
    assert (
        b"--quarters" in result.stderr
        or b"--through-quarter" in result.stderr
        or b"--name value" in result.stderr
    )


def test_run_ingestion_rejects_missing_quarter_count() -> None:
    """A missing count cannot silently narrow a requested import to one quarter."""
    result: Result = runner.invoke(app, ["run", "sec ingest-13f --quarters --through-quarter 2026-Q2"])
    assert "[exit:0" not in result.stdout
    assert "--quarters" in result.stdout or "--name value" in result.stdout
