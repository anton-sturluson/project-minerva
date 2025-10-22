"""OpenAI API client implementation."""

from typing import List, Optional
from openai import AsyncOpenAI

from minerva.util.env import OPENAI_API_KEY

from .base import BaseLLMClient, Message, ChatCompletionResponse


class OpenAIClient(BaseLLMClient):
    """OpenAI API client for chat completions."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key. If None, reads from OPENAI_API_KEY env var.
            model: Model name. If None, uses default model.
        """
        super().__init__(api_key, model)
        self.client = AsyncOpenAI(api_key=self.api_key or OPENAI_API_KEY)

    def get_default_model(self) -> str:
        """Return the default OpenAI model."""
        return "gpt-5-mini"

    async def achat_completion(
        self,
        messages: List[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        response_schema: Optional[type] = None,
        **kwargs,
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion using OpenAI.

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            response_schema: Optional Pydantic model for structured output.
            **kwargs: Additional OpenAI-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        openai_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        params = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        # Add structured output if schema provided
        if response_schema:
            params["response_format"] = response_schema

        params.update(kwargs)

        response = await self.client.chat.completions.create(**params)

        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

        return ChatCompletionResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage=usage,
            raw_response=response.model_dump(),
        )
