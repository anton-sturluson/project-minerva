"""Claude API client implementation."""

from typing import List, Optional
from anthropic import AsyncAnthropic

from minerva.util.env import ANTHROPIC_API_KEY

from .base import BaseLLMClient, Message, ChatCompletionResponse


class ClaudeClient(BaseLLMClient):
    """Claude API client for chat completions."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize Claude client.

        Args:
            api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
            model: Model name. If None, uses default model.
        """
        super().__init__(api_key, model)
        self.client = AsyncAnthropic(api_key=self.api_key or ANTHROPIC_API_KEY)

    def get_default_model(self) -> str:
        """Return the default Claude model."""
        return "claude-haiku-4-5"

    async def achat_completion(
        self,
        messages: List[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        **kwargs,
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion using Claude.

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional Claude-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        system_message = None
        conversation_messages = []

        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                conversation_messages.append({"role": msg.role, "content": msg.content})

        params = {
            "model": self.model,
            "messages": conversation_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_message:
            params["system"] = system_message
        params.update(kwargs)

        response = await self.client.messages.create(**params)

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        return ChatCompletionResponse(
            content=content,
            model=response.model,
            usage=usage,
            raw_response=response.model_dump(),
        )
