"""LLM extraction commands backed by Gemini or OpenAI."""

from __future__ import annotations

import asyncio
import glob as _glob
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from harness.commands.common import (
    abort_with_help,
    elapsed_ms,
    error_result,
    show_help_if_bare,
    resolve_path,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

EXTRACT_HELP = (
    "LLM-powered information extraction from large text documents.\n\n"
    "Examples:\n"
    "  minerva extract -f apple-10k.md \"What is the revenue by segment?\"\n"
    "  minerva extract -q questions.md -f apple-10k.md\n"
    "  minerva run \"sec 10k AAPL --items 1A | extract 'What are the top 3 risk factors?'\"\n"
)

EXTRACT_FILES_HELP = (
    "Apply one extraction prompt or question pack across many UTF-8 text/markdown files.\n\n"
    "Examples:\n"
    "  minerva extract-files \\\n"
    "    -f 'data/sources/**/*.md' -o data/extractions/churn \\\n"
    "    \"What does management say about churn?\"\n"
    "  minerva extract-files -q questions.md \\\n"
    "    -f oracle/income.md -f microsoft/q3-call.md \\\n"
    "    -f amazon/q1-call.md -o data/extractions/cross-company\n"
    "  minerva extract-files -q questions.md -F selected-files.txt \\\n"
    "    -o data/extractions/summary\n"
    "  minerva extract-files --questions-file questions.md \\\n"
    "    --files 'data/sources/**/*.md' --out data/extractions/summary \\\n"
    "    --model gemini-3-flash --thinking minimal --concurrency 4\n"
    "  minerva extract-files -q questions.md -f 'data/**/*.md' -o out \\\n"
    "    --model gpt-5.5 --concurrency 2\n"
)

DEFAULT_MODEL = "gemini-3-flash"
DEFAULT_MAX_TOKENS = 16384
DEFAULT_CONCURRENCY = 4
MODEL_ALIASES: dict[str, str] = {
    # OpenClaw/user-facing shorthand; Google GenAI expects the preview model id today.
    "gemini-3-flash": "gemini-3-flash-preview",
    # Accept provider-qualified OpenClaw-style names while sending OpenAI its model id.
    "openai/gpt-5.5": "gpt-5.5",
    "openai/gpt-5.4": "gpt-5.4",
}
UNSUPPORTED_TEXT_EXTRACTION_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".zip",
        ".gz",
        ".tar",
    }
)

SYSTEM_PROMPT = (
    "Extract information relevant to the prompt below. Be concise and specific. "
    "Cite section/page numbers when possible. If the prompt contains multiple "
    "questions, answer each under a clearly labeled markdown heading."
)

VALID_THINKING_LEVELS: frozenset[str] = frozenset({"off", "minimal", "low", "medium", "high", "adaptive"})

app = typer.Typer(help=EXTRACT_HELP, no_args_is_help=False, invoke_without_command=True)
extract_files_app = typer.Typer(help=EXTRACT_FILES_HELP, no_args_is_help=False, invoke_without_command=True)
# ---------------------------------------------------------------------------
# `extract`
# ---------------------------------------------------------------------------
def dispatch(args: list[str], settings: HarnessSettings, stdin: bytes = b"") -> CommandResult:
    """Dispatch the `extract` command for `minerva run`."""
    
    try:
        parsed = _parse_extract_args(args)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)
    return extract_command(
        question=parsed.question,
        questions_file=parsed.questions_file,
        file_path=parsed.file_path,
        model=parsed.model,
        max_tokens=parsed.max_tokens,
        thinking=parsed.thinking,
        stdin=stdin,
        settings=settings,
    )
