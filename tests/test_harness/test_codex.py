"""Tests for Codex command helpers."""

from pathlib import Path

from harness.commands.codex import dispatch
from harness.config import HarnessSettings


def test_codex_dispatch_returns_spawn_command_string(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "repo"
    workspace_root = tmp_path / "workspace"
    project_dir.mkdir()
    settings = HarnessSettings(workspace_root=workspace_root)
    monkeypatch.chdir(project_dir)

    result = dispatch(["Implement", "a", "new", "command", "group"], settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert f"Project dir: {project_dir.resolve()}" in output
    assert f"Workspace root: {workspace_root.resolve()}" in output
    assert (
        f"codex --cwd {project_dir.resolve()} 'Implement a new command group'"
        in output
    )
