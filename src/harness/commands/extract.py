"""LLM extraction commands backed by Gemini."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import typer

from harness.commands.common import (
    abort_with_help,
    elapsed_ms,
    error_result,
    parse_flag_args,
    read_text_input,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

EXTRACT_HELP = (
    "LLM-powered information extraction from large text documents.\n\n"
    "Examples:\n"
    "  minerva extract \"What is the revenue by segment?\" --file apple-10k.md\n"
    "  minerva extract-many --file apple-10k.md \"Revenue by segment\" \"Key risk factors\"\n"
    "  minerva run \"sec 10k AAPL --items 1A | extract 'What are the top 3 risk factors?'\"\n"
)

DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
SYSTEM_PROMPT = (
    "Extract information relevant to the following question. "
    "Be concise and specific. Cite section/page numbers when possible."
)

app = typer.Typer(help=EXTRACT_HELP, no_args_is_help=False, invoke_without_command=True)
extract_many_app = typer.Typer(help=EXTRACT_HELP, no_args_is_help=False, invoke_without_command=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch the single-question extract command for `minerva run`."""
    active_settings = settings or get_settings()
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no extraction question was provided",
                "pass a question and either `--file PATH` or piped stdin",
                ["`extract \"What is the revenue by segment?\" --file apple-10k.md`", "`extract-many --file apple-10k.md \"Revenue by segment\" \"Key risks\"`"],
                EXTRACT_HELP,
            ),
            exit_code=1,
        )

    question = args[0]
    try:
        parsed = parse_flag_args(args[1:])
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)
    return extract_command(
        question=question,
        file_path=str(parsed["file"]) if "file" in parsed else None,
        model=str(parsed.get("model", DEFAULT_MODEL)),
        max_tokens=int(parsed.get("max-tokens", 4096)),
        stdin=stdin,
        settings=active_settings,
    )


