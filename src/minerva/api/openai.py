"""OpenAI API client implementation."""

from openai import AsyncOpenAI

from minerva.util.env import OPENAI_API_KEY

from .base import BaseLLMClient, Message, ChatCompletionResponse


class OpenAIClient(BaseLLMClient):
    """OpenAI API client for chat completions."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key. If None, reads from OPENAI_API_KEY env var.
            model: Model name. If None, uses default model.
        """
        super().__init__(api_key, model)
        self.client: AsyncOpenAI = AsyncOpenAI(api_key=self.api_key or OPENAI_API_KEY)

    def get_default_model(self) -> str:
        """Return the default OpenAI model."""
        return "gpt-4.1-mini"

    async def achat_completion(
        self,
        messages: list[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        response_schema: type | None = None,
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
        openai_messages: list[dict] = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        params: dict = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        params.update(kwargs)

        content: str
        parsed_object = None
        if response_schema:
            params["response_format"] = response_schema
            response = await self.client.beta.chat.completions.parse(**params)
            parsed_object = response.choices[0].message.parsed
            content = parsed_object.model_dump_json()
        else:
            response = await self.client.chat.completions.create(**params)
            content = response.choices[0].message.content

        usage: dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

        return ChatCompletionResponse(
            content=content,
            model=response.model,
            usage=usage,
            raw_response=response.model_dump(),
            parsed_object=parsed_object,
        )
