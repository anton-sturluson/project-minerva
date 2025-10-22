from typing import Optional, List, Dict
from pathlib import Path

from minerva.api.base import BaseLLMClient, Message
from minerva.api.gemini import GeminiClient
from minerva.kb.mongo import MongoKB
from minerva.models import KnowledgeExtraction


class LearningPlatform:
    """Platform for learning and compressing knowledge from documents."""

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        mongo_host: str = "localhost",
        mongo_port: int = 27017,
        mongo_database: str = "minerva",
    ):
        """
        Initialize the learning platform.

        Args:
            llm_client: LLM client for knowledge extraction. Defaults to GeminiClient.
            mongo_host: MongoDB host.
            mongo_port: MongoDB port.
            mongo_database: MongoDB database name.
        """
        self.llm = llm_client or GeminiClient()
        self.mongo_host = mongo_host
        self.mongo_port = mongo_port
        self.mongo_database = mongo_database

        # Load learning prompt
        prompt_path = Path(__file__).parent / "prompt" / "learning.txt"
        with open(prompt_path, "r") as f:
            self.learning_prompt = f.read()

    def _get_kb_for_ticker(self, ticker: str) -> MongoKB:
        """
        Get MongoDB KB instance for a specific ticker.

        Args:
            ticker: Stock ticker symbol (used as collection name).

        Returns:
            MongoKB instance for the ticker.
        """
        kb = MongoKB(
            host=self.mongo_host,
            port=self.mongo_port,
            database=self.mongo_database,
        )
        # Override the collection to use ticker-specific collection
        kb.collection = kb.db[ticker.lower()]
        return kb

    async def alearn(
        self,
        text: str,
        ticker: str,
        metrics: Optional[Dict] = None,
        parent_section_id: Optional[str] = None,
    ) -> List[str]:
        """
        Learn from text and store knowledge in MongoDB (async).

        Args:
            text: Text content to learn from.
            ticker: Company ticker symbol.
            metrics: Optional metrics indicating relevance/importance.
            parent_section_id: Optional parent section ID for hierarchy.

        Returns:
            List of created section IDs.
        """
        # Prepare user prompt with text and metrics
        user_prompt = f"Text:\n{text}\n\n"
        if metrics:
            user_prompt += f"Metrics: {metrics}\n\n"
        user_prompt += "Extract valuable knowledge items from this text."

        # Use structured prediction to get knowledge items
        messages = [
            Message(role="system", content=self.learning_prompt),
            Message(role="user", content=user_prompt),
        ]

        response = await self.llm.achat_completion(
            messages=messages,
            response_schema=KnowledgeExtraction,
        )

        # Parse the structured response
        extraction = KnowledgeExtraction.model_validate_json(response.content)

        # Store each knowledge item in MongoDB
        kb = self._get_kb_for_ticker(ticker)
        section_ids = []

        for item in extraction.items:
            section_id = kb.add(
                header=item.header,
                content=item.content,
                parent_id=parent_section_id,
            )
            section_ids.append(section_id)

        kb.close()
        return section_ids
