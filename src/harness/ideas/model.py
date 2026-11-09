"""Bounded, schema-validated model calls with explicit stage routing; traces stay on disk."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import openai
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from harness.ideas import store
from harness.worker_model import WORKER_MODEL, generate_fireworks, is_fireworks_model


@dataclass(frozen=True)
class StageModels:
    source: str
    extraction: str
    review: str


def resolve_models(override: str | None = None) -> StageModels:
    """An explicit --model overrides every stage; otherwise use stage settings."""
    return StageModels(
        source=override or os.environ.get("MINERVA_IDEAS_SOURCE_MODEL", WORKER_MODEL),
        extraction=override
        or os.environ.get("MINERVA_IDEAS_EXTRACTION_MODEL", WORKER_MODEL),
        review=override or os.environ.get("MINERVA_IDEAS_REVIEW_MODEL", "gpt-6.1-sol"),
    )


def check_model(model: str) -> None:
    """Require the selected provider's key, without trying another provider."""
    if is_fireworks_model(model):
        key: str = "FIREWORKS_API_KEY"
    elif model.startswith("gpt-"):
        key = "OPENAI_API_KEY"
    elif model.startswith("gemini-"):
        key = "GEMINI_API_KEY"
    else:
        raise ModelError(f"Unsupported model: {model}")
    if not os.environ.get(key):
        raise ModelError(f"{key} is required for model {model}")


class ModelError(RuntimeError):
    """Provider/configuration failures must not be counted as missing sources."""


def provider_schema(schema: type[BaseModel]) -> dict:
    value = schema.model_json_schema()

    def prune(node):
        if isinstance(node, dict):
            node.pop("additionalProperties", None)
            for child in node.values():
                prune(child)
        elif isinstance(node, list):
            for child in node:
                prune(child)

    prune(value)
    return value


def generate(
    prompt: str, schema: type[BaseModel], folder: Path, *, model: str
) -> BaseModel:
    """Validate one structured result from the selected provider, without fallback."""
    check_model(model)
    name: str = f"research/model/{uuid4()}"
    store.json_artifact(
        folder,
        name + ".request.json",
        {"model": model, "schema": schema.model_json_schema(), "prompt": prompt},
    )
    if is_fireworks_model(model):
        try:
            text: str = generate_fireworks(prompt, model=model, schema=schema)
        except (RuntimeError, ValueError) as exc:
            raise ModelError(f"Fireworks structured request failed ({type(exc).__name__})") from None
        store.json_artifact(folder, name + ".response.json", {"text": text})
        return schema.model_validate_json(text)
    if model.startswith("gpt-"):
        try:
            with openai.OpenAI(timeout=180, max_retries=0) as client:
                response = client.responses.parse(
                    model=model,
                    input=prompt,
                    text_format=schema,
                    reasoning={"effort": "high"},
                    max_output_tokens=10000,
                    store=False,
                )
        except openai.APIError as exc:
            raise ModelError(
                f"OpenAI request failed ({type(exc).__name__}, HTTP {getattr(exc, 'status_code', None)}); inspect provider access or quota"
            ) from None
        store.json_artifact(
            folder, name + ".response.json", response.model_dump(mode="json")
        )
        if response.status != "completed" or response.output_parsed is None:
            raise ModelError(
                "OpenAI returned an incomplete answer or refusal; inspect the saved response"
            )
        return response.output_parsed
    try:
        with genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        ) as client:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=provider_schema(schema),
                    max_output_tokens=5000,
                    temperature=0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
    except errors.APIError as exc:
        raise ModelError(
            f"Model request failed (HTTP {exc.code}); inspect provider access or quota"
        ) from None
    store.json_artifact(
        folder, name + ".response.json", response.model_dump(mode="json")
    )
    if not response.text:
        raise ValueError("Model returned no structured answer")
    return schema.model_validate_json(response.text)
