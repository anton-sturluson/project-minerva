"""Tests for fileinfo command."""

from pathlib import Path

from harness.commands.fileinfo import inspect_path_command


def test_fileinfo_reports_text_file_metadata(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("# Notes\nhello world\n", encoding="utf-8")

    result = inspect_path_command(str(target))
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "format: text/markdown" in output
    assert "recommendation:" in output


def test_fileinfo_reports_directory_inventory(tmp_path: Path) -> None:
    folder = tmp_path / "AAPL"
    sub = folder / "10-K"
    sub.mkdir(parents=True)
    (sub / "2025-11-01.md").write_text("hello", encoding="utf-8")

    result = inspect_path_command(str(folder))
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "type: directory" in output
    assert "contents:" in output
