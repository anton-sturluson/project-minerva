"""Tests for research command."""

from pathlib import Path

from harness.commands.research import research_command
from harness.config import HarnessSettings


def test_research_command_calls_parallel_and_exports(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, parallel_api_key="parallel-test")
    export_path = tmp_path / "research.md"
    monkeypatch.setattr("harness.commands.research._call_parallel", lambda **kwargs: "Deep research result")

    result = research_command(query="market map", output_path=str(export_path), settings=settings)

    assert result.exit_code == 0
    assert "Deep research result" in result.stdout.decode("utf-8")
    assert export_path.exists()
