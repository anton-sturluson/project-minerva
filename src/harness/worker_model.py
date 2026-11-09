"""Direct Fireworks worker routing; no model fallback or retention guarantees."""

from __future__ import annotations

import json
import os
from typing import Literal, cast

import openai
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel

WORKER_MODEL: str = "accounts/fireworks/models/glm-5p3-flash"
WORKER_OPENCLAW_MODEL: str = f"fireworks/{WORKER_MODEL}"
WORKER_REASONING: str = "high"
FIREWORKS_BASE_URL: str = "https://api.fireworks.ai/inference/v1"


def is_fireworks_model(model: str) -> bool:
    """Recognize direct and OpenClaw-qualified Fireworks IDs without aliases."""
    return model.removeprefix("fireworks/").startswith("accounts/fireworks/")


def fireworks_model_id(model: str) -> str:
    """Remove only the provider prefix; never map FLASH to non-fast GLM."""
    if not is_fireworks_model(model):
        raise ValueError("Expected an accounts/fireworks model ID")
    return model.removeprefix("fireworks/")


def fireworks_client(
    *, api_key: str | None = None, timeout: float = 180
) -> openai.OpenAI:
    """Use only the Fireworks endpoint and host-owned environment authentication."""
    key: str | None = api_key or os.environ.get("FIREWORKS_API_KEY")
    if not key:
        raise ValueError("FIREWORKS_API_KEY is required")
    return openai.OpenAI(
        api_key=key, base_url=FIREWORKS_BASE_URL, timeout=timeout, max_retries=0
    )


def fireworks_text(response: ChatCompletion) -> str:
    """Reject truncation, refusals and empty content instead of switching models."""
    if not response.choices:
        raise ValueError("Fireworks returned no choices")
    choice: Choice = response.choices[0]
    if choice.finish_reason != "stop" or choice.message.refusal:
        raise ValueError("Fireworks returned an incomplete answer or refusal")
    text: str | None = choice.message.content
    if not text or not text.strip():
        raise ValueError("Fireworks returned an empty answer")
    return text.strip()


def generate_fireworks(
    prompt: str,
    *,
    model: str = WORKER_MODEL,
    api_key: str | None = None,
    max_tokens: int = 16384,
    reasoning_effort: str = WORKER_REASONING,
    schema: type[BaseModel] | None = None,
) -> str:
    """Request reasoning with text or prompt-specified JSON, validated locally."""
    if reasoning_effort not in {"low", "medium", "high"}:
        raise ValueError("Fireworks reasoning must be low|medium|high")
    model_id: str = fireworks_model_id(model)
    # Fireworks json_schema response_format disables reasoning output. Its documented
    # reasoning-compatible path puts the schema in the prompt and validates locally:
    # https://docs.fireworks.ai/structured-responses/structured-response-formatting
    if schema:
        prompt += (
            "\n\nReturn only a JSON object matching this schema (no markdown fences):\n"
            + json.dumps(schema.model_json_schema())
        )
    effort: Literal["low", "medium", "high"] = cast(Literal["low", "medium", "high"], reasoning_effort)
    try:
        with fireworks_client(api_key=api_key) as client:
            response: ChatCompletion = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                reasoning_effort=effort,
            )
    except openai.APIError as exc:
        raise RuntimeError(
            f"Fireworks request failed ({type(exc).__name__}, HTTP {getattr(exc, 'status_code', None)})"
        ) from None
    text: str = fireworks_text(response)
    if schema:
        try:
            schema.model_validate_json(text)
        except ValueError:
            raise ValueError("Fireworks returned invalid structured JSON") from None
    return text
