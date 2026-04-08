"""Delegated document reading commands."""

from __future__ import annotations

import asyncio
import time

import typer

from harness.commands.common import elapsed_ms, error_result
from harness.commands.fs import resolve_workspace_path
from harness.config import HarnessSettings, get_settings
from harness.delegate import delegate_read, delegate_read_many, extract_text_from_path
from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(help="Delegated document reads.", no_args_is_help=False)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path delegated-read commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "read",
            "Usage: read <file> <question> | read many <file> <question1> <question2> ... [--parallel N]",
            ["read memo.pdf \"What changed?\"", "read many memo.pdf \"What changed?\" \"Key risks?\""],
        )

    if args[0] == "many":
        if len(args) < 4:
            return _usage_error(
                "read many",
                "Usage: read many <file> <question1> <question2> ... [--parallel N]",
                ["read <file> <question>"],
            )
        parallel: int = 4
        payload: list[str] = args[1:]
        if "--parallel" in payload:
            option_index: int = payload.index("--parallel")
            if option_index + 1 >= len(payload):
                return _usage_error(
                    "read many",
                    "Usage: read many <file> <question1> <question2> ... [--parallel N]",
                    ["read <file> <question>"],
                )
            parallel = int(payload[option_index + 1])
            payload = payload[:option_index]
        if len(payload) < 3:
            return _usage_error(
                "read many",
                "Usage: read many <file> <question1> <question2> ... [--parallel N]",
                ["read <file> <question>"],
            )
        return read_many_command_result(payload[0], payload[1:], parallel=parallel, settings=active_settings)

    if len(args) < 2:
        return _usage_error("read", "Usage: read <file> <question>", ["read many <file> <question1> <question2>"])
    return read_command_result(args[0], " ".join(args[1:]), settings=active_settings)


def read_many_alias_dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Support `read-many` as a shell alias for `read many`."""
    return dispatch(["many", *args], settings=settings, stdin=stdin)


def read_command_result(file_path: str, question: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target = resolve_workspace_path(file_path, active_settings)
        document_text: str = extract_text_from_path(target)
        answer: str = asyncio.run(
            delegate_read(
                document_text,
                question,
                api_key=active_settings.anthropic_api_key,
                model=_strip_provider_prefix(active_settings.delegate_model),
            )
        )
    except Exception as exc:
        return error_result(
            f"What went wrong: delegated read failed for {file_path}: {exc}\n"
            "What to do instead: verify the file path, file format, and ANTHROPIC_API_KEY, then retry.\n"
            "Available alternatives: `cat <file>`, `stat <file>`, `read many <file> <question1> <question2>`",
            start,
        )

    return CommandResult.from_text(answer, duration_ms=elapsed_ms(start))


def read_many_command_result(
    file_path: str,
    questions: list[str],
    *,
    parallel: int = 4,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        target = resolve_workspace_path(file_path, active_settings)
        document_text: str = extract_text_from_path(target)
        answers: list[str] = asyncio.run(
            delegate_read_many(
                document_text,
                questions,
                parallel=parallel,
                api_key=active_settings.anthropic_api_key,
                model=_strip_provider_prefix(active_settings.delegate_model),
            )
        )
    except Exception as exc:
        return error_result(
            f"What went wrong: delegated multi-read failed for {file_path}: {exc}\n"
            "What to do instead: verify the file path, questions, and ANTHROPIC_API_KEY, then retry.\n"
            "Available alternatives: `read <file> <question>`, `cat <file>`",
            start,
        )

    sections: list[str] = []
    for question, answer in zip(questions, answers, strict=False):
        sections.append(f"## {question}\n\n{answer}")
    return CommandResult.from_text("\n\n".join(sections), duration_ms=elapsed_ms(start))


@app.callback(invoke_without_command=True)
def read_callback(
    ctx: typer.Context,
    file_path: str | None = typer.Argument(None, help="Workspace-relative path to read."),
    question_parts: list[str] | None = typer.Argument(None, help="Question to ask about the file."),
) -> None:
    """Run a single delegated read."""
    if ctx.invoked_subcommand is not None:
        return
    if not file_path or not question_parts:
        _print(_usage_error("read", "Usage: read <file> <question>", ["read many <file> <question1> <question2>"]))
        raise typer.Exit()
    _print(read_command_result(file_path, " ".join(question_parts)))


@app.command("many")
def many_command(
    file_path: str = typer.Argument(..., help="Workspace-relative path to read."),
    questions: list[str] = typer.Argument(..., help="Two or more questions."),
    parallel: int = typer.Option(4, "--parallel", min=1, help="Maximum concurrent LLM calls."),
) -> None:
    """Run multiple delegated reads against one document."""
    _print(read_many_command_result(file_path, questions, parallel=parallel))


def _strip_provider_prefix(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def _usage_error(command: str, usage: str, alternatives: list[str]) -> CommandResult:
    return CommandResult.from_text(
        "",
        stderr=(
            f"Invalid invocation for `{command}`.\n"
            f"What to do instead: {usage}\n"
            f"Available alternatives: {', '.join(alternatives)}"
        ),
        exit_code=1,
    )


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
