from pathlib import Path

from minerva.api.base import BaseLLMClient
from minerva.api.openai import OpenAIClient
from minerva.kb.kb import KnowledgeBase
from minerva.learning.curator import Curator
from minerva.learning.extractor import Extractor
from minerva.learning.model import KnowledgeItem, MetricConfig
from minerva.metric.base import Metric


class LearningPlatform:
    """Platform for learning and compressing knowledge from documents."""

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        mongo_host: str = "localhost",
        mongo_port: int = 27017,
        mongo_database: str = "minerva",
        chroma_path: str = "./.chroma_db",
        chroma_collection: str = "knowledge_base",
        required_metrics: list[tuple[Metric, MetricConfig]] | None = None,
        optional_metrics: list[Metric] | None = None,
        similarity_threshold: float = 0.5,
    ):
        self.llm: BaseLLMClient = llm_client or OpenAIClient()

        self.kb: KnowledgeBase = KnowledgeBase(
            mongo_host=mongo_host,
            mongo_port=mongo_port,
            mongo_database=mongo_database,
            chroma_path=chroma_path,
            chroma_collection=chroma_collection,
        )

        prompt_path: Path = Path(__file__).parent / "prompt" / "learning.txt"

        self.extractor: Extractor = Extractor(
            llm_client=self.llm,
            prompt_path=prompt_path,
            required_metrics=required_metrics,
            optional_metrics=optional_metrics,
        )

        self.curator: Curator = Curator(
            llm_client=self.llm,
            kb=self.kb,
            similarity_threshold=similarity_threshold,
        )

    async def alearn(
        self,
        text: str | list[str],
        ticker: str,
        parent_section_id: str | None = None,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[str]:
        self.kb.set_collection(ticker)

        items: list[KnowledgeItem] = await self.extractor.aextract(
            text, chunk_size, overlap
        )

        section_ids: list[str] = await self.curator.acurate(items, parent_section_id)

        return section_ids
