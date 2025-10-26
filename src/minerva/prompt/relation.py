"""Relation extraction from text."""

from __future__ import annotations

from typing import TYPE_CHECKING

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.prompt.model import FactExtractionResult

if TYPE_CHECKING:
    from minerva.core.node import EntityNode


async def extract_facts(
    context: str, entities: list[EntityNode], model: str = "gemini-2.5-flash"
) -> FactExtractionResult:
    """
    Extract facts (relationships) between entities from a text.

    Args:
        context: Source text to extract facts from.
        entities: List of entities to find relationships between.
        model: LLM model to use.

    Returns:
        FactExtractionResult with a list of extracted facts.
    """
    client: BaseLLMClient = get_client(model)

    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a helpful assistant that extracts structured facts from a text.

            Guidelines:

            1. Extract facts only between the provided entities in the <ENTITIES> list.
            2. Each fact should represent a clear relationship between two DISTINCT entities.
            3. The `from_entity` and `to_entity` must be exact matches from the <ENTITIES> list.
            4. The `relation_type` should be a concise, all-caps description of the fact (e.g., CEO_OF, PARTNERS_WITH, ACQUIRED_BY).
            5. Provide a more detailed `fact` containing all relevant information from the context.
            6. Consider temporal aspects of relationships when relevant (e.g., "announced plans to" vs. "completed action").
            7. Do not extract facts for the same entity (e.g., Apple Inc. -> Apple Inc.).
            """,
        ),
        Message(
            role="user",
            content=f"""
            <CONTEXT>
            {context}
            </CONTEXT>

            <ENTITIES>
            {"\n".join([f"- {e.name} (ID={e.id})" for e in entities])}
            </ENTITIES>

            Please extract the facts from the context.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=FactExtractionResult,
        model=model,
    )

    return response.parsed_object
