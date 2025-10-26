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
    model: str = "gemini-2.5-flash",
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

    entity_summaries: str = "\n".join([f"- {e.name}: {e.summary}" for e in entities])

    relation_facts: str = "\n".join(
        [
            f"- {r['from_name']} {r['relation_type']} {r['to_name']}: {r['fact']}"
            for r in relations
        ]
    )

    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a helpful assistant that creates concise summaries of topics based on entities and their relationships.

            Your summary should:
            1. Identify the main theme or domain of the topic
            2. Highlight key entities and their roles
            3. Note important relationships and patterns
            4. Be concise (2-4 sentences)

            Create a short, descriptive name (2-4 words) that captures the essence of the topic.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <ENTITIES>
            {entity_summaries}
            </ENTITIES>

            <RELATIONSHIPS>
            {relation_facts if relation_facts else "No relationships available."}
            </RELATIONSHIPS>

            Please create a name and summary for this topic.
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
    child_topics: list[TopicNode], model: str = "gemini-2.5-flash"
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
            You are a helpful assistant that creates high-level summaries of topics based on their subtopic summaries.

            Your summary should:
            1. Synthesize the common themes across subtopics
            2. Identify the overarching domain or category
            3. Note diversity or breadth of coverage
            4. Be concise (1-3 sentences)

            Create a short, descriptive name (2-4 words) that captures the overarching theme.
            """,
        ),
        Message(
            role="user",
            content=f"""
            <SUBTOPICS>
            {child_summaries}
            </SUBTOPICS>

            Please create a name and higher-level summary that encompasses these subtopics.
            """,
        ),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=TopicSummary,
        model=model,
    )

    return response.parsed_object
