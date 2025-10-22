"""Knowledge curation and storage with deduplication."""

import asyncio
from pathlib import Path

from minerva.api.base import BaseLLMClient
from minerva.kb.kb import KnowledgeBase
from minerva.kb.model import QueryResult
from minerva.learning.model import KnowledgeItem
from minerva.metric import SimilarityMetric, SubsetMetric, MetricResult
from minerva.primitive import Agent


class Curator:
    """Curates knowledge items with intelligent deduplication and compression."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        kb: KnowledgeBase,
        similarity_threshold: float = 0.5,
    ):
        self.llm: BaseLLMClient = llm_client
        self.kb: KnowledgeBase = kb
        self.similarity_threshold: float = similarity_threshold

        self.similarity_metric: SimilarityMetric = SimilarityMetric(llm_client)
        self.subset_metric: SubsetMetric = SubsetMetric(llm_client)
        self.compress_prompt_path: Path = (
            Path(__file__).parent / "prompt" / "compress.txt"
        )

    async def _compress_knowledge(
        self, new_item: KnowledgeItem, existing_items: list[KnowledgeItem]
    ) -> KnowledgeItem:
        existing_text: str = "\n\n".join(
            [
                f"Header: {item.header}\nContent: {item.content}"
                for item in existing_items
            ]
        )

        user_prompt: str = f"""New Knowledge Item:
Header: {new_item.header}
Content: {new_item.content}

Existing Similar Knowledge Items:
{existing_text}

Merge these into a single comprehensive knowledge item."""

        agent: Agent = Agent(
            client=self.llm,
            prompt_path=self.compress_prompt_path,
            prompt=user_prompt,
        )

        response = await agent.acall(response_schema=type(new_item))
        return response.parsed_object

    async def _process_item(
        self, item: KnowledgeItem, parent_section_id: str | None = None
    ) -> str | None:
        similar_results: list[QueryResult] = self.kb.search(
            item.content, n_results=10
        )

        candidates = [
            result
            for result in similar_results
            if result.similarity >= self.similarity_threshold
        ]

        if not candidates:
            section_id: str = self.kb.add(
                header=item.header,
                content=item.content,
                parent_section=parent_section_id,
            )
            return section_id

        similarity_tasks = [
            self.similarity_metric.aevaluate(item.content, candidate.content)
            for candidate in candidates
        ]
        similarity_results: list[MetricResult] = await asyncio.gather(
            *similarity_tasks
        )

        similar_candidates = [
            candidate
            for candidate, result in zip(candidates, similarity_results)
            if result.decision
        ]

        if not similar_candidates:
            section_id: str = self.kb.add(
                header=item.header,
                content=item.content,
                parent_section=parent_section_id,
            )
            return section_id

        subset_tasks = [
            self.subset_metric.aevaluate(item.content, candidate.content)
            for candidate in similar_candidates
        ]
        subset_results: list[MetricResult] = await asyncio.gather(*subset_tasks)

        for result in subset_results:
            if result.decision:
                # TODO: In the future, append original text as evidence
                # For now, discard if new item is subset of any existing item
                return None

        existing_items = [
            KnowledgeItem(header=candidate.header, content=candidate.content)
            for candidate in similar_candidates
        ]

        compressed_item: KnowledgeItem = await self._compress_knowledge(
            item, existing_items
        )

        most_similar_id: str = similar_candidates[0].section_id

        self.kb.update(
            most_similar_id,
            header=compressed_item.header,
            content=compressed_item.content,
        )

        for candidate in similar_candidates[1:]:
            self.kb.delete(candidate.section_id)

        return most_similar_id

    async def acurate(
        self,
        items: list[KnowledgeItem],
        parent_section_id: str | None = None,
    ) -> list[str]:
        tasks = [self._process_item(item, parent_section_id) for item in items]
        results: list[str | None] = await asyncio.gather(*tasks)

        section_ids: list[str] = [sid for sid in results if sid is not None]
        return section_ids
