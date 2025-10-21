"""Base class for LLM API clients."""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


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
    usage: Dict[str, int]
    raw_response: Optional[Dict[str, Any]] = None


class BaseLLMClient(ABC):
    """Base class for LLM API clients."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the LLM client.

        Args:
            api_key: API key for the service. If None, will try to get from environment.
            model: Model name to use. If None, will use the default for the provider.
        """
        self.api_key = api_key
        self.model = model or self.get_default_model()

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model name for this provider."""
        pass

    @abstractmethod
    async def achat_completion(
        self,
        messages: List[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        **kwargs
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion (async).

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        pass

    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        **kwargs
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion (sync).

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        return asyncio.run(self.achat_completion(messages, temperature, max_tokens, **kwargs))

    async def achat(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        """
        Convenience method for simple chat completion (async).

        Args:
            prompt: User prompt.
            system: Optional system message.
            **kwargs: Additional parameters to pass to achat_completion.

        Returns:
            The generated text content.
        """
        messages = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        response = await self.achat_completion(messages, **kwargs)
        return response.content

    def chat(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        """
        Convenience method for simple chat completion (sync).

        Args:
            prompt: User prompt.
            system: Optional system message.
            **kwargs: Additional parameters to pass to achat_completion.

        Returns:
            The generated text content.
        """
        return asyncio.run(self.achat(prompt, system, **kwargs))
