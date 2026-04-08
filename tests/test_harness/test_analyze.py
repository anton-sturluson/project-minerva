"""Tests for analysis commands."""

from pathlib import Path

from harness.commands.analyze import analyze_keywords, analyze_sentiment
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


def test_analyze_keywords_extracts_requested_groups(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    sample = (
        "Growth momentum and demand remain strong.\n"
        "Regulatory risk and litigation remain active.\n"
        "Competition is intense and pricing is under pressure."
    )
    (tmp_path / "sample.txt").write_text(sample, encoding="utf-8")

    result = analyze_keywords("sample.txt", "growth,risk,competition", settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "| growth | 3 |" in output
    assert "| risk | 3 |" in output
    assert "| competition | 2 |" in output
