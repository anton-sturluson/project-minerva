"""Binary metrics that compare two text inputs."""

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.prompt.metric.model import MetricResult


async def similarity_metric(
    text1: str, text2: str, model: str = "gemini-2.5-flash-lite"
) -> MetricResult:
    """
    Detect if two texts contain highly similar substance worth compressing into one.

    Args:
        text1: First text to compare
        text2: Second text to compare
        model: LLM model to use

    Returns:
        MetricResult with decision (True if similar) and gradient explanation
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a similarity analyzer. Your task is to determine if two text statements contain highly similar substance that could be compressed into one statement.

            High similarity means:
            - The two statements convey essentially the same core information or message
            - They describe the same facts, events, or concepts with minor variations in wording
            - Combining them would not lose significant information
            - One statement might be more detailed but covers the same ground as the other
            - They are redundant or overlapping in substance

            Evaluate the two texts and provide:
            - A binary decision (True if they ARE highly similar and worth compressing, False if they are NOT)
            - A brief gradient explaining what makes them similar or different, and whether compression would lose important information
            """,
        ),
        Message(role="user", content=f"Text 1:\n{text1}\n\nText 2:\n{text2}"),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=MetricResult,
        model=model,
    )

    return response.parsed_object


async def contradiction_metric(
    text1: str, text2: str, model: str = "gemini-2.5-flash-lite"
) -> MetricResult:
    """
    Detect if two texts contain contradictory information.

    Args:
        text1: First text to compare
        text2: Second text to compare
        model: LLM model to use

    Returns:
        MetricResult with decision (True if contradictory) and gradient explanation
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a contradiction analyzer. Your task is to determine if two text statements contain information that contradicts each other.

            Contradictions occur when:
            - The statements make opposing or conflicting claims about the same subject
            - One statement denies or refutes what the other asserts
            - They present incompatible facts, figures, or conclusions
            - They describe mutually exclusive outcomes or conditions
            - Following both statements simultaneously would be logically impossible or inconsistent

            Evaluate the two texts and provide:
            - A binary decision (True if they DO contradict each other, False if they do NOT)
            - A brief gradient explaining what specific contradictions exist or why they are consistent
            """,
        ),
        Message(role="user", content=f"Text 1:\n{text1}\n\nText 2:\n{text2}"),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=MetricResult,
        model=model,
    )

    return response.parsed_object


async def subset_metric(
    text1: str, text2: str, model: str = "gemini-2.5-flash-lite"
) -> MetricResult:
    """
    Detect if first text is a strict subset of second text.

    Args:
        text1: First text (to check if it's a subset)
        text2: Second text (to check if it contains text1)
        model: LLM model to use

    Returns:
        MetricResult with decision (True if text1 is subset of text2) and gradient explanation
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a subset analyzer. Your task is to determine if one text is a strict subset of another text.

            Text 1 is a subset of Text 2 when:
            - All information in Text 1 is already contained in Text 2
            - Text 2 provides equal or more detail than Text 1
            - Text 1 adds no new facts, insights, or perspectives beyond what's in Text 2
            - Text 2 fully subsumes the content of Text 1

            Text 1 is NOT a subset if:
            - It contains any facts, details, or perspectives not in Text 2
            - It provides different framing or context that adds value
            - It has more specific details than Text 2
            - The texts cover different aspects of a topic

            Evaluate the two texts and provide:
            - A binary decision (True if Text 1 IS a subset of Text 2, False if it is NOT)
            - A brief gradient explaining what unique information Text 1 contains, or why it's fully covered by Text 2
            """,
        ),
        Message(role="user", content=f"Text 1:\n{text1}\n\nText 2:\n{text2}"),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=MetricResult,
        model=model,
    )

    return response.parsed_object
