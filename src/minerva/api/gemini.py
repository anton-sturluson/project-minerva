"""Gemini API client implementation."""

from google import genai
from google.genai import types

from minerva.util.env import GOOGLE_API_KEY

from .base import BaseLLMClient, Message, ChatCompletionResponse


class GeminiClient(BaseLLMClient):
    """Gemini API client for chat completions."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize Gemini client.

        Args:
            api_key: Google API key. If None, reads from GOOGLE_API_KEY env var.
            model: Model name. If None, uses default model.
        """
        super().__init__(api_key, model)
        self.client: genai.Client = genai.Client(api_key=self.api_key or GOOGLE_API_KEY)

    def get_default_model(self) -> str:
        """Return the default Gemini model."""
        return "gemini-2.5-flash"

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
        Generate a chat completion using Gemini.

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            response_schema: Optional Pydantic model for structured output.
            model: Optional model override. If None, uses self.model.
            **kwargs: Additional Gemini-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        model_to_use: str = model or self.model
        # Separate system instruction from chat messages
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=msg.content)])
                )
            elif msg.role == "assistant":
                contents.append(
                    types.Content(role="model", parts=[types.Part(text=msg.content)])
                )

        # Build generation config
        config_params: dict = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # Add structured output if schema provided
        if response_schema:
            config_params["response_mime_type"] = "application/json"
            config_params["response_schema"] = response_schema

        config_params.update(kwargs)

        if system_instruction:
            config_params["system_instruction"] = system_instruction

        config: types.GenerateContentConfig = types.GenerateContentConfig(
            **config_params
        )

        # Generate content using the async API
        response = await self.client.aio.models.generate_content(
            model=model_to_use, contents=contents, config=config
        )

        usage_metadata = response.usage_metadata
        usage: dict[str, int] = {
            "prompt_tokens": usage_metadata.prompt_token_count,
            "completion_tokens": usage_metadata.candidates_token_count,
            "total_tokens": usage_metadata.total_token_count,
        }

        parsed_object = None
        if response_schema:
            parsed_object = response_schema.model_validate_json(response.text)

        return ChatCompletionResponse(
            content=response.text,
            model=model_to_use,
            usage=usage,
            raw_response=response,
            parsed_object=parsed_object,
        )

    async def close(self) -> None:
        """Close the Gemini client and cleanup resources."""
        await self.client.aio.aclose()
