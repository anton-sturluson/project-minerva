"""Tests for delegated read commands."""

from pathlib import Path

from harness.commands.read import read_command_result, read_many_command_result
from harness.config import HarnessSettings


async def _fake_delegate_read(document_text: str, question: str, *, api_key: str | None = None, model: str = "") -> str:
    return f"answer:{question}:{len(document_text)}"


async def _fake_delegate_read_many(
    document_text: str,
    questions: list[str],
    *,
    parallel: int = 4,
    api_key: str | None = None,
    model: str = "",
) -> list[str]:
    return [f"answer:{question}:{parallel}" for question in questions]


def test_read_command_reads_file_and_uses_delegate(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "memo.txt").write_text("Hello delegated read", encoding="utf-8")
    monkeypatch.setattr("harness.commands.read.delegate_read", _fake_delegate_read)

    result = read_command_result("memo.txt", "What changed?", settings=settings)

    assert result.exit_code == 0
    assert "answer:What changed?" in result.stdout.decode("utf-8")


def test_read_many_command_combines_answers(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "memo.txt").write_text("Hello delegated read", encoding="utf-8")
    monkeypatch.setattr("harness.commands.read.delegate_read_many", _fake_delegate_read_many)

    result = read_many_command_result("memo.txt", ["What changed?", "Key risks?"], parallel=2, settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "## What changed?" in output
    assert "answer:Key risks?:2" in output
