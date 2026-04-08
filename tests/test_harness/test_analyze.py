"""Tests for analysis commands."""

from harness.commands.analyze import analyze_ngrams_command, analyze_topics_command


def test_analyze_ngrams_extracts_unigrams_bigrams_and_trigrams() -> None:
    sample = b"supply chain risk supply chain resilience risk management\n"
    result = analyze_ngrams_command(stdin=sample, top=5, min_count=1)
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert "## Unigrams" in output
    assert "## Bigrams" in output
    assert "## Trigrams" in output
    assert "supply chain" in output


def test_analyze_topics_groups_co_occurring_terms() -> None:
    sample = (
        b"supply chain logistics components manufacturing\n\n"
        b"regulatory compliance antitrust privacy litigation\n\n"
        b"supply chain manufacturing logistics components\n"
    )
    result = analyze_topics_command(stdin=sample, clusters=2, min_count=1)
    output = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert 'Topic 1:' in output
    assert "supply chain" in output or "manufacturing" in output
