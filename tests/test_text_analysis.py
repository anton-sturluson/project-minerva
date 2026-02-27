"""Tests for minerva.text_analysis module."""

from minerva.text_analysis import (
    KeywordGroup,
    count_keyword_group,
    count_keyword_groups,
    normalize_0_1,
    score_sentiment,
    split_into_chunks,
)


class TestCountKeywordGroup:
    """Tests for count_keyword_group."""

    def test_exact_count(self):
        """Counts exact keyword occurrences case-insensitively."""
        text: str = "Revenue growth was strong. Strong growth drove results."
        keywords: list[str] = ["growth", "strong"]
        result: int = count_keyword_group(text, keywords)
        assert result == 4

    def test_no_matches(self):
        """Returns zero when no keywords are found."""
        text: str = "The cat sat on the mat."
        keywords: list[str] = ["growth", "strong"]
        result: int = count_keyword_group(text, keywords)
        assert result == 0

    def test_case_insensitive(self):
        """Matches regardless of case."""
        text: str = "GROWTH Growth growth"
        keywords: list[str] = ["growth"]
        result: int = count_keyword_group(text, keywords)
        assert result == 3


class TestCountKeywordGroups:
    """Tests for count_keyword_groups."""

    def test_multi_group(self):
        """Counts across multiple keyword groups."""
        text: str = "Revenue growth was strong. Risk of decline is real."
        groups: list[KeywordGroup] = [
            KeywordGroup(name="positive", keywords=["growth", "strong"]),
            KeywordGroup(name="negative", keywords=["risk", "decline"]),
        ]
        result: dict[str, int] = count_keyword_groups(text, groups)
        assert result == {"positive": 2, "negative": 2}

    def test_empty_text(self):
        """Returns zeros for empty text."""
        groups: list[KeywordGroup] = [
            KeywordGroup(name="test", keywords=["alpha"]),
        ]
        result: dict[str, int] = count_keyword_groups("", groups)
        assert result == {"test": 0}


class TestSplitIntoChunks:
    """Tests for split_into_chunks."""

    def test_chunk_count(self):
        """Produces expected number of overlapping chunks."""
        words: list[str] = [f"word{i}" for i in range(1000)]
        text: str = " ".join(words)
        chunks: list[str] = split_into_chunks(text, chunk_size=500, overlap_ratio=0.5)
        assert len(chunks) >= 3

    def test_overlap_shares_words(self):
        """Adjacent chunks share overlapping words."""
        words: list[str] = [f"w{i}" for i in range(200)]
        text: str = " ".join(words)
        chunks: list[str] = split_into_chunks(text, chunk_size=100, overlap_ratio=0.5)
        assert len(chunks) >= 2
        first_words: set[str] = set(chunks[0].split())
        second_words: set[str] = set(chunks[1].split())
        overlap: set[str] = first_words & second_words
        assert len(overlap) > 0

    def test_small_text_skipped(self):
        """Text with fewer than 21 words produces no chunks."""
        text: str = " ".join(["hi"] * 15)
        chunks: list[str] = split_into_chunks(text, chunk_size=500)
        assert len(chunks) == 0


class TestScoreSentiment:
    """Tests for score_sentiment."""

    def test_confident_paragraphs(self):
        """Confident text yields positive net_score."""
        paragraphs: list[str] = [
            "We see strong growth and exciting opportunity ahead.",
            "Our innovative approach gives us a competitive advantage.",
        ]
        result = score_sentiment(paragraphs)
        assert result.confidence_count > 0
        assert result.uncertainty_count == 0
        assert result.net_score > 0
        assert result.paragraph_count == 2

    def test_uncertain_paragraphs(self):
        """Uncertain text yields negative net_score."""
        paragraphs: list[str] = [
            "There are significant risks and uncertainty in the market.",
            "Regulatory challenges and volatile conditions persist.",
        ]
        result = score_sentiment(paragraphs)
        assert result.uncertainty_count > 0
        assert result.net_score < 0

    def test_empty_paragraphs(self):
        """Empty input returns zero counts and zero score."""
        result = score_sentiment([])
        assert result.confidence_count == 0
        assert result.uncertainty_count == 0
        assert result.net_score == 0.0
        assert result.paragraph_count == 0


class TestNormalize01:
    """Tests for normalize_0_1."""

    def test_normal_range(self):
        """Normalizes typical values to [0, 1]."""
        values: list[float] = [10.0, 20.0, 30.0, 40.0, 50.0]
        result: list[float] = normalize_0_1(values)
        assert result[0] == 0.0
        assert result[-1] == 1.0
        assert result[2] == pytest.approx(0.5)

    def test_all_same_values(self):
        """Returns all zeros when every value is identical."""
        values: list[float] = [5.0, 5.0, 5.0]
        result: list[float] = normalize_0_1(values)
        assert result == [0.0, 0.0, 0.0]

    def test_single_value(self):
        """Single-element list normalizes to [0.0]."""
        result: list[float] = normalize_0_1([42.0])
        assert result == [0.0]

    def test_two_values(self):
        """Two distinct values map to 0 and 1."""
        result: list[float] = normalize_0_1([100.0, 200.0])
        assert result == [0.0, 1.0]


import pytest
