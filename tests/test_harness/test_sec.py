"""Tests for SEC command wrappers."""

from pathlib import Path

from harness.cli import dispatch_command
from harness.commands import sec
from harness.config import HarnessSettings


def test_sec_dispatch_requires_subcommand(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    result = dispatch_command(["sec"], settings=settings)
    assert result.exit_code == 1
    assert "Usage: sec <10k|13f|financials>" in result.stderr.decode("utf-8")


def test_sec_subcommands_validate_missing_args(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    ten_k = sec.dispatch(["10k"], settings)
    thirteen_f = sec.dispatch(["13f"], settings)
    financials = sec.dispatch(["financials"], settings)

    assert ten_k.exit_code == 1
    assert "Usage: sec 10k <ticker>" in ten_k.stderr.decode("utf-8")
    assert thirteen_f.exit_code == 1
    assert "Usage: sec 13f <cik>" in thirteen_f.stderr.decode("utf-8")
    assert financials.exit_code == 1
    assert "Usage: sec financials <ticker>" in financials.stderr.decode("utf-8")
