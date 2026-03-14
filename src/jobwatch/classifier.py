"""LLM classification module for JobWatch."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from jobwatch.models import JobClassification

_FENCE_RE: re.Pattern[str] = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json_response(raw: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    fence_match: re.Match[str] | None = _FENCE_RE.search(raw)
    text: str = fence_match.group(1) if fence_match else raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse LLM JSON: {exc}\nRaw output: {raw[:500]}") from exc

SYSTEM_PROMPT: str = """\
Classify this job posting into department, role type, and seniority.
Provide a brief justification (1-2 sentences) noting key evidence.

Codes:
- department: ENG, RES, PROD, DES, DATA, INFRA, SEC, SALES, MKT, CS, OPS, PPL, FIN, LEGAL, EXEC, UNKNOWN
- role_type: ENG has subcategories (ENG.FE, ENG.BE, ENG.FS, ENG.ML, ENG.PLAT, ENG.SRE, ENG.MOB, \
ENG.DATA, ENG.SEC, ENG.EMBEDDED, ENG.QA, ENG.FDE, ENG.GEN). All other departments use {DEPT}.GEN.
- seniority: INTERN, JUNIOR, MID, SENIOR, STAFF, LEAD, DIRECTOR, VP, C_LEVEL, UNKNOWN

Precedence rules:
- "Research Engineer" → ENG.ML (engineering function)
- "Applied AI Engineer" → ENG.ML
- "Member of Technical Staff" → ENG.GEN (unless description clarifies)
- "Research Scientist" → RES.GEN
- "Technical Program Manager" → PROD.GEN
- "Solutions Architect" → SALES.GEN
- If confidence < 0.6, use UNKNOWN for department or {DEPT}.GEN for role type.

Respond with a JSON object matching this schema:
{"justification": str, "department": str, "role_type": str, "seniority": str, "confidence": float}"""

_DESC_CHAR_LIMIT: int = 1500


def build_user_message(
    title: str, department_raw: str | None, description: str | None
) -> str:
    """Format posting info into an LLM user message."""
    desc_text: str = description[:_DESC_CHAR_LIMIT] if description else "N/A"
    return (
        f"Title: {title}\n"
        f"Department (from ATS): {department_raw or 'N/A'}\n"
        f"Description (first {_DESC_CHAR_LIMIT} chars): {desc_text}"
    )


class ClassifierProvider(ABC):
    """Abstract base for LLM classification providers."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def classify(
        self,
        title: str,
        department_raw: str | None,
        description: str | None,
    ) -> JobClassification: ...


class AnthropicClassifier(ClassifierProvider):
    """Anthropic-backed classifier using the Messages API."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: str | None = None,
    ):
        import anthropic

        self._client: anthropic.Anthropic = anthropic.Anthropic(api_key=api_key)
        self._model: str = model

    @property
    def model_name(self) -> str:
        return self._model

    def classify(
        self,
        title: str,
        department_raw: str | None,
        description: str | None,
    ) -> JobClassification:
        user_message: str = build_user_message(title, department_raw, description)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=256,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            raise RuntimeError(f"Anthropic API error: {exc}") from exc

        raw_text: str = response.content[0].text
        data: dict = _parse_json_response(raw_text)
        return JobClassification(**data)


class OpenAIClassifier(ClassifierProvider):
    """OpenAI-backed classifier using the Chat Completions API."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ):
        import openai

        self._client: openai.OpenAI = openai.OpenAI(api_key=api_key)
        self._model: str = model

    @property
    def model_name(self) -> str:
        return self._model

    def classify(
        self,
        title: str,
        department_raw: str | None,
        description: str | None,
    ) -> JobClassification:
        user_message: str = build_user_message(title, department_raw, description)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
        except Exception as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc

        raw_text: str = response.choices[0].message.content
        data: dict = _parse_json_response(raw_text)
        return JobClassification(**data)


def classify_postings(
    provider: ClassifierProvider,
    postings: list[tuple[str, str | None, str | None]],
) -> list[JobClassification]:
    """Classify postings sequentially (v1 — no concurrency).

    Args:
        provider: LLM classification provider.
        postings: List of (title, department_raw, description) tuples.

    Returns:
        Classifications in the same order as input postings.
    """
    results: list[JobClassification] = []
    for title, department_raw, description in postings:
        classification: JobClassification = provider.classify(
            title, department_raw, description
        )
        results.append(classification)
    return results
