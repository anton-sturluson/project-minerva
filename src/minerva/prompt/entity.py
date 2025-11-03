"""Entity extraction from text."""

from __future__ import annotations

from typing import TYPE_CHECKING

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.prompt.model import EntityExtractionResult, EntityResolution

if TYPE_CHECKING:
    from minerva.core.node import EntityNode


async def extract_entities(
    text: str, model: str = "gemini-2.5-flash-lite"
) -> EntityExtractionResult:
    """
    Extract key entities from text.

    Args:
        text: Source text to extract entities from
        model: LLM model to use

    Returns:
        EntityExtractionResult with list of entities
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            Extract key entities from the provided text. An entity is a person, organization,
            concept, product, or important object mentioned in the text.

            For each entity, provide:
            - name: The entity name (short, clear identifier)

            Focus on substantive entities that represent important concepts or objects.
            Avoid extracting generic terms or overly broad concepts.
            """,
        ),
        Message(role="user", content=text),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=EntityExtractionResult,
        model=model,
    )

    return response.parsed_object


async def resolve_entity(
    context: str,
    new_entity: str,
    existing_entities: list[EntityNode],
    model: str = "gemini-2.5-flash-lite",
) -> EntityResolution:
    """
    Resolve a new entity against existing entities.

    Args:
        context: Source text to extract entities from
        new_entity: The new entity to resolve against existing entities
        existing_entities: List of existing entity names
        model: LLM model to use

    Returns:
        EntityResolution with the resolution of the new entity
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a helpful assistant that determines whether or not a NEW ENTITY is a duplicate of existing entities.

            An entity is a duplicate if it refers to the same real-world object or concept.
            Do NOT mark entities as duplicates if:
            - They are related but distinct.
            - They have similar names or purposes but refer to separate instances or concepts.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <CONTEXT>
            {context}
            </CONTEXT>

            <NEW_ENTITY>
            {new_entity}
            </NEW_ENTITY>

            <EXISTING_ENTITIES>
            {"\n".join([f"- {e.name} (ID={e.id})" for e in existing_entities])}
            </EXISTING_ENTITIES>

            Please determine for the NEW ENTITY whether it is a duplicate of an existing entity.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=EntityResolution,
        model=model,
    )

    return response.parsed_object
