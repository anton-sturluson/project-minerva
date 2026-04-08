"""Tests for delegated read commands."""

import asyncio
from pathlib import Path

from harness.delegate import delegate_read_many
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


def test_read_many_fans_out_delegate_calls_concurrently(monkeypatch) -> None:
    async def _exercise() -> tuple[list[str], int]:
        in_flight = 0
        max_in_flight = 0

        async def _fake_delegate_read(
            document_text: str,
            question: str,
            *,
            api_key: str | None = None,
            model: str = "",
        ) -> str:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return f"answer:{question}"

        monkeypatch.setattr("harness.delegate.delegate_read", _fake_delegate_read)
        answers = await delegate_read_many("doc text", ["Q1", "Q2", "Q3"], parallel=3, api_key="test-key")
        return answers, max_in_flight

    answers, max_in_flight = asyncio.run(_exercise())

    assert answers == ["answer:Q1", "answer:Q2", "answer:Q3"]
    assert max_in_flight == 3
