"""Deep research via Parallel.ai."""

from __future__ import annotations

import json
import time

import typer

from harness.commands.common import (
    abort_with_help,
    elapsed_ms,
    error_result,
    maybe_export_text,
    parse_flag_args,
    retry_call,
    should_retry_http_error,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

RESEARCH_HELP = (
    "Deep web research powered by Parallel.ai.\n\n"
    "Examples:\n"
    "  minerva research \"market map of vertical SaaS companies in hospitality\"\n"
    "  minerva research \"create a comprehensive analysis of travel tech value migration\" --output travel-tech.md\n"
)

app = typer.Typer(help=RESEARCH_HELP, no_args_is_help=False, invoke_without_command=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch research for `minerva run`."""
    _ = stdin
    active_settings = settings or get_settings()
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no research query was provided",
                "pass a natural-language research question",
                ["`research \"market map of vertical SaaS companies in hospitality\"`", "`research \"travel tech value migration\" --output travel-tech.md`"],
                RESEARCH_HELP,
            ),
            exit_code=1,
        )
    query = args[0]
    try:
        parsed = parse_flag_args(args[1:])
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)
    return research_command(query=query, output_path=str(parsed["output"]) if "output" in parsed else None, settings=active_settings)


def research_command(
    *,
    query: str,
    output_path: str | None = None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start = time.perf_counter()
    active_settings = settings or get_settings()
    if not active_settings.parallel_api_key:
        return error_result(
            "PARALLEL_API_KEY is not set",
            "set PARALLEL_API_KEY and retry",
            ["`export PARALLEL_API_KEY=...`", "`minerva extract \"Question\" --file document.md`"],
            start,
        )
    try:
        response_text = retry_call(
            lambda: _call_parallel(query=query, api_key=active_settings.parallel_api_key),
            should_retry=should_retry_http_error,
        )
    except Exception as exc:
        return error_result(
            f"deep research request failed: {exc}",
            "verify PARALLEL_API_KEY and retry with a focused query",
            ["`research \"travel tech value migration\"`", "`research \"market map of vertical SaaS companies in hospitality\" --output market-map.md`"],
            start,
        )
    output = response_text + maybe_export_text(response_text, output_path)
    return CommandResult.from_text(output, duration_ms=elapsed_ms(start))


@app.callback()
def research_cli_command(
    ctx: typer.Context,
    query: str | None = typer.Argument(None, help="Research query in natural language."),
    output: str | None = typer.Option(None, "--output", help="Optional path to save the results."),
) -> None:
    """Run a deep research query through Parallel.ai.

    Example:
      minerva research "market map of vertical SaaS companies in hospitality"
    """
    if not query:
        abort_with_help(
            ctx,
            what_went_wrong="no research query was provided",
            what_to_do="pass a natural-language research question",
            alternatives=["`minerva research \"market map of vertical SaaS companies in hospitality\"`", "`minerva research \"travel tech value migration\" --output travel-tech.md`"],
        )
    _print(research_command(query=query, output_path=output))


def _call_parallel(*, query: str, api_key: str) -> str:
    import httpx

    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    with httpx.Client(timeout=600.0) as client:
        # 1. Create task run (async – returns 202 with run_id)
        create_resp = client.post(
            "https://api.parallel.ai/v1/tasks/runs",
            headers=headers,
            json={
                "input": query,
                "processor": "core",
            },
        )
        create_resp.raise_for_status()
        run_id = create_resp.json()["run_id"]

        # 2. Block until complete via the result endpoint (server-side long-poll)
        result_resp = client.get(
            f"https://api.parallel.ai/v1/tasks/runs/{run_id}/result",
            headers=headers,
            params={"timeout": 600},
        )
        result_resp.raise_for_status()
        payload = result_resp.json()

    # Extract output text from the new response structure
    output = payload.get("output", {})
    content = output.get("content", {})
    if isinstance(content, dict):
        text = content.get("output", "")
        if isinstance(text, str) and text.strip():
            return text
    if isinstance(content, str) and content.strip():
        return content
    return json.dumps(payload, indent=2, sort_keys=True)


def _usage_error(what: str, what_to_do: str, alternatives: list[str], help_text: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {what}",
            f"What to do instead: {what_to_do}",
            f"Available alternatives: {', '.join(alternatives)}",
            "",
            help_text.rstrip(),
        ]
    )


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
