"""Base class for modular agent types."""

import asyncio
from pathlib import Path
from typing import Any

from minerva.api.base import BaseLLMClient, Message, ChatCompletionResponse


class Agent:
    """
    Base class for modular agents that wrap LLM calls with prompts.

    Designed to be composable and easy to use as tools in agentic workflows.
    """

    def __init__(
        self,
        client: BaseLLMClient,
        prompt_path: str | Path,
        prompt: str,
    ):
        self.client: BaseLLMClient = client
        self.prompt_path: Path = Path(prompt_path)
        self.prompt: str = prompt
        self._system_prompt: str | None = None

    def _load_system_prompt(self) -> str:
        if self._system_prompt is None:
            if not self.prompt_path.exists():
                raise FileNotFoundError(f"Prompt file not found: {self.prompt_path}")
            self._system_prompt = self.prompt_path.read_text(encoding="utf-8")
        return self._system_prompt

    async def acall(
        self,
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        response_schema: type | None = None,
        **kwargs: Any,
    ) -> ChatCompletionResponse:
        system_prompt: str = self._load_system_prompt()

        messages: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=self.prompt),
        ]

        return await self.client.achat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
            **kwargs,
        )

    def call(
        self,
        temperature: float = 1.0,
        max_tokens: int = 16_384,
        response_schema: type | None = None,
        **kwargs: Any,
    ) -> ChatCompletionResponse:
        return asyncio.run(
            self.acall(temperature, max_tokens, response_schema, **kwargs)
        )

    def as_tool(self, name: str, description: str) -> dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "callable": self.call,
            "async_callable": self.acall,
        }
