"""Tests for workspace-scoped filesystem commands."""

from pathlib import Path

from harness.commands.fs import cat_file, list_files, resolve_workspace_path, stat_path, write_file
from harness.config import HarnessSettings


def test_resolve_workspace_path_rejects_escape(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    try:
        resolve_workspace_path("../outside.txt", settings)
    except ValueError as exc:
        assert "Path escapes the workspace root" in str(exc)
    else:
        raise AssertionError("Expected workspace escape to be rejected.")


def test_write_and_cat_file_round_trip(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    write_result = write_file("notes/test.txt", "alpha", settings)
    cat_result = cat_file("notes/test.txt", settings)
    assert write_result.exit_code == 0
    assert cat_result.stdout.decode("utf-8") == "alpha"


def test_cat_rejects_binary_files(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    binary_path = tmp_path / "blob.bin"
    binary_path.write_bytes(b"\x00\x01\x02")
    result = cat_file("blob.bin", settings)
    assert result.exit_code == 1
    assert "Binary file detected" in result.stderr.decode("utf-8")


def test_ls_defaults_to_workspace_root(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "alpha.txt").write_text("a", encoding="utf-8")
    (tmp_path / "beta").mkdir()
    result = list_files(settings=settings)
    output: str = result.stdout.decode("utf-8")
    assert "alpha.txt" in output
    assert "beta/" in output


def test_stat_reports_large_file_guidance(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    content: str = "\n".join(f"line {index}" for index in range(250))
    (tmp_path / "large.txt").write_text(content, encoding="utf-8")
    result = stat_path("large.txt", settings)
    output: str = result.stdout.decode("utf-8")
    assert "estimated_tokens:" in output
    assert "recommendation: Large file." in output
