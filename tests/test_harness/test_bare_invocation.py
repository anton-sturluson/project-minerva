"""Tests for bare-invocation help behavior (doc 19).

Bare invocation (zero user args) → clean help, exit 0, no error.
Partial invocation (some args, missing required) → error + help, exit 1.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.commands.common import _is_bare_default

runner = CliRunner()


# ---------------------------------------------------------------------------
# Unit tests — _is_bare_default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        ([], True),
        ((), True),
        ("hello", False),
        (["a"], False),
        ("", False),  # Typer never sends "" for unprovided args
        (0, False),  # must not treat 0 as bare
        (False, False),  # must not treat False as bare
        (4, False),  # e.g. default concurrency value
        (True, False),
        ([None], False),  # list with one None element is NOT empty
    ],
)
def test_is_bare_default(value: object, expected: bool) -> None:
    assert _is_bare_default(value) is expected


# ---------------------------------------------------------------------------
# Bare invocation — clean help, exit 0, no error
# ---------------------------------------------------------------------------


def test_bare_extract_shows_help_without_error() -> None:
    result = runner.invoke(app, ["extract"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    assert "Usage:" in result.output
    assert "What went wrong" not in result.output


def test_bare_extract_files_shows_help_without_error() -> None:
    result = runner.invoke(app, ["extract-files"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    assert "Usage:" in result.output
    assert "What went wrong" not in result.output


def test_bare_fileinfo_shows_help_without_error() -> None:
    result = runner.invoke(app, ["fileinfo"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    assert "Usage:" in result.output
    assert "What went wrong" not in result.output


def test_bare_research_shows_help_without_error() -> None:
    result = runner.invoke(app, ["research"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    assert "Usage:" in result.output
    assert "What went wrong" not in result.output


def test_bare_run_shows_help_without_error() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    assert "Usage:" in result.output
    assert "What went wrong" not in result.output


# ---------------------------------------------------------------------------
# Partial invocation — error + help, exit 1 (regression guards)
# ---------------------------------------------------------------------------


def test_partial_extract_still_errors(tmp_path) -> None:
    """extract with --file but no question should still error."""
    src = tmp_path / "src.md"
    src.write_text("body", encoding="utf-8")
    result = runner.invoke(app, ["extract", "-f", str(src)])
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}.\n{result.output}"
    assert "What went wrong" in result.output


def test_partial_extract_files_still_errors(tmp_path) -> None:
    """extract-files with --files but no question/out should still error."""
    src = tmp_path / "src.md"
    src.write_text("body", encoding="utf-8")
    result = runner.invoke(app, ["extract-files", "-f", str(src)])
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}.\n{result.output}"
    assert "What went wrong" in result.output


def test_partial_research_still_errors() -> None:
    """research with --output but no query should still error."""
    result = runner.invoke(app, ["research", "--output", "foo.md"])
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}.\n{result.output}"
    assert "What went wrong" in result.output


# ---------------------------------------------------------------------------
# Dispatch path regression — run "extract" still errors
# ---------------------------------------------------------------------------


def test_run_dispatch_extract_still_errors() -> None:
    """'minerva run extract' goes through dispatch, should still show an error (not clean help).

    Note: `run` wraps dispatch results in an OutputEnvelope and always exits 0 at the
    process level.  The important assertion is that the dispatch path still produces an
    error message — i.e. it did NOT get the bare-invocation clean-help treatment.
    """
    result = runner.invoke(app, ["run", "extract"])
    assert "no extraction prompt" in result.output or "What went wrong" in result.output
