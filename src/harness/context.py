"""Token budgeting and content-aware truncation helpers."""

from __future__ import annotations

import csv
import io
from typing import Iterable


def estimate_tokens(text: str) -> int:
    """Estimate tokens with a cheap chars/4 heuristic."""
    return max(1, (len(text) + 3) // 4)


def is_binary(data: bytes) -> bool:
    """Heuristically detect binary content."""
    if not data:
        return False
    if b"\x00" in data:
        return True
    try:
        text: str = data.decode("utf-8")
    except UnicodeDecodeError:
        return True

    if not text:
        return False

    suspicious: int = 0
    for char in text:
        codepoint: int = ord(char)
        if codepoint in {9, 10, 13}:
            continue
        if codepoint < 32:
            suspicious += 1

    return (suspicious / max(len(text), 1)) > 0.30


def smart_truncate(text: str, content_type: str) -> str:
    """Return a compact, content-aware preview of large content."""
    normalized: str = content_type.lower()
    if normalized == "csv":
        return _summarize_csv(text)
    return _summarize_large_text(text)


def _summarize_csv(text: str, sample_size: int = 5) -> str:
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = list(reader)
    if not rows:
        return "CSV appears to be empty."

    header: list[str] = rows[0]
    data_rows: list[list[str]] = rows[1:]
    sample: Iterable[list[str]] = data_rows[:sample_size]
    lines: list[str] = [
        "CSV summary:",
        f"Columns: {', '.join(header) if header else '(none)'}",
        f"Row count: {len(data_rows)}",
        "Sample rows:",
    ]
    if not data_rows:
        lines.append("(no data rows)")
    else:
        lines.append(",".join(header))
        for row in sample:
            lines.append(",".join(row))
    return "\n".join(lines)


def _summarize_large_text(text: str, head_lines: int = 40, tail_lines: int = 20) -> str:
    lines: list[str] = text.splitlines()
    if len(lines) <= head_lines + tail_lines:
        return text

    head: list[str] = lines[:head_lines]
    tail: list[str] = lines[-tail_lines:]
    preview: list[str] = [
        f"Large text preview: {len(lines)} total lines.",
        "--- head ---",
        *head,
        "--- tail ---",
        *tail,
    ]
    return "\n".join(preview)
