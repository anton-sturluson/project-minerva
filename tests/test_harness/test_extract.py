"""Tests for extract commands."""

from pathlib import Path

from harness.commands import extract
from harness.config import HarnessSettings


def test_extract_command_reads_file_and_calls_model(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("Revenue is $10M.", encoding="utf-8")
    monkeypatch.setattr("harness.commands.extract._generate_answer", lambda **kwargs: "Revenue: $10M")

    result = extract.extract_command(question="What is revenue?", file_path=str(file_path), settings=settings)

    assert result.exit_code == 0
    assert result.stdout.decode("utf-8") == "Revenue: $10M"


def test_extract_many_merges_inline_and_file_questions(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    questions_file = tmp_path / "questions.txt"
    questions_file.write_text("Q2\n", encoding="utf-8")
    monkeypatch.setattr(
        "harness.commands.extract._gather_answers",
        lambda **kwargs: __import__("asyncio").sleep(0, result=["A1", "A2"]),
    )

    result = extract.extract_many_command(
        questions=["Q1"],
        questions_file=str(questions_file),
        stdin=b"Document text",
        settings=settings,
    )

    assert result.exit_code == 0
    output = result.stdout.decode("utf-8")
    assert "## Q1" in output
    assert "## Q2" in output
