"""Tests for report scaffolding commands."""

from pathlib import Path

from harness.commands.report import create_report, list_reports, report_status
from harness.config import HarnessSettings


def test_report_new_list_status(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)

    created = create_report("alpha", settings=settings)
    listed = list_reports(settings=settings)
    status = report_status("alpha", settings=settings)
    status_text: str = status.stdout.decode("utf-8")

    assert created.exit_code == 0
    assert "alpha" in listed.stdout.decode("utf-8")
    assert "outline.md words=" in status_text
    assert "notes.md words=" in status_text
    assert "data/" in status_text
