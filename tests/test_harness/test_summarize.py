"""Behavioral tests for the top-level summarize command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.commands import extract
from harness.config import HarnessSettings

runner = CliRunner()


@pytest.fixture
def captured_generation(tmp_path: Path, monkeypatch) -> dict:
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "Model summary"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)
    monkeypatch.setattr(
        "harness.commands.extract.get_settings",
        lambda: HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key"),
    )
    return captured


def test_summarize_file_emits_only_summary_and_forwards_controls(
    tmp_path: Path, captured_generation: dict
) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("Revenue grew while margins contracted.", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "summarize",
            "-f",
            str(source),
            "--model",
            "gemini-3-pro",
            "--max-tokens",
            "512",
            "--thinking",
            "high",
        ],
    )

    assert result.exit_code == 0
    assert result.output == "Model summary\n"
    assert captured_generation["model"] == "gemini-3-pro"
    assert captured_generation["max_tokens"] == 512
    assert captured_generation["thinking"] == "high"
    assert "Revenue grew while margins contracted." in captured_generation["prompt"]


def test_summarize_reads_stdin_with_new_default(captured_generation: dict) -> None:
    result = runner.invoke(app, ["summarize"], input="Résumé source")

    assert result.exit_code == 0
    assert result.output == "Model summary\n"
    assert captured_generation["model"] == "gemini-3.6-flash"
    assert captured_generation["thinking"] == "minimal"
    assert "Résumé source" in captured_generation["prompt"]


def test_summarize_rejects_non_utf8_stdin_actionably(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    result = extract.summarize_command(stdin=b"\xff\xfe", settings=settings)

    assert result.exit_code == 1
    assert b"valid UTF-8" in result.stderr
    assert b"convert" in result.stderr


def test_bare_summarize_shows_help_without_calling_model() -> None:
    result = runner.invoke(app, ["summarize"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "--file" in result.output
    assert "What went wrong" not in result.output
