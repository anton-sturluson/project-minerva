"""Tests for per-section filing download."""

from pathlib import Path
from unittest.mock import MagicMock

from harness.commands.sec import _download_filing_sections


def test_download_filing_sections_creates_per_section_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "10-K" / "2025-02-18"

    # Mock a filing object with structured item access.
    mock_filing = MagicMock()
    mock_obj = MagicMock()
    mock_obj.__getitem__ = lambda self, key: f"Content for {key}.\nLots of detail."
    mock_filing.obj.return_value = mock_obj

    result = _download_filing_sections(
        filing=mock_filing,
        form="10-K",
        out_dir=out_dir,
    )

    assert result["mode"] == "split"
    assert (out_dir / "01-business.md").exists()
    assert (out_dir / "02-risk-factors.md").exists()
    assert (out_dir / "_sections.md").exists()
    index_text = (out_dir / "_sections.md").read_text(encoding="utf-8")
    assert "01-business.md" in index_text


def test_download_filing_sections_falls_back_on_error(tmp_path: Path) -> None:
    out_dir = tmp_path / "10-K" / "2025-02-18"

    mock_filing = MagicMock()
    mock_filing.obj.side_effect = Exception("Structured access failed")
    mock_filing.markdown.return_value = "# Full filing\nBody text."

    result = _download_filing_sections(
        filing=mock_filing,
        form="10-K",
        out_dir=out_dir,
    )

    assert result["mode"] == "single"
    assert (out_dir / "filing.md").exists()
    assert (out_dir / "_sections.md").exists()
