"""Entity extraction from text."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Coroutine

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.prompt.model import EntityExtractionResult, EntityResolution

if TYPE_CHECKING:
    from minerva.core.node import EntityNode


async def extract_entities(
    text: str, model: str = "gemini-2.5-flash"
) -> EntityExtractionResult:
    """
    Extract key entities from text.

    Args:
        text: Source text to extract entities from
        model: LLM model to use (default: gemini-2.5-flash)

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
    model: str = "gemini-2.5-flash",
) -> EntityResolution:
    """
    Resolve a new entity against existing entities.

    Args:
        context: Source text to extract entities from
        new_entity: The new entity to resolve against existing entities
        existing_entities: List of existing entity names
        model: LLM model to use (default: gemini-2.5-flash)

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


async def resolve_entities(
    context: str,
    new_entities: list[str],
    existing_entities: list[EntityNode],
    model: str = "gemini-2.5-flash",
) -> list[EntityResolution]:
    """
    Resolve entities against existing entities.

    Args:
        context: Source text to extract entities from
        new_entities: List of new entities to resolve
        existing_entities: List of existing entity nodes
        model: LLM model to use (default: gemini-2.5-flash)

    Returns:
        EntityResolutionResult with list of entity resolutions in the same order as new_entities
    """
    tasks: list[Coroutine] = [
        resolve_entity(context, entity, existing_entities, model)
        for entity in new_entities
    ]
    results: list[EntityResolution] = await asyncio.gather(*tasks)
    return results


async def summarize_entity(
    entity_name: str,
    relations: list[dict],
    model: str = "gemini-2.5-flash",
) -> str:
    """
    Generate summary for an entity based on its relationships.

    Args:
        entity_name: Name of the entity to summarize
        relations: List of relation dicts with keys: neighbor_name, relation_type, fact, direction
        model: LLM model to use

    Returns:
        Generated summary string
    """
    client: BaseLLMClient = get_client(model)

    if not relations:
        return f"{entity_name} (no connections available)"

    relation_facts: str = "\n".join(
        [
            f"- {entity_name} {r['relation_type']} {r['neighbor_name']}: {r['fact']}"
            if r["direction"] == "outgoing"
            else f"- {r['neighbor_name']} {r['relation_type']} {entity_name}: {r['fact']}"
            for r in relations
        ]
    )

    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a helpful assistant that creates concise entity summaries based on their relationships.

            Your summary should:
            1. Describe what the entity is or represents
            2. Highlight key relationships with other entities
            3. Be concise (1-2 sentences)
            4. Focus on the most important information

            Create a natural language summary that captures the essence of the entity.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <ENTITY>
            {entity_name}
            </ENTITY>

            <RELATIONSHIPS>
            {relation_facts}
            </RELATIONSHIPS>

            Please create a concise summary for this entity based on its relationships.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        model=model,
    )

    return response.content
