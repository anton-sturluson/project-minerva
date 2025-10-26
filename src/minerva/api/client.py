"""Shared LLM clients."""

from minerva.api.base import BaseLLMClient
from minerva.api.claude import ClaudeClient
from minerva.api.gemini import GeminiClient
from minerva.api.openai import OpenAIClient

_gemini_client: GeminiClient = GeminiClient(model="gemini-2.5-flash")
_openai_client: OpenAIClient = OpenAIClient(model="gpt-4o-mini")
_claude_client: ClaudeClient = ClaudeClient(model="claude-sonnet-4")


def get_client(model: str = "gemini-2.5-flash") -> BaseLLMClient:
    """
    Get the appropriate LLM client for the specified model.

    Args:
        model: Model name (e.g., "gemini-2.5-flash", "gpt-4o-mini", "claude-sonnet-4")

    Returns:
        The appropriate client instance for the model
    """
    if model.startswith("gemini"):
        return _gemini_client
    elif model.startswith(("gpt", "o1", "o3", "o4")):
        return _openai_client
    elif model.startswith("claude"):
        return _claude_client
    raise ValueError(f"Invalid model: {model}")


async def close_all_clients() -> None:
    """Close all LLM client sessions."""
    await _gemini_client.close()
    await _openai_client.close()
    await _claude_client.close()
