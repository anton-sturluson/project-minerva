"""Tests for harness.cli chain parsing and execution."""

from pathlib import Path

from harness.cli import execute_chain, parse_chain
from harness.config import HarnessSettings


def test_parse_chain_respects_quoted_operators() -> None:
    parsed = parse_chain('cat "alpha|beta.txt" | grep "x && y" ; ls')
    assert [item.text for item in parsed] == ['cat "alpha|beta.txt"', 'grep "x && y"', "ls"]
    assert [item.operator for item in parsed] == ["|", ";", None]


def test_execute_chain_supports_semicolon_and_and_or(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "sample.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = execute_chain("cat sample.txt && stat sample.txt", settings)
    assert result.exit_code == 0
    assert "estimated_tokens:" in result.stdout.decode("utf-8")

    fallback = execute_chain("cat missing.txt || stat sample.txt", settings)
    assert fallback.exit_code == 0
    assert "path: sample.txt" in fallback.stdout.decode("utf-8")


def test_execute_chain_pipes_stdout_between_stages(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "sample.txt").write_text("alpha\nbeta\nalpha\n", encoding="utf-8")
    result = execute_chain("cat sample.txt | grep alpha", settings)
    assert result.exit_code == 0
    assert result.stdout.decode("utf-8").strip() == "alpha\nalpha"


def test_integration_cat_pipe_grep(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "report.txt").write_text("gross margin\nrevenue\nmargin expansion\n", encoding="utf-8")
    result = execute_chain("cat report.txt | grep margin", settings)
    assert result.exit_code == 0
    assert result.stdout.decode("utf-8").splitlines() == ["gross margin", "margin expansion"]
