"""Offline wire-contract tests using the real SDK with a synthetic HTTP transport."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import openai
import pytest
from pydantic import BaseModel, ConfigDict

from harness import worker_model as worker
from harness.commands import extract
from harness.config import HarnessSettings, get_settings
from harness.ideas import agents, model as ideas
from jobwatch.classifier import (
    AnthropicClassifier, ClassifierProvider, FireworksClassifier, OpenAIClassifier, create_classifier,
)
from jobwatch.models import JobClassification

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]


class Answer(BaseModel):
    """Small schema for validating provider output."""

    model_config = ConfigDict(extra="forbid")
    supported: bool


def completion(content: str | None, finish: str = "stop") -> dict[str, JSON]:
    """Build a minimal synthetic Chat Completions response."""
    return {
        "id": "synthetic", "object": "chat.completion", "created": 0,
        "model": worker.WORKER_MODEL,
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", "content": content}}],
    }


@dataclass
class Wire:
    """Capture requests and provide queued synthetic responses, never network I/O."""

    requests: list[httpx.Request] = field(default_factory=list)
    replies: list[tuple[int, dict[str, JSON]]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Fail a test if the client attempts an unplanned retry or fallback."""
        self.requests.append(request)
        assert self.replies, "Unplanned provider request (retry/fallback)"
        status: int
        body: dict[str, JSON]
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)

    def body(self, index: int = 0) -> dict[str, JSON]:
        """Decode an actual SDK request body."""
        return json.loads(self.requests[index].content)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    """Replace only SDK transport; every request builder and parser stays real."""
    state: Wire = Wire()
    original: type[openai.OpenAI] = openai.OpenAI

    def client(
        *, api_key: str | None = None, base_url: str | None = None,
        timeout: float = 180, max_retries: int = 0,
    ) -> openai.OpenAI:
        """Install the offline transport on a normal OpenAI-compatible client."""
        assert max_retries == 0
        return original(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries,
            http_client=httpx.Client(transport=httpx.MockTransport(state.handle)),
        )

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setenv("FIREWORKS_API_KEY", "synthetic-fireworks-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong-host.example/v1")
    return state


@pytest.mark.parametrize("model", [worker.WORKER_MODEL, worker.WORKER_OPENCLAW_MODEL])
def test_extract_uses_exact_fireworks_host_model_and_high(wire: Wire, model: str) -> None:
    """Both accepted Fireworks refs select only Fireworks auth and its fixed host."""
    wire.replies.append((200, completion("Revenue: 10")))
    settings: HarnessSettings = HarnessSettings(fireworks_api_key="synthetic-settings-key")
    result: extract.CommandResult = extract.extract_command(
        question="Revenue?", stdin=b"Revenue was 10.", model=model, settings=settings,
    )
    assert result.exit_code == 0 and result.stdout == b"Revenue: 10"
    request: httpx.Request = wire.requests[0]
    assert str(request.url) == worker.FIREWORKS_BASE_URL + "/chat/completions"
    assert request.headers["authorization"] == "Bearer synthetic-settings-key"
    assert wire.body()["model"] == "accounts/fireworks/models/glm-5p3-flash"
    assert wire.body()["reasoning_effort"] == "high"
    assert len(wire.requests) == 1


