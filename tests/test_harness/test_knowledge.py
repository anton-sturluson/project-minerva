"""Tests for knowledge commands."""

from pathlib import Path

from harness.commands.knowledge import read_knowledge, search_knowledge, write_knowledge
from harness.config import HarnessSettings


def test_knowledge_search_read_write(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)

    write_result = write_knowledge("00-saas/metrics.md", "# Benchmarks\nGross margin benchmark", settings=settings)
    search_result = search_knowledge("gross margin", settings=settings)
    read_result = read_knowledge("00-saas/metrics.md", settings=settings)

    assert write_result.exit_code == 0
    assert "metrics.md" in search_result.stdout.decode("utf-8")
    assert "Gross margin benchmark" in read_result.stdout.decode("utf-8")
