"""Topic summary extraction from entities and relations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.prompt.model import TopicSummary

if TYPE_CHECKING:
    from minerva.core.node import EntityNode, TopicNode


async def summarize_leaf_topic(
    entities: list[EntityNode],
    relations: list[dict],
    model: str = "gemini-2.5-flash-lite",
) -> TopicSummary:
    """
    Generate summary for a leaf topic from its entities and relations.

    Args:
        entities: List of entities in the topic
        relations: List of relation dictionaries with keys: from_name, to_name, relation_type, fact
        model: LLM model to use

    Returns:
        TopicSummary with name and summary
    """
    if not entities:
        return TopicSummary(
            reasoning="No entities in topic",
            name="Empty Topic",
            summary="Empty topic with no entities.",
        )

    client: BaseLLMClient = get_client(model)

    entity_names: str = "\n".join([f"- {e.name}" for e in entities])

    relation_facts: str = "\n".join(
        [
            f"- [src:{r['from_name']} -> rel:{r['relation_type']} -> dst:{r['to_name']}]\n{r['fact']}"
            for r in relations
        ]
    )

    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are analyzing edge communities from hierarchical link clustering (HLC).

            You will be given:
            - Entity names (nodes) that participate in this edge community
            - Relationships (edges) with their types and facts

            Your task is to identify what connects these RELATIONSHIPS, not the entities themselves.
            Focus on:
            1. The pattern of how entities are connected (relationship types)
            2. The semantic content of the facts in the relationships
            3. The common theme or domain that these specific relationships represent

            Remember: This is an edge-centric community. Entities may belong to multiple topics,
            but these relationships cluster together because they share structural or semantic similarity.

            Create a concise name (2-5 words) and summary (1-3 sentences) that captures the essence
            of what these relationships have in common.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <ENTITY_NAMES>
            {entity_names}
            </ENTITY_NAMES>

            <RELATIONSHIPS>
            {relation_facts if relation_facts else "No relationships available."}
            </RELATIONSHIPS>

            Analyze the pattern and theme of these relationships to create a topic name and summary.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=TopicSummary,
        model=model,
    )

    return response.parsed_object


async def summarize_parent_topic(
    child_topics: list[TopicNode], model: str = "gemini-2.5-flash-lite"
) -> TopicSummary:
    """
    Generate summary for a parent topic from its child topics.

    Args:
        child_topics: List of child TopicNodes with their summaries
        model: LLM model to use

    Returns:
        TopicSummary with name and summary
    """
    if not child_topics:
        return TopicSummary(
            reasoning="No subtopics available",
            name="Empty Parent Topic",
            summary="Empty parent topic with no subtopics.",
        )

    client: BaseLLMClient = get_client(model)

    child_summaries: str = "\n".join([f"- {c.name}: {c.summary}" for c in child_topics])

    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are analyzing hierarchical edge communities from HLC (Hierarchical Link Clustering).

            You will be given child topics, where each child represents a cluster of similar relationships.
            Your task is to identify the higher-level pattern that connects these relationship clusters.

            Focus on:
            1. What semantic or structural similarities link these child relationship communities
            2. The broader domain or context that encompasses these relationship patterns
            3. How these relationship types relate to each other at a higher abstraction level

            Remember: You are analyzing patterns in RELATIONSHIPS (edges), not just entity groupings.
            The hierarchy represents merging of similar edge communities.

            Create a concise name (2-5 words) and summary (2-3 sentences) that captures the
            overarching relationship pattern or domain.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <CHILD_EDGE_COMMUNITIES>
            {child_summaries}
            </CHILD_EDGE_COMMUNITIES>

            Identify the higher-level relationship pattern that connects these edge communities.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=TopicSummary,
        model=model,
    )

    return response.parsed_object