def extract_command(
    *,
    question: str | None = None,
    questions_file: str | None = None,
    file_path: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    thinking: str | None = None,
    stdin: bytes = b"",
    settings: HarnessSettings,
) -> CommandResult:
    start = time.perf_counter()
    
    api_key = _api_key_for_model(settings, model)
    if not api_key:
        return _missing_api_key_result(model, start)
    try:
        prompt_pack = _build_prompt_pack(question=question, questions_file=questions_file)
        document_text = _read_document_text(file_path=file_path, stdin=stdin)
        resolved_thinking = _resolve_default_thinking(model, thinking)
        # Validate thinking config before any network call.
        _build_thinking_config(model, resolved_thinking)
        prompt = _compose_prompt(prompt_pack=prompt_pack, document_text=document_text)
        answer = _generate_answer(
            prompt=prompt,
            document_text=document_text,
            model=model,
            max_tokens=max_tokens,
            thinking=resolved_thinking,
            api_key=api_key,
        )
    except _UsageError as exc:
        return error_result(
            exc.what,
            exc.what_to_do,
            exc.alternatives,
            start,
        )
    except ValueError as exc:
        return error_result(
            f"invalid extraction configuration: {exc}",
            "use a supported model/thinking combination, or omit `--thinking`",
            ["`--thinking minimal` for gemini-3-*", "`--thinking adaptive` for gemini-2.5-*"],
            start,
        )
    except Exception as exc:  # noqa: BLE001
        return error_result(
            f"extraction failed: {exc}",
            "verify the input source, API key, and model name, then retry",
            [
                "`extract \"What is the revenue by segment?\" --file apple-10k.md`",
                "`extract --questions-file questions.md --file apple-10k.md`",
            ],
            start,
        )
    return CommandResult.from_text(answer.strip(), duration_ms=elapsed_ms(start))
@app.callback()
def extract_cli_command(
    ctx: typer.Context,
    question: str | None = typer.Argument(None, help="Question or prompt to apply to the input document."),
    file_path: str | None = typer.Option(None, "--file", "-f", help="Path to a text file. Omit to read from stdin."),
    questions_file: str | None = typer.Option(
        None,
        "--questions-file",
        "-q",
        help="Markdown file containing the question/prompt pack to apply to the input document.",
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Model to use (Gemini or OpenAI)."),
    max_tokens: int = typer.Option(DEFAULT_MAX_TOKENS, "--max-tokens", help="Maximum output tokens."),
    thinking: str | None = typer.Option(
        None,
        "--thinking",
        help="Thinking level: off|minimal|low|medium|high|adaptive (model-aware).",
    ),
) -> None:
    """Run a single extraction call against an input document.

    Example:
      minerva extract "What is the revenue by segment?" --file apple-10k.md
      minerva extract --questions-file questions.md --file apple-10k.md
    """
    show_help_if_bare(ctx, question=question, file_path=file_path, questions_file=questions_file)
    if not question and not questions_file:
        abort_with_help(
            ctx,
            what_went_wrong="no extraction prompt was provided",
            what_to_do="pass a positional question, `--questions-file PATH`, or both",
            alternatives=[
                "`minerva extract \"What is the revenue by segment?\" --file apple-10k.md`",
                "`minerva extract --questions-file questions.md --file apple-10k.md`",
            ],
        )
    stdin = b"" if file_path else typer.get_binary_stream("stdin").read()
    if not file_path and not stdin:
        abort_with_help(
            ctx,
            what_went_wrong="no input document was provided for `extract`",
            what_to_do="pass `--file PATH` or pipe text into the command",
            alternatives=[
                "`minerva extract \"What is the revenue by segment?\" --file apple-10k.md`",
                "`minerva run \"sec 10k AAPL --items 7 | extract 'Revenue by segment'\"`",
            ],
        )
    settings = get_settings()
    _print(
        extract_command(
            question=question,
            questions_file=questions_file,
            file_path=file_path,
            model=model,
            max_tokens=max_tokens,
            thinking=thinking,
            stdin=stdin,
            settings=settings,
        )
    )
# ---------------------------------------------------------------------------
# `extract-files`
# ---------------------------------------------------------------------------
def dispatch_files(args: list[str], settings: HarnessSettings, stdin: bytes = b"") -> CommandResult:
    """Dispatch the `extract-files` command for `minerva run`."""
    
    try:
        parsed = _parse_extract_files_args(args)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)
    return extract_files_command(
        question=parsed.question,
        questions_file=parsed.questions_file,
        files=parsed.files,
        files_from=parsed.files_from,
        out=parsed.out,
        model=parsed.model,
        max_tokens=parsed.max_tokens,
        thinking=parsed.thinking,
        concurrency=parsed.concurrency,
        force=parsed.force,
        settings=settings,
    )
