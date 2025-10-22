"""Claude API client implementation."""

import json
from anthropic import AsyncAnthropic

from minerva.util.env import ANTHROPIC_API_KEY

from .base import BaseLLMClient, Message, ChatCompletionResponse


class ClaudeClient(BaseLLMClient):
    """Claude API client for chat completions."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize Claude client.

        Args:
            api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
            model: Model name. If None, uses default model.
        """
        super().__init__(api_key, model)
        self.client: AsyncAnthropic = AsyncAnthropic(
            api_key=self.api_key or ANTHROPIC_API_KEY
        )

    def get_default_model(self) -> str:
        """Return the default Claude model."""
        return "claude-haiku-4-5"

    async def achat_completion(
        self,
        messages: list[Message],
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        response_schema: type | None = None,
        **kwargs,
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion using Claude.

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            response_schema: Optional Pydantic model for structured output.
            **kwargs: Additional Claude-specific parameters.

        Returns:
            ChatCompletionResponse with the generated content.
        """
        system_message: str | None = None
        conversation_messages: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                conversation_messages.append({"role": msg.role, "content": msg.content})

        params: dict = {
            "model": self.model,
            "messages": conversation_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_message:
            params["system"] = system_message

        # If structured output requested, use tool calling approach
        if response_schema:
            schema: dict = response_schema.model_json_schema()
            # Define a tool with the schema
            tools: list[dict] = [
                {
                    "name": "extract_data",
                    "description": "Extract and structure data according to the schema",
                    "input_schema": schema,
                }
            ]
            params["tools"] = tools
            params["tool_choice"] = {"type": "tool", "name": "extract_data"}

        params.update(kwargs)

        response = await self.client.messages.create(**params)

        usage: dict[str, int] = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        content: str = ""
        parsed_object = None

        for block in response.content:
            if block.type == "tool_use" and response_schema:
                content = json.dumps(block.input)
                parsed_object = response_schema.model_validate(block.input)
            elif block.type == "text":
                content += block.text

        return ChatCompletionResponse(
            content=content,
            model=response.model,
            usage=usage,
            raw_response=response.model_dump(),
            parsed_object=parsed_object,
        )
