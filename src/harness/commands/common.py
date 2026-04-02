"""Shared helpers for harness command groups."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import pandas as pd

from harness.output import CommandResult
from minerva.formatting import build_markdown_table


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


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)