def extract_files_command(
    *,
    question: str | None = None,
    questions_file: str | None = None,
    files: list[str] | None = None,
    files_from: str | None = None,
    out: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    thinking: str | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    force: bool = False,
    settings: HarnessSettings,
) -> CommandResult:
    start = time.perf_counter()
    
    api_key = _api_key_for_model(settings, model)
    if not api_key:
        return _missing_api_key_result(model, start)
    if not out:
        return error_result(
            "no output directory was provided",
            "pass `--out DIR` so per-file extractions are written somewhere durable",
            ["`extract-files \"Q\" --files 'data/**/*.md' --out data/extractions/q`"],
            start,
        )
    try:
        prompt_pack = _build_prompt_pack(question=question, questions_file=questions_file)
    except _UsageError as exc:
        return error_result(exc.what, exc.what_to_do, exc.alternatives, start)

    if not files and not files_from:
        return error_result(
            "no input files were provided",
            "pass one or more `--files PATH_OR_GLOB` values or `--files-from LIST`",
            [
                "`extract-files \"Q\" --files data/sources/a.md --out out/`",
                "`extract-files \"Q\" --files-from files.txt --out out/`",
            ],
            start,
        )

    try:
        resolved_files = _expand_file_inputs(files or [], files_from=files_from)
    except _UsageError as exc:
        return error_result(exc.what, exc.what_to_do, exc.alternatives, start)

    resolved_thinking = _resolve_default_thinking(model, thinking)
    try:
        _build_thinking_config(model, resolved_thinking)
    except ValueError as exc:
        return error_result(
            f"invalid thinking config: {exc}",
            "use a thinking level supported by the selected model, or omit `--thinking`",
            ["`--thinking minimal` for gemini-3-*", "`--thinking adaptive` for gemini-2.5-*"],
            start,
        )

    if concurrency < 1:
        return error_result(
            f"--concurrency must be >= 1 (got {concurrency})",
            "pass `--concurrency` >= 1",
            ["`--concurrency 4`"],
            start,
        )

    out_root = resolve_path(out)
    out_root.mkdir(parents=True, exist_ok=True)

    # Plan output paths (mirroring relative paths under common parent).
    plan = _plan_output_paths(resolved_files, out_root)

    # Pre-check overwrite when not --force.
    if not force:
        collisions = [str(target) for _, target in plan if target.exists()]
        if collisions:
            preview = ", ".join(collisions[:3])
            return error_result(
                f"{len(collisions)} output file(s) already exist (e.g. {preview})",
                "pass `--force` to overwrite existing outputs, or choose a different `--out`",
                ["`--force`", "`--out <fresh-dir>`"],
                start,
            )

    entries: list[dict[str, Any]] = asyncio.run(
        _run_extractions(
            plan=plan,
            prompt_pack=prompt_pack,
            model=model,
            max_tokens=max_tokens,
            thinking=resolved_thinking,
            api_key=api_key,
            concurrency=concurrency,
        )
    )

    manifest = {
        "model": model,
        "api_model": _api_model_name(model),
        "thinking": resolved_thinking,
        "max_tokens": max_tokens,
        "questions_file": str(resolve_path(questions_file)) if questions_file else None,
        "question": question,
        "out": str(out_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    failures = [entry for entry in entries if entry["status"] != "ok"]
    summary_lines = [
        f"wrote {len(entries) - len(failures)} extraction(s) under {out_root}",
        f"manifest: {out_root / 'manifest.json'}",
    ]
    if failures:
        summary_lines.append(f"{len(failures)} extraction(s) failed; see manifest for details.")
        return CommandResult.from_text(
            "\n".join(summary_lines),
            stderr=f"{len(failures)} extraction(s) failed",
            exit_code=1,
            duration_ms=elapsed_ms(start),
        )
    return CommandResult.from_text("\n".join(summary_lines), duration_ms=elapsed_ms(start))
@extract_files_app.callback()
def extract_files_cli_command(
    ctx: typer.Context,
    question: str | None = typer.Argument(None, help="Question or prompt to apply to each input file."),
    files: list[str] = typer.Option(
        None,
        "--files",
        "-f",
        help="One or more UTF-8 text/markdown source file paths or glob patterns (repeatable).",
    ),
    files_from: str | None = typer.Option(
        None,
        "--files-from",
        "-F",
        help="Newline-delimited file containing source paths or globs; relative entries resolve from the list file's directory.",
    ),
    out: str | None = typer.Option(None, "--out", "-o", help="Output directory for per-file markdown results."),
    questions_file: str | None = typer.Option(
        None,
        "--questions-file",
        "-q",
        help="Markdown file containing the question/prompt pack to apply to each source file.",
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Model to use (Gemini or OpenAI)."),
    max_tokens: int = typer.Option(DEFAULT_MAX_TOKENS, "--max-tokens", help="Maximum output tokens per file."),
    thinking: str | None = typer.Option(
        None,
        "--thinking",
        help="Thinking level: off|minimal|low|medium|high|adaptive (model-aware).",
    ),
    concurrency: int = typer.Option(DEFAULT_CONCURRENCY, "--concurrency", help="Bounded concurrency (>=1)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing output files."),
) -> None:
    """Apply one extraction prompt across many files, writing one markdown output per file."""
    show_help_if_bare(ctx, question=question, files=files, files_from=files_from, questions_file=questions_file, out=out)
    if not question and not questions_file:
        abort_with_help(
            ctx,
            what_went_wrong="no extraction prompt was provided",
            what_to_do="pass a positional question, `--questions-file PATH`, or both",
            alternatives=[
                "`minerva extract-files \"Q\" --files 'data/**/*.md' --out out/`",
                "`minerva extract-files --questions-file questions.md --files data/a.md --out out/`",
            ],
        )
    if not files and not files_from:
        abort_with_help(
            ctx,
            what_went_wrong="no input files were provided",
            what_to_do="pass one or more `--files PATH_OR_GLOB` values or `--files-from LIST`",
            alternatives=["`--files data/a.md --files data/b.md`", "`--files 'data/**/*.md'`", "`--files-from files.txt`"],
        )
    if not out:
        abort_with_help(
            ctx,
            what_went_wrong="no `--out` directory was provided",
            what_to_do="pass `--out DIR` so per-file extractions are written somewhere durable",
            alternatives=["`--out data/extractions/q`"],
        )
    settings = get_settings()
    _print(
        extract_files_command(
            question=question,
            questions_file=questions_file,
            files=list(files or []),
            files_from=files_from,
            out=out,
            model=model,
            max_tokens=max_tokens,
            thinking=thinking,
            concurrency=concurrency,
            force=force,
            settings=settings,
        )
    )
# ---------------------------------------------------------------------------
# Argument parsing helpers (run-chain)
# ---------------------------------------------------------------------------
class _UsageError(Exception):
    def __init__(self, what: str, what_to_do: str, alternatives: list[str]) -> None:
        super().__init__(what)
        self.what = what
        self.what_to_do = what_to_do
        self.alternatives = alternatives
class _ExtractArgs:
    __slots__ = ("question", "questions_file", "file_path", "model", "max_tokens", "thinking")

    def __init__(self) -> None:
        self.question: str | None = None
        self.questions_file: str | None = None
        self.file_path: str | None = None
        self.model: str = DEFAULT_MODEL
        self.max_tokens: int = DEFAULT_MAX_TOKENS
        self.thinking: str | None = None
class _ExtractFilesArgs:
    __slots__ = (
        "question",
        "questions_file",
        "files",
        "files_from",
        "out",
        "model",
        "max_tokens",
        "thinking",
        "concurrency",
        "force",
    )

    def __init__(self) -> None:
        self.question: str | None = None
        self.questions_file: str | None = None
        self.files: list[str] = []
        self.files_from: str | None = None
        self.out: str | None = None
        self.model: str = DEFAULT_MODEL
        self.max_tokens: int = DEFAULT_MAX_TOKENS
        self.thinking: str | None = None
        self.concurrency: int = DEFAULT_CONCURRENCY
        self.force: bool = False
def _parse_extract_args(args: list[str]) -> _ExtractArgs:
    parsed = _ExtractArgs()
    positionals: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--file", "-f"}:
            parsed.file_path = _require_value(args, i, token)
            i += 2
        elif token in {"--questions-file", "-q"}:
            parsed.questions_file = _require_value(args, i, token)
            i += 2
        elif token == "--model":
            parsed.model = _require_value(args, i, token)
            i += 2
        elif token == "--max-tokens":
            parsed.max_tokens = int(_require_value(args, i, token))
            i += 2
        elif token == "--thinking":
            parsed.thinking = _require_value(args, i, token)
            i += 2
        elif token.startswith("--"):
            raise ValueError(f"unknown flag for `extract`: `{token}`")
        else:
            positionals.append(token)
            i += 1
    if len(positionals) > 1:
        raise ValueError(f"too many positional arguments for `extract`: {positionals}")
    if positionals:
        parsed.question = positionals[0]
    return parsed
def _parse_extract_files_args(args: list[str]) -> _ExtractFilesArgs:
    parsed = _ExtractFilesArgs()
    positionals: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--files", "-f"}:
            parsed.files.append(_require_value(args, i, token))
            i += 2
        elif token in {"--files-from", "-F"}:
            parsed.files_from = _require_value(args, i, token)
            i += 2
        elif token in {"--questions-file", "-q"}:
            parsed.questions_file = _require_value(args, i, token)
            i += 2
        elif token in {"--out", "-o"}:
            parsed.out = _require_value(args, i, token)
            i += 2
        elif token == "--model":
            parsed.model = _require_value(args, i, token)
            i += 2
        elif token == "--max-tokens":
            parsed.max_tokens = int(_require_value(args, i, token))
            i += 2
        elif token == "--thinking":
            parsed.thinking = _require_value(args, i, token)
            i += 2
        elif token == "--concurrency":
            parsed.concurrency = int(_require_value(args, i, token))
            i += 2
        elif token == "--force":
            parsed.force = True
            i += 1
        elif token.startswith("--"):
            raise ValueError(f"unknown flag for `extract-files`: `{token}`")
        else:
            positionals.append(token)
            i += 1
    if len(positionals) > 1:
        raise ValueError(f"too many positional arguments for `extract-files`: {positionals}")
    if positionals:
        parsed.question = positionals[0]
    return parsed
def _require_value(args: list[str], index: int, flag: str) -> str:
    if index + 1 >= len(args):
        raise ValueError(f"missing value for flag `{flag}`")
    return args[index + 1]
# ---------------------------------------------------------------------------
# Prompt / input helpers
# ---------------------------------------------------------------------------
def _build_prompt_pack(*, question: str | None, questions_file: str | None) -> str:
    sections: list[str] = []
    if question and question.strip():
        sections.append(question.strip())
    if questions_file:
        path = resolve_path(questions_file)
        if not path.exists():
            raise _UsageError(
                f"questions file not found: {questions_file}",
                "pass an existing path to `--questions-file`",
                ["`--questions-file path/to/questions.md`"],
            )
        raw = path.read_text(encoding="utf-8")
        body = raw.strip("\n")
        body = body.strip()
        if not body:
            raise _UsageError(
                f"questions file is empty: {questions_file}",
                "populate the file with a markdown prompt or question pack",
                ["`--questions-file path/to/questions.md`"],
            )
        sections.append(body)
    if not sections:
        raise _UsageError(
            "no extraction prompt was provided",
            "pass a positional question, `--questions-file PATH`, or both",
            [
                "`extract \"Q\" --file doc.md`",
                "`extract --questions-file questions.md --file doc.md`",
            ],
        )
    if len(sections) == 1:
        return sections[0]
    return "\n\n".join(
        [
            "# Inline question",
            sections[0],
            "",
            "# Question pack",
            sections[1],
        ]
    )
def _read_document_text(*, file_path: str | None, stdin: bytes) -> str:
    if file_path:
        return resolve_path(file_path).read_text(encoding="utf-8")
    if stdin:
        return stdin.decode("utf-8", errors="replace")
    raise _UsageError(
        "no input document was provided",
        "pass `--file PATH` or pipe text into the command",
        ["`--file path/to/doc.md`"],
    )
def _compose_prompt(*, prompt_pack: str, document_text: str) -> str:
    return f"{SYSTEM_PROMPT}\n\nPrompt:\n{prompt_pack}\n\nDocument:\n{document_text}"
# ---------------------------------------------------------------------------
# Thinking config helpers
# ---------------------------------------------------------------------------
def _resolve_default_thinking(model: str, explicit: str | None) -> str | None:
    if explicit is not None:
        return explicit
    if _is_gemini_3_flash(model):
        return "minimal"
    return None
def _build_thinking_config(model: str, thinking: str | None):
    """Return a ThinkingConfig (or None) for the given model.

    Raises ValueError on unsupported (model, level) combinations.
    """
    if thinking is None:
        return None
    if thinking not in VALID_THINKING_LEVELS:
        raise ValueError(
            f"unknown thinking level `{thinking}` (expected one of {sorted(VALID_THINKING_LEVELS)})"
        )

    try:
        from google.genai import types as genai_types
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("google-genai is not installed") from exc

    if _is_gemini_3(model):
        if thinking in {"off", "adaptive"}:
            raise ValueError(
                f"`--thinking {thinking}` is not supported for Gemini 3 models; "
                "use minimal|low|medium|high"
            )
        return genai_types.ThinkingConfig(thinking_level=thinking.upper())

    if _is_gemini_25(model):
        if thinking == "off":
            return genai_types.ThinkingConfig(thinking_budget=0)
        if thinking == "adaptive":
            return genai_types.ThinkingConfig(thinking_budget=-1)
        raise ValueError(
            f"`--thinking {thinking}` is not supported for Gemini 2.5 models; use off|adaptive"
        )

    raise ValueError(
        f"`--thinking` is not configured for model `{model}`; omit `--thinking` to skip thinking config"
    )
def _build_generate_config(model: str, max_tokens: int, thinking: str | None):
    try:
        from google.genai import types as genai_types
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("google-genai is not installed") from exc
    thinking_cfg = _build_thinking_config(model, thinking)
    kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}
    if thinking_cfg is not None:
        kwargs["thinking_config"] = thinking_cfg
    return genai_types.GenerateContentConfig(**kwargs)
def _is_gemini_3(model: str) -> bool:
    return model.startswith("gemini-3")
def _is_gemini_3_flash(model: str) -> bool:
    return model.startswith("gemini-3-flash")
def _is_gemini_25(model: str) -> bool:
    return model.startswith("gemini-2.5")
def _api_model_name(model: str) -> str:
    return MODEL_ALIASES.get(model, model)
def _is_openai_model(model: str) -> bool:
    api_model = _api_model_name(model)
    return model.startswith("openai/") or api_model.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4"))
def _api_key_for_model(settings: HarnessSettings, model: str) -> str | None:
    if _is_openai_model(model):
        return settings.openai_api_key
    return settings.gemini_api_key
def _missing_api_key_result(model: str, start: float) -> CommandResult:
    if _is_openai_model(model):
        return error_result(
            "OPENAI_API_KEY is not set",
            "set OPENAI_API_KEY and retry, or choose a Gemini model with GEMINI_API_KEY configured",
            ["`export OPENAI_API_KEY=...`", "`--model gemini-3-flash`"],
            start,
        )
    return error_result(
        "GEMINI_API_KEY is not set",
        "set GEMINI_API_KEY and retry, or choose an OpenAI model with OPENAI_API_KEY configured",
        ["`export GEMINI_API_KEY=...`", "`--model gpt-5.5`"],
        start,
    )
# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------
def _generate_answer(
    *,
    prompt: str,
    document_text: str,  # kept for tests/observability
    model: str,
    max_tokens: int,
    thinking: str | None,
    api_key: str,
) -> str:
    if _is_openai_model(model):
        return _generate_openai_answer(prompt=prompt, model=model, max_tokens=max_tokens, api_key=api_key)
    return _generate_gemini_answer(
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        thinking=thinking,
        api_key=api_key,
    )
def _generate_gemini_answer(
    *,
    prompt: str,
    model: str,
    max_tokens: int,
    thinking: str | None,
    api_key: str,
) -> str:
    try:
        from google import genai
    except ModuleNotFoundError as exc:
        raise RuntimeError("google-genai is not installed") from exc
    client = genai.Client(api_key=api_key)
    config = _build_generate_config(model, max_tokens, thinking)
    response = client.models.generate_content(model=_api_model_name(model), contents=prompt, config=config)
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Gemini returned an empty response")
    return str(text)
def _generate_openai_answer(*, prompt: str, model: str, max_tokens: int, api_key: str) -> str:
    try:
        import openai
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("openai is not installed") from exc

    client = openai.OpenAI(api_key=api_key)
    response = client.responses.create(
        model=_api_model_name(model),
        input=prompt,
        max_output_tokens=max_tokens,
    )
    text = _openai_response_text(response)
    if not text:
        raise ValueError("OpenAI returned an empty response")
    return text
def _openai_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
            elif isinstance(content, dict) and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts)
# ---------------------------------------------------------------------------
# extract-files internals
# ---------------------------------------------------------------------------
def _expand_file_inputs(patterns: list[str], *, files_from: str | None = None) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    inputs: list[tuple[str, Path | None]] = [(raw, None) for raw in patterns]
    if files_from:
        inputs.extend(_read_files_from(files_from))

    for raw, base_dir in inputs:
        candidate = Path(raw).expanduser()
        if base_dir is not None and not candidate.is_absolute():
            candidate = base_dir / candidate
        expanded_raw = str(candidate)
        matches: list[str]
        if any(ch in raw for ch in ["*", "?", "["]):
            matches = sorted(_glob.glob(expanded_raw, recursive=True))
            if not matches:
                raise _UsageError(
                    f"no files matched pattern `{raw}`",
                    "verify the path or glob pattern; quote the value to prevent shell expansion",
                    ["`--files 'data/**/*.md'`"],
                )
        else:
            matches = [expanded_raw]
        for match in matches:
            path = Path(match).resolve()
            if path.is_dir():
                continue
            if not path.exists():
                raise _UsageError(
                    f"file does not exist: {match}",
                    "pass paths or globs that match real files",
                    ["`--files 'data/**/*.md'`"],
                )
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
    if not ordered:
        raise _UsageError(
            "no files matched the provided `--files` values",
            "pass one or more `--files PATH_OR_GLOB` values that match real files",
            ["`--files data/a.md`", "`--files 'data/**/*.md'`"],
        )
    return sorted(ordered)
def _read_files_from(files_from: str) -> list[tuple[str, Path | None]]:
    path = resolve_path(files_from)
    if not path.exists():
        raise _UsageError(
            f"files list not found: {files_from}",
            "pass an existing newline-delimited file to `--files-from`",
            ["`--files-from path/to/files.txt`"],
        )
    base_dir = path.parent
    entries: list[tuple[str, Path | None]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        entries.append((raw, base_dir))
    if not entries:
        raise _UsageError(
            f"files list is empty: {files_from}",
            "add one path or glob per line",
            ["`--files-from path/to/files.txt`"],
        )
    return entries
def _read_extraction_text(path: Path) -> str:
    if path.suffix.lower() in UNSUPPORTED_TEXT_EXTRACTION_EXTENSIONS:
        raise ValueError(
            f"unsupported non-text file type `{path.suffix}`; convert to text first or use the OpenClaw pdf/image tools"
        )
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("file appears to be binary; convert to UTF-8 text before using extract-files")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8 text; convert it before using extract-files") from exc
def _plan_output_paths(files: list[Path], out_root: Path) -> list[tuple[Path, Path]]:
    common = _common_parent(files)
    used: set[Path] = set()
    plan: list[tuple[Path, Path]] = []
    for src in files:
        try:
            rel = src.relative_to(common)
        except ValueError:
            rel = Path(src.name)
        target = (out_root / rel).with_suffix(".md")
        if target in used:
            digest = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:8]
            target = target.with_name(f"{target.stem}-{digest}{target.suffix}")
        used.add(target)
        plan.append((src, target))
    return plan
def _common_parent(files: list[Path]) -> Path:
    if not files:
        return Path(".")
    if len(files) == 1:
        return files[0].parent
    parts_lists = [p.parts for p in files]
    common: list[str] = []
    for tuples in zip(*parts_lists):
        if all(part == tuples[0] for part in tuples):
            common.append(tuples[0])
        else:
            break
    if not common:
        return Path(files[0].anchor or ".")
    return Path(*common)
async def _run_extractions(
    *,
    plan: list[tuple[Path, Path]],
    prompt_pack: str,
    model: str,
    max_tokens: int,
    thinking: str | None,
    api_key: str,
    concurrency: int,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _run_one(src: Path, target: Path) -> dict[str, Any]:
        async with semaphore:
            entry: dict[str, Any] = {
                "source": str(src),
                "output": str(target),
                "status": "ok",
                "error": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                document_text = _read_extraction_text(src)
                prompt = _compose_prompt(prompt_pack=prompt_pack, document_text=document_text)
                answer = await asyncio.to_thread(
                    _generate_answer,
                    prompt=prompt,
                    document_text=document_text,
                    model=model,
                    max_tokens=max_tokens,
                    thinking=thinking,
                    api_key=api_key,
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(answer.strip() + "\n", encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                entry["status"] = "error"
                entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["finished_at"] = datetime.now(timezone.utc).isoformat()
            return entry

    return list(
        await asyncio.gather(*[_run_one(src, target) for src, target in plan])
    )
# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
