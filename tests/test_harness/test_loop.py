"""Tests for the Anthropic-backed harness loop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import loop
from harness.config import HarnessSettings
from harness.output import CommandResult


def test_build_system_prompt_includes_dynamic_command_catalog(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    (tmp_path / "notes.txt").write_text("workspace file", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(loop, "generate_command_catalog", lambda app: "web search\nsec 10k")

    prompt = loop.build_system_prompt(settings=settings)

    assert "Available commands:\nweb search\nsec 10k" in prompt
    assert "Workspace state:" in prompt
    assert "- notes.txt" in prompt
    assert "- reports/" in prompt


def test_run_agent_loop_dispatches_tool_calls_and_collects_output(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(
        workspace_root=tmp_path,
        anthropic_api_key="test-key",
        llm_model="anthropic/test-model",
    )
    calls: list[str] = []
    client_holder: dict[str, object] = {}
    responses = [
        SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", id="tool-1", input={"command": "ls reports"})]
        ),
        SimpleNamespace(content=[SimpleNamespace(type="text", text="Final answer")]),
    ]

    class _FakeMessages:
        def __init__(self, queued_responses) -> None:
            self.calls: list[dict[str, object]] = []
            self._queued_responses = list(queued_responses)

        def create(self, **kwargs):
            snapshot = dict(kwargs)
            snapshot["messages"] = list(kwargs["messages"])
            self.calls.append(snapshot)
            return self._queued_responses.pop(0)

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages(responses)

    def fake_anthropic(*, api_key: str):
        client = _FakeClient()
        client_holder["client"] = client
        assert api_key == "test-key"
        return client

    def fake_execute_chain(command: str, settings: HarnessSettings | None = None) -> CommandResult:
        calls.append(command)
        return CommandResult.from_text("tool output", duration_ms=12)

    monkeypatch.setattr(loop, "Anthropic", fake_anthropic)
    monkeypatch.setattr(loop, "execute_chain", fake_execute_chain)

    result = loop.run_agent_loop("Inspect the workspace", settings=settings)
    client = client_holder["client"]

    assert result == "Final answer"
    assert calls == ["ls reports"]
    assert client.messages.calls[0]["model"] == "test-model"
    assert client.messages.calls[1]["messages"][-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "tool-1",
            "content": "tool output\n[exit:0 | 12ms]",
        }
    ]


def test_compact_messages_summarizes_when_threshold_is_exceeded(monkeypatch) -> None:
    messages = [{"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"} for index in range(8)]
    monkeypatch.setattr(loop, "estimate_tokens", lambda text: loop.MAX_CONTEXT_TOKENS + 1)

    compacted = loop.compact_messages(messages)

    assert len(compacted) == 7
    assert compacted[0]["role"] == "assistant"
    assert compacted[0]["content"].startswith("Earlier context summary:")
    assert compacted[1:] == messages[-6:]


def test_run_agent_loop_returns_text_responses_directly(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(
        workspace_root=tmp_path,
        anthropic_api_key="test-key",
        llm_model="anthropic/test-model",
    )

    class _FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="First line"),
                    SimpleNamespace(type="text", text="Second line"),
                ]
            )

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    monkeypatch.setattr(loop, "Anthropic", lambda *, api_key: _FakeClient())

    result = loop.run_agent_loop("Answer directly", settings=settings)

    assert result == "First line\nSecond line"


def test_run_agent_loop_propagates_api_failures(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(
        workspace_root=tmp_path,
        anthropic_api_key="test-key",
        llm_model="anthropic/test-model",
    )

    class _FakeMessages:
        def create(self, **kwargs):
            raise RuntimeError("api down")

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    monkeypatch.setattr(loop, "Anthropic", lambda *, api_key: _FakeClient())

    with pytest.raises(RuntimeError, match="api down"):
        loop.run_agent_loop("Trigger failure", settings=settings)