def response_payload(text: str) -> dict[str, JSON]:
    """Build a synthetic Responses API result for Sol wire-contract checks."""
    return {
        "id": "resp_synthetic", "object": "response", "created_at": 0,
        "model": "gpt-6.1-sol", "status": "completed",
        "output": [{"id": "msg_synthetic", "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}],
    }


def test_sol_review_keeps_responses_api_with_high_reasoning(wire: Wire, tmp_path: Path) -> None:
    """A real SDK parse preserves Sol, HIGH and the existing storage parameter."""
    wire.replies.append((200, response_payload('{"supported":true}')))
    assert ideas.generate("Review support", Answer, tmp_path, model="gpt-6.1-sol") == Answer(supported=True)
    assert wire.requests[0].url.path == "/v1/responses"
    assert wire.body()["model"] == "gpt-6.1-sol"
    assert wire.body()["reasoning"] == {"effort": "high"}
    assert wire.body()["store"] is False  # This alone is not an account ZDR guarantee.
    assert len(wire.requests) == 1


def test_sol_orchestrator_keeps_responses_api_and_high(wire: Wire, tmp_path: Path) -> None:
    """Sol orchestration is not replaced by a worker model."""
    wire.replies.append((200, response_payload("Research complete")))
    assert agents._loop(
        "Coordinate research", model="gpt-6.1-sol", folder=tmp_path, tools=[],
        dispatch=lambda name, arguments: {}, deadline=time.monotonic() + 30,
        label="coordinator", cancel=threading.Event(),
    ) == "Research complete"
    assert wire.body()["model"] == "gpt-6.1-sol"
    assert wire.body()["reasoning"] == {"effort": "high"}
    assert wire.body()["include"] == ["reasoning.encrypted_content"]
    assert wire.body()["store"] is False
    assert len(wire.requests) == 1


def test_explicit_openai_extract_override_keeps_model_and_effort(wire: Wire) -> None:
    """The new default does not rewrite a provider-qualified caller model."""
    wire.replies.append((200, response_payload("Explicit OpenAI answer")))
    result: extract.CommandResult = extract.extract_command(
        question="Q", stdin=b"Synthetic input", model="openai/gpt-6.1-sol", thinking="low",
        settings=HarnessSettings(openai_api_key="synthetic-openai-key"),
    )
    assert result.exit_code == 0 and result.stdout == b"Explicit OpenAI answer"
    assert wire.body()["model"] == "gpt-6.1-sol"
    assert wire.body()["reasoning"] == {"effort": "low"}
    assert wire.requests[0].url.path == "/v1/responses"
    assert len(wire.requests) == 1


def test_settings_reads_only_named_fireworks_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI can obtain the worker key from the host-owned environment."""
    monkeypatch.setenv("FIREWORKS_API_KEY", "synthetic-env-key")
    get_settings.cache_clear()
    try:
        assert get_settings().fireworks_api_key == "synthetic-env-key"
    finally:
        get_settings.cache_clear()


def test_parallel_extraction_uses_worker_route_and_keeps_safe_failures(wire: Wire, tmp_path: Path) -> None:
    """Parallel text exploration keeps successes and records a sanitized failure."""
    first: Path = tmp_path / "first.txt"
    second: Path = tmp_path / "second.txt"
    output: Path = tmp_path / "output"
    first.write_text("Synthetic first source")
    second.write_text("Synthetic second source")
    wire.replies.extend([
        (200, completion("Extracted evidence")),
        (500, {"error": {"message": "synthetic-sensitive-marker"}}),
    ])
    result: extract.CommandResult = extract.extract_files_command(
        question="Find the evidence", files=[str(first), str(second)], out=str(output),
        concurrency=2, settings=HarnessSettings(fireworks_api_key="synthetic-key"),
    )
    manifest: dict[str, JSON] = json.loads((output / "manifest.json").read_text())
    assert result.exit_code == 1
    assert manifest["model"] == worker.WORKER_MODEL and manifest["thinking"] == "high"
    assert sorted(entry["status"] for entry in manifest["entries"]) == ["error", "ok"]
    assert "synthetic-sensitive-marker" not in json.dumps(manifest)
    assert len(list(output.glob("*.md"))) == 1
    assert len(wire.requests) == 2
    for request in wire.requests:
        assert str(request.url) == worker.FIREWORKS_BASE_URL + "/chat/completions"
        body: dict[str, JSON] = json.loads(request.content)
        assert body["model"] == worker.WORKER_MODEL and body["reasoning_effort"] == "high"


def test_nonfast_model_and_effort_override_are_not_substituted(wire: Wire) -> None:
    """An explicit non-fast GLM is a different model, not a FLASH alias."""
    wire.replies.append((200, completion("Explicit result")))
    result: extract.CommandResult = extract.summarize_command(
        stdin=b"Synthetic source", model="fireworks/accounts/fireworks/models/glm-5p3",
        thinking="low", settings=HarnessSettings(fireworks_api_key="synthetic-key"),
    )
    assert result.exit_code == 0
    assert wire.body()["model"] == "accounts/fireworks/models/glm-5p3"
    assert wire.body()["reasoning_effort"] == "low"


def test_missing_fireworks_auth_never_uses_other_provider_keys(wire: Wire) -> None:
    """Configured Google/OpenAI keys cannot satisfy a Fireworks request."""
    settings: HarnessSettings = HarnessSettings(
        openai_api_key="synthetic-openai", gemini_api_key="synthetic-google",
    )
    result: extract.CommandResult = extract.extract_command(question="Q", stdin=b"Document", settings=settings)
    assert result.exit_code == 1 and b"FIREWORKS_API_KEY" in result.stderr
    assert not wire.requests


@pytest.mark.parametrize("finish,content", [
    ("length", "partial"), ("stop", ""), ("content_filter", None),
])
def test_incomplete_text_is_a_failure_without_fallback(
    wire: Wire, finish: str, content: str | None,
) -> None:
    """Do not publish partial, empty or filtered worker results."""
    wire.replies.append((200, completion(content, finish)))
    with pytest.raises(ValueError):
        worker.generate_fireworks("Synthetic input")
    assert len(wire.requests) == 1


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_error_is_secret_safe_and_never_retried(wire: Wire, status: int) -> None:
    """Provider error bodies cannot leak headers/keys into CLI error output."""
    wire.replies.append((status, {"error": {"message": "synthetic-sensitive-marker"}}))
    result: extract.CommandResult = extract.summarize_command(
        stdin=b"Synthetic document", settings=HarnessSettings(fireworks_api_key="synthetic-key"),
    )
    assert result.exit_code == 1
    assert b"synthetic-sensitive-marker" not in result.stderr
    assert len(wire.requests) == 1


@pytest.mark.parametrize("content", ['{"supported":true}', 'not JSON', '{"wrong":1}'])
def test_ideas_structured_json_and_validation(
    wire: Wire, tmp_path: Path, content: str,
) -> None:
    """Use reasoning-compatible prompt schemas and reject invalid JSON locally."""
    wire.replies.append((200, completion(content)))
    if content == '{"supported":true}':
        assert ideas.generate("Check support", Answer, tmp_path, model=worker.WORKER_MODEL) == Answer(supported=True)
        assert list((tmp_path / "research/model").glob("*.response.json"))
    else:
        with pytest.raises(ideas.ModelError):
            ideas.generate("Check support", Answer, tmp_path, model=worker.WORKER_MODEL)
    body: dict[str, JSON] = wire.body()
    assert body["reasoning_effort"] == "high"
    assert "response_format" not in body  # Must not disable reasoning output.
    assert json.dumps(Answer.model_json_schema()) in body["messages"][0]["content"]
    assert "Return only a JSON object" in body["messages"][0]["content"]
    assert len(wire.requests) == 1


def test_default_classifier_uses_fireworks_and_validates_output(wire: Wire) -> None:
    """The real generic factory selects GLM, not the retained legacy providers."""
    expected: JobClassification = JobClassification(
        justification="Builds backend services", department="ENG", role_type="ENG.BE",
        seniority="SENIOR", confidence=0.9,
    )
    wire.replies.append((200, completion(expected.model_dump_json())))
    classifier: ClassifierProvider = create_classifier()
    assert isinstance(classifier, FireworksClassifier)
    assert classifier.classify("Senior Backend Engineer", "Engineering", "Build APIs") == expected
    assert classifier.model_name == worker.WORKER_MODEL
    assert wire.body()["model"] == worker.WORKER_MODEL
    assert wire.body()["reasoning_effort"] == "high"
    assert "response_format" not in wire.body()
    assert json.dumps(JobClassification.model_json_schema()) in wire.body()["messages"][0]["content"]


def test_explicit_legacy_classifier_is_not_replaced(wire: Wire) -> None:
    """Legacy OpenAI remains an opt-in class with its exact caller model."""
    classifier: ClassifierProvider = create_classifier("openai", model="gpt-4o-mini")
    assert isinstance(classifier, OpenAIClassifier)
    assert classifier.model_name == "gpt-4o-mini"
    assert not wire.requests


def test_missing_worker_key_stops_ideas_and_classifier(
    wire: Wire, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No direct consumer can use the configured OpenAI key as a fallback."""
    monkeypatch.delenv("FIREWORKS_API_KEY")
    with pytest.raises(ideas.ModelError, match="FIREWORKS_API_KEY"):
        ideas.generate("Synthetic check", Answer, tmp_path, model=worker.WORKER_MODEL)
    with pytest.raises(ValueError, match="FIREWORKS_API_KEY"):
        create_classifier().classify("Engineer", None, None)
    with pytest.raises(ideas.ModelError, match="FIREWORKS_API_KEY"):
        agents._loop(
            "Synthetic task", model=worker.WORKER_MODEL, folder=tmp_path, tools=[],
            dispatch=lambda name, arguments: {}, deadline=time.monotonic() + 30,
            label="offline", cancel=threading.Event(),
        )
    assert not wire.requests


def test_classifier_rejects_bad_schema_and_cross_provider_ids(wire: Wire) -> None:
    """Schema failure and wrong-provider input are errors, not fallback signals."""
    wire.replies.append((200, completion('{"department":"ENG"}')))
    with pytest.raises(ValueError, match="invalid structured JSON"):
        create_classifier().classify("Engineer", None, None)
    with pytest.raises(ValueError):
        OpenAIClassifier(model=worker.WORKER_MODEL)
    with pytest.raises(ValueError):
        AnthropicClassifier(model=worker.WORKER_MODEL)
    with pytest.raises(ValueError):
        FireworksClassifier(model="gpt-4o-mini")
    with pytest.raises(ValueError):
        create_classifier("unknown")
    assert len(wire.requests) == 1


def test_fireworks_agent_tool_replay_uses_native_chat_protocol(wire: Wire, tmp_path: Path) -> None:
    """Exercise a real two-turn tool exchange and archive the provider-native history."""
    first: dict[str, JSON] = completion(None, "tool_calls")
    first["choices"][0]["message"]["tool_calls"] = [{
        "id": "call_synthetic", "type": "function",
        "function": {"name": "search", "arguments": '{"query":"Acme letter"}'},
    }]
    first["choices"][0]["message"]["reasoning_content"] = "Synthetic reasoning"
    wire.replies.extend([(200, first), (200, completion("Source found"))])

    def dispatch(name: str, arguments: str) -> agents.Result:
        """Return synthetic source evidence from the typed tool boundary."""
        assert name == "search"
        query: agents.Search = agents.Search.model_validate_json(arguments)
        return {"url": "https://example.com/letter", "query": query.query}

    result: str = agents._loop(
        "Find Acme's original letter", model=worker.WORKER_MODEL, folder=tmp_path,
        tools=[agents._tool("search", agents.Search, "Find originals")], dispatch=dispatch,
        deadline=time.monotonic() + 30, label="offline", cancel=threading.Event(),
    )
    assert result == "Source found"
    assert len(wire.requests) == 2
    assert all(str(request.url) == worker.FIREWORKS_BASE_URL + "/chat/completions" for request in wire.requests)
    assert wire.body()["reasoning_effort"] == "high"
    assert wire.body()["tools"][0]["function"]["name"] == "search"
    history: JSON = wire.body(1)["messages"]
    assert history[1]["reasoning_content"] == "Synthetic reasoning"
    assert history[2]["role"] == "tool" and history[2]["tool_call_id"] == "call_synthetic"
    assert json.loads(history[2]["content"])["url"] == "https://example.com/letter"


def test_agent_provider_error_stops_without_fallback(wire: Wire, tmp_path: Path) -> None:
    """Agent traces contain only safe error metadata, never provider error bodies."""
    wire.replies.append((500, {"error": {"message": "synthetic-sensitive-marker"}}))
    with pytest.raises(ideas.ModelError):
        agents._loop(
            "Synthetic task", model=worker.WORKER_MODEL, folder=tmp_path,
            tools=[], dispatch=lambda name, arguments: {}, deadline=time.monotonic() + 30,
            label="offline", cancel=threading.Event(),
        )
    assert len(wire.requests) == 1
    assert all("synthetic-sensitive-marker" not in file.read_text() for file in tmp_path.rglob("*.json"))
