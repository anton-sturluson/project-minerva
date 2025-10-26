"""Unary metrics that evaluate a single text input."""

from minerva.api.base import BaseLLMClient, ChatCompletionResponse, Message
from minerva.api.client import get_client
from minerva.prompt.metric.model import MetricResult


async def boilerplate_metric(
    text: str, model: str = "gemini-2.5-flash"
) -> MetricResult:
    """
    Detect if text is generic boilerplate lacking substantive information.

    Args:
        text: The text to evaluate
        model: LLM model to use (default: gemini-2.5-flash)

    Returns:
        MetricResult with decision (True if boilerplate) and gradient explanation
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a boilerplate detector. Your task is to determine if the given text is a boilerplate.

            Boilerplate text typically:
            - Contains generic, repetitive language that appears across many documents
            - Lacks specific, substantive information
            - Includes standard disclaimers, legal notices, or template language
            - Has no unique insights or actionable content

            Evaluate the text and provide:
            - A binary decision (True if it IS boilerplate, False if it is NOT)
            - A brief gradient explaining why you made this decision
            """,
        ),
        Message(role="user", content=text),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=MetricResult,
        model=model,
    )

    return response.parsed_object


async def forecast_metric(text: str, model: str = "gemini-2.5-flash") -> MetricResult:
    """
    Detect if text contains forecasts or forward-looking statements.

    Args:
        text: The text to evaluate
        model: LLM model to use (default: gemini-2.5-flash)

    Returns:
        MetricResult with decision (True if contains forecast) and gradient explanation
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a forecast detector. Your task is to determine if the given text contains a forecast or forward-looking statement.

            Forecasts typically:
            - Predict future events, outcomes, or conditions
            - Contain projections, estimates, or expectations about future performance
            - Include statements about anticipated trends, growth, or changes
            - Use forward-looking language (e.g., "will," "expect," "anticipate," "project," "plan," "believe")
            - Provide guidance or outlook for future periods

            Evaluate the text and provide:
            - A binary decision (True if it CONTAINS a forecast, False if it does NOT)
            - A brief gradient explaining what forecast elements are present or why it's not a forecast
            """,
        ),
        Message(role="user", content=text),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=MetricResult,
        model=model,
    )

    return response.parsed_object


async def definition_metric(text: str, model: str = "gemini-2.5-flash") -> MetricResult:
    """
    Detect if text defines a terminology or concept.

    Args:
        text: The text to evaluate
        model: LLM model to use (default: gemini-2.5-flash)

    Returns:
        MetricResult with decision (True if is definition) and gradient explanation
    """
    client: BaseLLMClient = get_client(model)
    messages: list[Message] = [
        Message(
            role="system",
            content="""
            You are a definition detector. Your task is to determine if the given text is a definition of a terminology or concept.

            Definitions typically:
            - Explain what a term, concept, or phrase means
            - Provide clarification of technical, industry-specific, or specialized terminology
            - Use phrases like "means," "refers to," "is defined as," "includes," "consists of"
            - Establish the scope or boundaries of a concept
            - May include examples or criteria that clarify meaning

            Evaluate the text and provide:
            - A binary decision (True if it IS a definition, False if it is NOT)
            - A brief gradient explaining what is being defined or why it's not a definition
            """,
        ),
        Message(role="user", content=text),
    ]

    response: ChatCompletionResponse = await client.chat_completion(
        messages=messages,
        response_schema=MetricResult,
        model=model,
    )

    return response.parsed_object
