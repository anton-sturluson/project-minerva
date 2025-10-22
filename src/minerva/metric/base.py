"""Base classes for metrics."""

import asyncio
from pathlib import Path

from minerva.api.base import BaseLLMClient, ChatCompletionResponse
from minerva.metric.model import MetricResult
from minerva.primitive import Agent


class Metric:
    """Base class for metrics that evaluate text with binary decisions and gradients."""

    description: str = "Base metric class"

    def __init__(self, client: BaseLLMClient, prompt_path: str | Path):
        self.client: BaseLLMClient = client
        self.prompt_path: Path = Path(prompt_path)

    async def aevaluate(self, text: str) -> MetricResult:
        agent: Agent = Agent(
            client=self.client,
            prompt_path=self.prompt_path,
            prompt=text,
        )

        response: ChatCompletionResponse = await agent.acall(
            response_schema=MetricResult,
        )

        return response.parsed_object

    def evaluate(self, text: str) -> MetricResult:
        return asyncio.run(self.aevaluate(text))


class ComparisonMetric:
    """Base class for metrics that compare two texts."""

    description: str = "Base comparison metric class"

    def __init__(self, client: BaseLLMClient, prompt_path: str | Path):
        self.client: BaseLLMClient = client
        self.prompt_path: Path = Path(prompt_path)

    async def aevaluate(self, text1: str, text2: str) -> MetricResult:
        prompt: str = f"Text 1:\n{text1}\n\nText 2:\n{text2}"

        agent: Agent = Agent(
            client=self.client,
            prompt_path=self.prompt_path,
            prompt=prompt,
        )

        response: ChatCompletionResponse = await agent.acall(
            response_schema=MetricResult,
        )

        return response.parsed_object

    def evaluate(self, text1: str, text2: str) -> MetricResult:
        return asyncio.run(self.aevaluate(text1, text2))
