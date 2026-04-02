"""Tests for memory commands and storage."""

from pathlib import Path

from harness.commands.memory_cmd import forget_memory, list_memory, search_memory, store_memory
from harness.config import HarnessSettings


def test_memory_store_list_forget_search_cycle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = HarnessSettings(workspace_root=tmp_path)

    store_one = store_memory("Alpha thesis note", settings=settings)
    store_two = store_memory("Beta risk note", settings=settings)
    listed = list_memory(settings=settings)
    searched = search_memory("risk", settings=settings)
    forgot = forget_memory(1, settings=settings)
    listed_after = list_memory(settings=settings)

    assert store_one.exit_code == 0
    assert store_two.exit_code == 0
    assert "Alpha thesis note" in listed.stdout.decode("utf-8")
    assert "Beta risk note" in searched.stdout.decode("utf-8")
    assert forgot.exit_code == 0
    assert "Alpha thesis note" not in listed_after.stdout.decode("utf-8")
