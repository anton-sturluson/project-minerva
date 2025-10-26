"""Base class for LLM API clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass
class Message:
    """Represents a chat message."""

    role: str  # "system", "user", or "assistant"
    content: str


@dataclass
class ChatCompletionResponse:
    """Standardized response from chat completion."""

    content: str
    model: str
    usage: dict[str, int]
    raw_response: dict[str, Any] | None = None
    parsed_object: BaseModel | None = None


class BaseLLMClient(ABC):
    """Base class for LLM API clients (async-first)."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize the LLM client.

        Args:
            api_key: API key for the service. If None, will try to get from environment.
            model: Model name to use. If None, will use the default for the provider.
        """
        self.api_key: str | None = api_key
        self.model: str = model or self.get_default_model()

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model name for this provider."""
        pass

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        response_schema: type | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion.

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            response_schema: Optional Pydantic model for structured output.
            model: Optional model override. If None, uses self.model.
            **kwargs: Additional provider-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        pass

    async def chat(self, prompt: str, system: str | None = None, **kwargs) -> str:
        """
        Convenience method for simple chat completion.

        Args:
            prompt: User prompt.
            system: Optional system message.
            **kwargs: Additional parameters to pass to chat_completion.

        Returns:
            The generated text content.
        """
        messages: list[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        response: ChatCompletionResponse = await self.chat_completion(
            messages, **kwargs
        )
        return response.content

    async def close(self) -> None:
        """Close any open connections. Override in subclasses if needed."""
        pass
