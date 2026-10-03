"""One bounded, schema-constrained low-cost model call; traces stay on disk."""

import os
from pathlib import Path
from uuid import uuid4

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from harness.ideas import store

DEFAULT_MODEL = "gemini-2.5-flash-lite"


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
    prompt: str, schema: type[BaseModel], folder: Path, *, model: str = DEFAULT_MODEL
) -> BaseModel:
    if not os.environ.get("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY is required for original-source research")
    name = f"research/model/{uuid4()}"
    store.json_artifact(
        folder,
        name + ".request.json",
        {"model": model, "schema": schema.model_json_schema(), "prompt": prompt},
    )
    try:
        with genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=60000),
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
