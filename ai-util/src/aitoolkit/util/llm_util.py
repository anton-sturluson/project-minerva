"""Utility functions for handling LLM outputs."""
import re
import json

from pydantic import BaseModel

import aitoolkit.client as C
from .exceptions import OutputFormatError

# names of the reasoning models
REASONING_MODELS: list[str] = ["o1", "o1-mini", "o3-mini", "gemini-2.0-flash-thinking-exp"]

def parse_output(output: str) -> dict:
    """
    Parse the output from the LLM using regex to handle both XML-style tags 
    and markdown code blocks.

    Args:
        output: String containing JSON output either within <output> tags or ```json blocks

    Returns:
        Parsed JSON dictionary

    Raises:
        json.JSONDecodeError: If the output is not a valid JSON
        OutputFormatError: If no valid output format is found
    """
    patterns: list[str] = [
        r'<output>(.*)</output>',
        r'```json\s*(.*)\s*```',
        r'```\s*(.*)\s*```',
    ]
    for pattern in patterns:
        if match := re.search(pattern, output, re.DOTALL):
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue

    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        raise OutputFormatError(f"No valid output format found: {e}") from e


def load_client(
    model: str,
    api_key: str,
    schema: BaseModel | None = None,
    set_retry: bool = True,
    **kwargs
) -> C.BaseClient:
    """Load the client for the model."""
    kwargs["model"] = model
    kwargs["schema"] = schema
    kwargs["set_retry"] = set_retry

    if "/" in model:
        return C.TogetherAIClient(api_key=api_key, **kwargs)

    if model.startswith(("gpt", "o1", "o3")):
        return C.OpenAIClient(api_key=api_key, **kwargs)

    if model.startswith("gemini"):
        return C.GeminiClient(api_key=api_key, **kwargs)

    if model.startswith("claude"):
        return C.ClaudeClient(api_key=api_key, **kwargs)

    raise ValueError(f"Model {model} not supported.")
