"""Relation extraction from text."""

from __future__ import annotations

from typing import TYPE_CHECKING

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.core.relation import RelatesToRelation
from minerva.prompt.model import FactExtractionResult, FactResolution

if TYPE_CHECKING:
    from minerva.core.node import EntityNode


async def extract_facts(
    context: str, entities: list[EntityNode], model: str = "gemini-2.5-flash-lite"
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


async def resolve_fact(
    context: str,
    new_relation: RelatesToRelation,
    existing_relations: list[RelatesToRelation],
    entity_map: dict[str, str],
    model: str = "gemini-2.5-flash-lite",
) -> FactResolution:
    """
    Resolve a new relation against existing relations.

    Args:
        context: Source text for context
        new_relation: The new relation to resolve against existing relations
        existing_relations: List of existing relation objects
        entity_map: Dictionary mapping entity IDs to names
        model: LLM model to use

    Returns:
        FactResolution with the resolution of the new relation
    """
    client: BaseLLMClient = get_client(model)
    from_name: str = entity_map.get(new_relation.from_id, new_relation.from_id)
    to_name: str = entity_map.get(new_relation.to_id, new_relation.to_id)

    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a helpful assistant that determines whether or not a NEW RELATION is a duplicate of existing relations.

            A relation is a duplicate ONLY if it contains strictly subset or duplicate information compared to an existing relation.
            Do NOT mark relations as duplicates if:
            - The new relation contains ANY information not present in the existing relation
            - The new relation adds details, temporal information, or context not in the existing relation
            - The relations are related but convey different aspects or information

            Only mark as duplicate if the new relation is completely redundant - it provides no additional information beyond what is already in the existing relation.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <CONTEXT>
            {context}
            </CONTEXT>

            <NEW_RELATION>
            From: {from_name} (ID={new_relation.from_id})
            To: {to_name} (ID={new_relation.to_id})
            Relation Type: {new_relation.relation_type}
            Fact: {new_relation.fact}
            </NEW_RELATION>

            <EXISTING_RELATIONS>
            {"\n".join([f"- ID={r.id}: From {entity_map.get(r.from_id, r.from_id)} (ID={r.from_id}) to {entity_map.get(r.to_id, r.to_id)} (ID={r.to_id}), Type={r.relation_type}, Fact={r.fact}" for r in existing_relations])}
            </EXISTING_RELATIONS>

            Please determine for the NEW RELATION whether it is a duplicate of an existing relation.
            Remember: Only mark as duplicate if the new relation contains strictly subset or duplicate information with no additional details.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=FactResolution,
        model=model,
    )

    return response.parsed_object
