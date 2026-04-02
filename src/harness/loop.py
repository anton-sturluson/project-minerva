"""Anthropic-backed agent loop for the investment harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from harness.cli import app as cli_app
from harness.cli import execute_chain, generate_command_catalog
from harness.config import HarnessSettings, get_settings
from harness.context import estimate_tokens
from harness.output import OutputEnvelope

MAX_CONTEXT_TOKENS: int = 24_000


def build_system_prompt(settings: HarnessSettings | None = None) -> str:
    """Build the system prompt from persona, commands, and workspace state."""
    active_settings: HarnessSettings = settings or get_settings()
    catalog: str = generate_command_catalog(cli_app)
    workspace_state: str = describe_workspace(active_settings.ensure_workspace_root())
    return (
        "You are Minerva, an investment research analyst operating through a local CLI.\n"
        "Use tools deliberately, prefer workspace-scoped file operations, and keep outputs concise.\n\n"
        "Available commands:\n"
        f"{catalog}\n\n"
        "Workspace state:\n"
        f"{workspace_state}"
    )


def describe_workspace(workspace_root: Path) -> str:
    """Describe top-level workspace contents for prompt injection."""
    if not workspace_root.exists():
        return f"{workspace_root} (missing)"

    entries: list[str] = []
    for child in sorted(workspace_root.iterdir())[:20]:
        suffix: str = "/" if child.is_dir() else ""
        entries.append(f"- {child.name}{suffix}")
    if not entries:
        entries.append("- (empty)")
    return "\n".join(entries)


def run_agent_loop(prompt: str, settings: HarnessSettings | None = None, max_loops: int = 8) -> str:
    """Run the Anthropic tool loop until a final text response is produced."""
    active_settings: HarnessSettings = settings or get_settings()
    if active_settings.llm_provider != "anthropic":
        raise ValueError(f"Unsupported llm_provider for Phase 1: {active_settings.llm_provider}")
    if not active_settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required to run the loop.")

    client = Anthropic(api_key=active_settings.anthropic_api_key)
    system_prompt: str = build_system_prompt(active_settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tools: list[dict[str, Any]] = [
        {
            "name": "run",
            "description": "Execute a Minerva CLI command chain and return the presented output.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "CLI command string, including pipes and boolean operators when needed.",
                    }
                },
                "required": ["command"],
            },
        }
    ]

    for _ in range(max_loops):
        response = client.messages.create(
            model=_strip_provider_prefix(active_settings.llm_model),
            system=system_prompt,
            max_tokens=1_500,
            messages=messages,
            tools=tools,
        )
        assistant_message: dict[str, Any] = {"role": "assistant", "content": response.content}
        messages.append(assistant_message)

        tool_uses: list[Any] = [block for block in response.content if getattr(block, "type", "") == "tool_use"]
        if not tool_uses:
            text_parts: list[str] = [block.text for block in response.content if getattr(block, "type", "") == "text"]
            return "\n".join(part for part in text_parts if part).strip()

        tool_results: list[dict[str, Any]] = []
        for tool_use in tool_uses:
            command: str = tool_use.input["command"]
            result = execute_chain(command, settings=active_settings)
            envelope = OutputEnvelope.from_result(result, workspace_root=active_settings.ensure_workspace_root())
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": envelope.render(),
                }
            )

        messages.append({"role": "user", "content": tool_results})
        messages = compact_messages(messages)

    raise RuntimeError("Agent loop exceeded the maximum tool iterations.")


def compact_messages(messages: list[dict[str, Any]], max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict[str, Any]]:
    """Summarize older turns when the estimated context budget is exceeded."""
    total_tokens: int = estimate_tokens(_messages_to_text(messages))
    if total_tokens <= max_tokens or len(messages) <= 6:
        return messages

    preserved: list[dict[str, Any]] = messages[-6:]
    summarized: list[dict[str, Any]] = messages[:-6]
    summary_lines: list[str] = ["Earlier context summary:"]
    for message in summarized:
        role: str = message["role"]
        content: Any = message["content"]
        if isinstance(content, str):
            text: str = content
        else:
            text = json.dumps(content, default=str)
        cleaned: str = " ".join(text.split())
        summary_lines.append(f"{role}: {cleaned[:400]}")

    return [{"role": "assistant", "content": "\n".join(summary_lines)}] + preserved


def main() -> None:
    """Entry point for the standalone loop runner."""
    parser = argparse.ArgumentParser(description="Run the Minerva investment harness loop.")
    parser.add_argument("prompt", help="User prompt to send to the loop.")
    parser.add_argument("--max-loops", type=int, default=8, help="Maximum number of tool iterations.")
    args = parser.parse_args()
    print(run_agent_loop(args.prompt, max_loops=args.max_loops))


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    for message in messages:
        pieces.append(message["role"])
        content: Any = message["content"]
        if isinstance(content, str):
            pieces.append(content)
        else:
            pieces.append(json.dumps(content, default=str))
    return "\n".join(pieces)


def _strip_provider_prefix(model_name: str) -> str:
    if "/" in model_name:
        return model_name.split("/", maxsplit=1)[1]
    return model_name
