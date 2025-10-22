"""Knowledge extraction from text."""

import asyncio
from pathlib import Path

from minerva.api.base import BaseLLMClient
from minerva.kb.utils import chunk_text
from minerva.learning.model import KnowledgeExtraction, KnowledgeItem, MetricConfig
from minerva.metric import MetricResult
from minerva.metric.base import Metric
from minerva.primitive import Agent


class Extractor:
    """Extracts knowledge items from text using LLM and metrics."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_path: str | Path,
        required_metrics: list[tuple[Metric, MetricConfig]] | None = None,
        optional_metrics: list[Metric] | None = None,
    ):
        self.llm: BaseLLMClient = llm_client
        self.prompt_path: Path = Path(prompt_path)
        self.required_metrics: list[tuple[Metric, MetricConfig]] = required_metrics or []
        self.optional_metrics: list[Metric] = optional_metrics or []

    async def _process_chunk(self, chunk: str) -> list[KnowledgeItem]:
        before_metrics = [
            (metric, config)
            for metric, config in self.required_metrics
            if config.timing.value == "before"
        ]

        metric_tasks = [metric.aevaluate(chunk) for metric, config in before_metrics]
        metric_results: list[MetricResult] = await asyncio.gather(*metric_tasks)

        metric_feedback: str = ""
        for (metric, config), result in zip(before_metrics, metric_results):
            should_halt = (result.decision and config.on_true.value == "halt") or (
                not result.decision and config.on_false.value == "halt"
            )
            if should_halt:
                return []

            if result.decision:
                metric_feedback += f"{config.metric_name}: {result.gradient}\n"

        user_prompt: str = f"Text:\n{chunk}\n\n"
        if metric_feedback:
            user_prompt += f"Metric Evaluation:\n{metric_feedback}\n"
        user_prompt += "Extract valuable knowledge items from this text."

        agent: Agent = Agent(
            client=self.llm,
            prompt_path=self.prompt_path,
            prompt=user_prompt,
        )

        response = await agent.acall(response_schema=KnowledgeExtraction)
        extraction: KnowledgeExtraction = response.parsed_object

        return extraction.items

    async def aextract(
        self,
        text: str | list[str],
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[KnowledgeItem]:
        chunks: list[str] = []
        if isinstance(text, str):
            chunks = chunk_text(text, chunk_size, overlap)
        else:
            for t in text:
                chunks.extend(chunk_text(t, chunk_size, overlap))

        tasks = [self._process_chunk(chunk) for chunk in chunks]
        results: list[list[KnowledgeItem]] = await asyncio.gather(*tasks)

        all_items: list[KnowledgeItem] = []
        for items in results:
            all_items.extend(items)

        return all_items
