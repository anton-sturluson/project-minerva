"""Tests for classifier module (no real LLM calls)."""

from __future__ import annotations

import pytest

from jobwatch.classifier import ClassifierProvider, build_user_message, classify_postings
from jobwatch.models import JobClassification


class FakeClassifier(ClassifierProvider):
    """Deterministic classifier for testing."""

    def __init__(self, fixed_output: JobClassification | None = None):
        self._fixed: JobClassification = fixed_output or JobClassification(
            justification="Test classification.",
            department="ENG",
            role_type="ENG.GEN",
            seniority="MID",
            confidence=0.85,
        )
        self.call_count: int = 0

    @property
    def model_name(self) -> str:
        return "fake-model"

    def classify(
        self,
        title: str,
        department_raw: str | None,
        description: str | None,
    ) -> JobClassification:
        self.call_count += 1
        return self._fixed


class TestBuildUserMessage:
    def test_contains_title(self):
        msg: str = build_user_message("Software Engineer", "Eng", "Build things.")
        assert "Title: Software Engineer" in msg

    def test_contains_department(self):
        msg: str = build_user_message("PM", "Product", "Drive roadmap.")
        assert "Department (from ATS): Product" in msg

    def test_none_department_shows_na(self):
        msg: str = build_user_message("Engineer", None, "Build.")
        assert "Department (from ATS): N/A" in msg

    def test_none_description_shows_na(self):
        msg: str = build_user_message("Engineer", "Eng", None)
        assert "N/A" in msg

    def test_description_truncated(self):
        long_desc: str = "x" * 3000
        msg: str = build_user_message("Engineer", "Eng", long_desc)
        assert len(msg) < 3000


class TestClassifyPostings:
    def test_returns_correct_count(self):
        classifier: FakeClassifier = FakeClassifier()
        postings: list[tuple[str, str | None, str | None]] = [
            ("Engineer", "Eng", "Build."),
            ("PM", "Product", "Drive."),
            ("Designer", "Design", "Design."),
        ]
        results: list[JobClassification] = classify_postings(classifier, postings)
        assert len(results) == 3

    def test_calls_provider_per_posting(self):
        classifier: FakeClassifier = FakeClassifier()
        postings: list[tuple[str, str | None, str | None]] = [
            ("A", None, None),
            ("B", None, None),
        ]
        classify_postings(classifier, postings)
        assert classifier.call_count == 2

    def test_returns_fixed_classification(self):
        custom: JobClassification = JobClassification(
            justification="Research role.",
            department="RES",
            role_type="RES.GEN",
            seniority="SENIOR",
            confidence=0.92,
        )
        classifier: FakeClassifier = FakeClassifier(fixed_output=custom)
        results: list[JobClassification] = classify_postings(
            classifier, [("Scientist", "Research", "Study alignment.")]
        )
        assert results[0].department == "RES"
        assert results[0].seniority == "SENIOR"
        assert results[0].confidence == 0.92

    def test_empty_list(self):
        classifier: FakeClassifier = FakeClassifier()
        results: list[JobClassification] = classify_postings(classifier, [])
        assert results == []
        assert classifier.call_count == 0
