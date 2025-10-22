"""Metric implementations."""

from pathlib import Path

from minerva.api.base import BaseLLMClient
from minerva.metric.base import ComparisonMetric, Metric


class BoilerplateMetric(Metric):
    """Metric to detect if text is boilerplate."""

    description: str = "Detects if text is generic boilerplate lacking substantive information"

    def __init__(self, client: BaseLLMClient):
        prompt_path: Path = Path(__file__).parent / "prompt" / "boilerplate.txt"
        super().__init__(client, prompt_path)


class ForecastMetric(Metric):
    """Metric to detect if text contains a forecast."""

    description: str = "Detects if text contains forecasts or forward-looking statements"

    def __init__(self, client: BaseLLMClient):
        prompt_path: Path = Path(__file__).parent / "prompt" / "forecast.txt"
        super().__init__(client, prompt_path)


class DefinitionMetric(Metric):
    """Metric to detect if text is a definition."""

    description: str = "Detects if text defines a terminology or concept"

    def __init__(self, client: BaseLLMClient):
        prompt_path: Path = Path(__file__).parent / "prompt" / "definition.txt"
        super().__init__(client, prompt_path)


class SimilarityMetric(ComparisonMetric):
    """Metric to detect if two texts are highly similar."""

    description: str = "Detects if two texts contain highly similar substance worth compressing into one"

    def __init__(self, client: BaseLLMClient):
        prompt_path: Path = Path(__file__).parent / "prompt" / "similarity.txt"
        super().__init__(client, prompt_path)


class ContradictionMetric(ComparisonMetric):
    """Metric to detect if two texts contradict each other."""

    description: str = "Detects if two texts contain contradictory information"

    def __init__(self, client: BaseLLMClient):
        prompt_path: Path = Path(__file__).parent / "prompt" / "contradiction.txt"
        super().__init__(client, prompt_path)


class SubsetMetric(ComparisonMetric):
    """Metric to detect if first text is a subset of second text."""

    description: str = "Detects if first text is a strict subset of second text"

    def __init__(self, client: BaseLLMClient):
        prompt_path: Path = Path(__file__).parent / "prompt" / "subset.txt"
        super().__init__(client, prompt_path)
