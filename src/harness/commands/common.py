"""Shared helpers for harness command groups."""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

import httpx
import pandas as pd
from anthropic import APIStatusError, APITimeoutError

from harness.output import CommandResult
from minerva.formatting import build_markdown_table

T = TypeVar("T")
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


def elapsed_ms(start: float) -> int:
    """Convert a perf counter start time into a non-negative millisecond duration."""
    return max(0, int((time.perf_counter() - start) * 1000))


def error_result(message: str, start: float) -> CommandResult:
    """Build a standard error result with duration metadata."""
    return CommandResult.from_text("", stderr=message, exit_code=1, duration_ms=elapsed_ms(start))


def dataframe_to_markdown(df: pd.DataFrame, *, max_rows: int = 20) -> str:
    """Render a dataframe as a markdown table without extra dependencies."""
    if df.empty:
        return "(no rows)"

    preview: pd.DataFrame = df.head(max_rows).copy()
    headers: list[str] = [str(column) for column in preview.columns]
    rows: list[list[str]] = []
    for _, row in preview.iterrows():
        rows.append([_format_cell(value) for value in row.tolist()])

    table: str = build_markdown_table(headers, rows, alignment=["l"] * len(headers))
    if len(df) > max_rows:
        table += f"\n\nShowing {max_rows} of {len(df)} rows."
    return table


def relative_display_path(path: Path, root: Path) -> str:
    """Return a workspace-relative path when possible."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


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
    if isinstance(exc, httpx.TimeoutException):
        return True

    status_code: int | None = _extract_status_code(exc)
    if status_code is None:
        return False
    if status_code in {400, 401, 403}:
        return False
    return status_code in RETRYABLE_STATUS_CODES


def should_retry_anthropic_error(exc: Exception) -> bool:
    """Retry Anthropic calls on timeout and transient status codes only."""
    if isinstance(exc, APITimeoutError):
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
    if should_retry_http_error(exc):
        return True
    if should_retry_anthropic_error(exc):
        return True

    status_code: int | None = _extract_status_code(exc)
    if status_code is None:
        return False
    if status_code in {400, 401, 403}:
        return False
    return status_code in RETRYABLE_STATUS_CODES


def _extract_status_code(exc: Exception) -> int | None:
    if isinstance(exc, APIStatusError):
        return getattr(exc, "status_code", None)

    status_code: object = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response: object = getattr(exc, "response", None)
    response_status: object = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status

    return None


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)