def dispatch_many(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch the multi-question extract command for `minerva run`."""
    active_settings = settings or get_settings()
    file_path: str | None = None
    questions_file: str | None = None
    model: str = DEFAULT_MODEL
    max_tokens: int = 4096
    questions: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--file" and index + 1 < len(args):
            file_path = args[index + 1]
            index += 2
            continue
        if token == "--questions-file" and index + 1 < len(args):
            questions_file = args[index + 1]
            index += 2
            continue
        if token == "--model" and index + 1 < len(args):
            model = args[index + 1]
            index += 2
            continue
        if token == "--max-tokens" and index + 1 < len(args):
            max_tokens = int(args[index + 1])
            index += 2
            continue
        questions.append(token)
        index += 1

    return extract_many_command(
        questions=questions,
        file_path=file_path,
        questions_file=questions_file,
        model=model,
        max_tokens=max_tokens,
        stdin=stdin,
        settings=active_settings,
    )


def extract_command(
    *,
    question: str,
    file_path: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    stdin: bytes = b"",
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start = time.perf_counter()
    active_settings = settings or get_settings()
    if not active_settings.gemini_api_key:
        return error_result(
            "GEMINI_API_KEY is not set",
            "set GEMINI_API_KEY and retry",
            ["`export GEMINI_API_KEY=...`", "`minerva analyze ngrams sample.txt`"],
            start,
        )
    try:
        document_text = read_text_input(file_path=file_path, stdin=stdin)
        answer = _generate_answer(
            question=question,
            document_text=document_text,
            model=model,
            max_tokens=max_tokens,
            api_key=active_settings.gemini_api_key,
        )
    except Exception as exc:
        return error_result(
            f"extraction failed: {exc}",
            "verify the input source, Gemini API key, and model name, then retry",
            ["`extract \"What is the revenue by segment?\" --file apple-10k.md`", "`extract-many --file apple-10k.md \"Revenue by segment\" \"Key risks\"`"],
            start,
        )
    return CommandResult.from_text(answer.strip(), duration_ms=elapsed_ms(start))


def extract_many_command(
    *,
    questions: list[str],
    file_path: str | None = None,
    questions_file: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    stdin: bytes = b"",
    settings: HarnessSettings | None = None,
) -> CommandResult:
    start = time.perf_counter()
    active_settings = settings or get_settings()
    if not active_settings.gemini_api_key:
        return error_result(
            "GEMINI_API_KEY is not set",
            "set GEMINI_API_KEY and retry",
            ["`export GEMINI_API_KEY=...`", "`minerva analyze topics sample.txt`"],
            start,
        )
    try:
        merged_questions = _merge_questions(questions, questions_file)
        if not merged_questions:
            raise ValueError("at least one question is required")
        document_text = read_text_input(file_path=file_path, stdin=stdin)
        answers = asyncio.run(
            _gather_answers(
                questions=merged_questions,
                document_text=document_text,
                model=model,
                max_tokens=max_tokens,
                api_key=active_settings.gemini_api_key,
            )
        )
    except Exception as exc:
        return error_result(
            f"parallel extraction failed: {exc}",
            "verify the input source, question list, Gemini API key, and model name, then retry",
            ["`extract-many --file apple-10k.md \"Revenue by segment\" \"Key risks\"`", "`extract \"What is the revenue by segment?\" --file apple-10k.md`"],
            start,
        )
    output = "\n\n".join(f"## {question}\n{answer.strip()}" for question, answer in zip(merged_questions, answers, strict=False))
    return CommandResult.from_text(output, duration_ms=elapsed_ms(start))


@app.callback()
def extract_cli_command(
    ctx: typer.Context,
    question: str | None = typer.Argument(None, help="Question to answer about the input document."),
    file_path: str | None = typer.Option(None, "--file", help="Path to a text file. Omit to read from stdin."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Gemini model to use."),
    max_tokens: int = typer.Option(4096, "--max-tokens", help="Maximum response tokens."),
) -> None:
    """Ask one focused question about input text.

    Example:
      minerva extract "What is the revenue by segment?" --file apple-10k.md
    """
    stdin = typer.get_binary_stream("stdin").read()
    if not question:
        abort_with_help(
            ctx,
            what_went_wrong="no extraction question was provided",
            what_to_do="pass a question and either `--file PATH` or piped stdin",
            alternatives=["`minerva extract \"What is the revenue by segment?\" --file apple-10k.md`", "`minerva extract-many --file apple-10k.md \"Revenue by segment\" \"Key risks\"`"],
        )
    if not file_path and not stdin:
        abort_with_help(
            ctx,
            what_went_wrong="no input document was provided for `extract`",
            what_to_do="pass `--file PATH` or pipe text into the command",
            alternatives=["`minerva extract \"What is the revenue by segment?\" --file apple-10k.md`", "`minerva run \"sec 10k AAPL --items 7 | extract 'Revenue by segment'\"`"],
        )
    _print(extract_command(question=question, file_path=file_path, model=model, max_tokens=max_tokens, stdin=stdin))


@extract_many_app.callback()
def extract_many_cli_command(
    ctx: typer.Context,
    questions: list[str] = typer.Argument(None, help="One or more questions."),
    file_path: str | None = typer.Option(None, "--file", help="Path to a text file. Omit to read from stdin."),
    questions_file: str | None = typer.Option(None, "--questions-file", help="Path to a file with one question per line."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Gemini model to use."),
    max_tokens: int = typer.Option(4096, "--max-tokens", help="Maximum response tokens per answer."),
) -> None:
    """Ask multiple questions about the same document concurrently.

    Example:
      minerva extract-many --file apple-10k.md "Revenue by segment" "Key risk factors"
    """
    stdin = typer.get_binary_stream("stdin").read()
    if not questions and not questions_file:
        abort_with_help(
            ctx,
            what_went_wrong="no extraction questions were provided",
            what_to_do="pass question arguments, `--questions-file`, or both",
            alternatives=["`minerva extract extract-many --file apple-10k.md \"Revenue by segment\" \"Key risks\"`", "`minerva extract \"What is the revenue by segment?\" --file apple-10k.md`"],
        )
    if not file_path and not stdin:
        abort_with_help(
            ctx,
            what_went_wrong="no input document was provided for `extract-many`",
            what_to_do="pass `--file PATH` or pipe text into the command",
            alternatives=["`minerva extract extract-many --file apple-10k.md \"Revenue by segment\" \"Key risks\"`", "`minerva run \"sec 10k AAPL --items 7 | extract-many 'Revenue by segment' 'Key risks'\"`"],
        )
    _print(
        extract_many_command(
            questions=questions,
            file_path=file_path,
            questions_file=questions_file,
            model=model,
            max_tokens=max_tokens,
            stdin=stdin,
        )
    )


def _generate_answer(*, question: str, document_text: str, model: str, max_tokens: int, api_key: str) -> str:
    try:
        from google import genai
    except ModuleNotFoundError as exc:
        raise RuntimeError("google-genai is not installed") from exc
    client = genai.Client(api_key=api_key)
    prompt_text = f"{SYSTEM_PROMPT}\n\nQuestion: {question}\n\nDocument:\n{document_text}"
    response = client.models.generate_content(model=model, contents=prompt_text, config={"max_output_tokens": max_tokens})
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Gemini returned an empty response")
    return str(text)


async def _gather_answers(
    *,
    questions: list[str],
    document_text: str,
    model: str,
    max_tokens: int,
    api_key: str,
) -> list[str]:
    semaphore = asyncio.Semaphore(max(len(questions), 1))

    async def _run(question: str) -> str:
        async with semaphore:
            return await asyncio.to_thread(
                _generate_answer,
                question=question,
                document_text=document_text,
                model=model,
                max_tokens=max_tokens,
                api_key=api_key,
            )

    return list(await asyncio.gather(*[_run(question) for question in questions]))


def _merge_questions(questions: list[str], questions_file: str | None) -> list[str]:
    merged = [question.strip() for question in questions if question.strip()]
    if questions_file:
        merged.extend(
            question.strip()
            for question in Path(questions_file).expanduser().read_text(encoding="utf-8").splitlines()
            if question.strip()
        )
    return merged


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
