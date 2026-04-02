"""Tests for analysis commands."""

from pathlib import Path

from harness.commands.analyze import analyze_sentiment
from harness.config import HarnessSettings


def test_analyze_sentiment_scores_sample_text(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    sample = (
        "We see strong growth and momentum in demand.\n\n"
        "There is regulatory risk and uncertainty in the market."
    )
    (tmp_path / "sample.txt").write_text(sample, encoding="utf-8")

    result = analyze_sentiment("sample.txt", settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "paragraph_count: 2" in output
    assert "confidence_count: 4" in output
    assert "uncertainty_count: 3" in output
    assert "net_score: 0.143" in output
