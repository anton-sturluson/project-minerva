"""Utility functions for the Knowledge Base."""

import re
import uuid


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for better embeddings."""
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start: int = 0
    while start < len(text):
        end: int = start + chunk_size
        chunk: str = text[start:end]

        # Try to break at sentence boundary
        if end < len(text):
            last_period: int = chunk.rfind(".")
            last_newline: int = chunk.rfind("\n")
            break_point: int = max(last_period, last_newline)
            if break_point > chunk_size // 2:
                chunk = chunk[: break_point + 1]
                end = start + break_point + 1

        chunks.append(chunk.strip())
        start = end - overlap

    return chunks


def split_lines(text: str, min_chars: int = 20) -> list[str]:
    """Split text into lines."""
    return [
        processed
        for line in text.split("\n")
        if len(processed := line.strip()) >= min_chars
    ]
