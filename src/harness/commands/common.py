"""Shared helpers for harness command groups."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

import typer

from harness.output import CommandResult

T = TypeVar("T")
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


def elapsed_ms(start: float) -> int:
    """Convert a perf counter start time into a non-negative millisecond duration."""
    return max(0, int((time.perf_counter() - start) * 1000))


def format_error(
    what_went_wrong: str,
    what_to_do: str,
    alternatives: list[str] | tuple[str, ...],
    *,
    help_text: str | None = None,
) -> str:
    """Build a standard structured error message."""
    lines: list[str] = [
        f"What went wrong: {what_went_wrong}",
        f"What to do instead: {what_to_do}",
        f"Available alternatives: {', '.join(alternatives) if alternatives else '(none)'}",
    ]
    if help_text:
        lines.extend(["", help_text.rstrip()])
    return "\n".join(lines)


def error_result(
    what_went_wrong: str,
    what_to_do: str,
    alternatives: list[str] | tuple[str, ...],
    start: float,
    *,
    help_text: str | None = None,
) -> CommandResult:
    """Build a standard error result with duration metadata."""
    return CommandResult.from_text(
        "",
        stderr=format_error(what_went_wrong, what_to_do, alternatives, help_text=help_text),
        exit_code=1,
        duration_ms=elapsed_ms(start),
    )


def _is_bare_default(v: object) -> bool:
    """True only for None or empty list/tuple — the values Typer uses for unprovided args.

    Deliberately narrow: does NOT treat False, 0, or "" as bare.
    Typer passes None for unprovided Optional args and None for unprovided list options.
    """
    if v is None:
        return True
    if isinstance(v, (list, tuple)) and len(v) == 0:
        return True
    return False


def show_help_if_bare(ctx: typer.Context, **kwargs: object) -> None:
    """If every kwarg is an unprovided default (None or empty collection), print help and exit 0.

    Call as the first line of a Typer callback to give bare invocations clean help
    instead of an error message.  Pass only user-facing parameters that indicate intent —
    not defaults like model/max_tokens/concurrency that always have values.
    """
    if all(_is_bare_default(v) for v in kwargs.values()):
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def abort_with_help(
    ctx: typer.Context,
    *,
    what_went_wrong: str,
    what_to_do: str,
    alternatives: list[str] | tuple[str, ...],
    exit_code: int = 1,
) -> None:
    """Print a structured error plus command help, then exit."""
    typer.echo(
        format_error(
            what_went_wrong,
            what_to_do,
            alternatives,
            help_text=ctx.get_help(),
        )
    )
    raise typer.Exit(exit_code)


def dataframe_to_markdown(df, *, max_rows: int = 20) -> str:
    """Render a dataframe as a markdown table without extra dependencies."""
    from minerva.formatting import build_markdown_table

    if df.empty:
        return "(no rows)"

    preview = df.head(max_rows).copy()
    headers: list[str] = [str(column) for column in preview.columns]
    rows: list[list[str]] = [[_format_cell(value) for value in row.tolist()] for _, row in preview.iterrows()]
    table: str = build_markdown_table(headers, rows, alignment=["l"] * len(headers))
    if len(df) > max_rows:
        table += f"\n\nShowing {max_rows} of {len(df)} rows."
    return table


def relative_display_path(path: Path, root: Path | None = None) -> str:
    """Return a short path relative to the given root or cwd when possible."""
    reference: Path = root.resolve() if root else Path.cwd().resolve()
    try:
        return str(path.resolve().relative_to(reference))
    except ValueError:
        return str(path.resolve())


def resolve_path(raw_path: str | Path) -> Path:
    """Resolve a path relative to the current working directory."""
    candidate: Path = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def parse_flag_args(args: list[str], *, allow_flags_without_values: set[str] | None = None) -> dict[str, str | bool]:
    """Parse simple `--name value` arguments for `run` dispatch paths."""
    parsed: dict[str, str | bool] = {}
    index: int = 0
    bare_flags: set[str] = allow_flags_without_values or set()
    while index < len(args):
        token = args[index]
        if not token.startswith("--"):
            raise ValueError(
                format_error(
                    "arguments must be passed as `--name value` pairs",
                    "retry with explicit flag names before each value",
                    ["`--help`", "`minerva run \"...\"`"],
                )
            )
        key: str = token.removeprefix("--")
        if key in bare_flags and (index + 1 >= len(args) or args[index + 1].startswith("--")):
            parsed[key] = True
            index += 1
            continue
        if index + 1 >= len(args):
            raise ValueError(
                format_error(
                    f"missing value for flag `{token}`",
                    "supply a value immediately after the flag",
                    ["`--help`", "`minerva run \"...\"`"],
                )
            )
        parsed[key] = args[index + 1]
        index += 2
    return parsed


def parse_csv_floats(raw: str) -> list[float]:
    """Parse a comma-separated list of floats."""
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def read_text_input(*, file_path: str | None = None, stdin: bytes = b"") -> str:
    """Read UTF-8 text from a file or stdin."""
    if file_path:
        return resolve_path(file_path).read_text(encoding="utf-8")
    if stdin:
        return stdin.decode("utf-8", errors="replace")
    raise ValueError("no input provided")


def maybe_export_text(text: str, export_path: str | None) -> str:
    """Write text to a file when requested and return a note for the CLI output."""
    if not export_path:
        return ""
    target: Path = resolve_path(export_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return f"\n\nexported_to: {relative_display_path(target)}"


def retry_call(
    operation: Callable[[], T],
    *,
    should_retry: Callable[[Exception], bool],
    retries: int = 3,
    delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Run a synchronous operation with bounded exponential backoff."""
    attempt: int = 0
    sleep_fn: Callable[[float], None] = time.sleep if sleep is None else sleep
    while True:
        try:
            return operation()
        except Exception as exc:
            if attempt >= retries or not should_retry(exc):
                raise
            sleep_fn(delays[min(attempt, len(delays) - 1)])
            attempt += 1


async def async_retry_call(
    operation: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[Exception], bool],
    retries: int = 3,
    delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """Run an async operation with bounded exponential backoff."""
    attempt: int = 0
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep if sleep is None else sleep
    while True:
        try:
            return await operation()
        except Exception as exc:
            if attempt >= retries or not should_retry(exc):
                raise
            await sleep_fn(delays[min(attempt, len(delays) - 1)])
            attempt += 1


def should_retry_http_error(exc: Exception) -> bool:
    """Retry HTTP operations on timeout and transient status codes only."""
    import httpx

    if isinstance(exc, httpx.TimeoutException):
        return True
    status_code: int | None = _extract_status_code(exc)
    if status_code is None:
        return False
    if status_code in {400, 401, 403}:
        return False
    return status_code in RETRYABLE_STATUS_CODES


def should_retry_network_error(exc: Exception) -> bool:
    """Retry generic network calls when they expose a retryable timeout or status."""
    if isinstance(exc, TimeoutError):
        return True
    return should_retry_http_error(exc)


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)
