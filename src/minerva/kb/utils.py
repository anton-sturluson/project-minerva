"""Utility functions for the Knowledge Base."""

import uuid
import re
from typing import List
from .models import Section


def generate_id() -> str:
    """Generate a unique section ID."""
    return str(uuid.uuid4())


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks for better embeddings."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at sentence boundary
        if end < len(text):
            last_period = chunk.rfind(".")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)
            if break_point > chunk_size // 2:
                chunk = chunk[: break_point + 1]
                end = start + break_point + 1

        chunks.append(chunk.strip())
        start = end - overlap

    return chunks


def build_section_path(section: Section, all_sections: List[Section]) -> str:
    """Build numeric path like '1.2.3' for a section."""
    path_parts = []
    current = section

    # Build path from current to root
    while current:
        siblings = [s for s in all_sections if s.parent_id == current.parent_id]
        siblings.sort(key=lambda s: s.order)

        position = next(
            (
                i + 1
                for i, s in enumerate(siblings)
                if s.section_id == current.section_id
            ),
            0,
        )
        path_parts.insert(0, str(position))

        if current.parent_id:
            current = next(
                (s for s in all_sections if s.section_id == current.parent_id), None
            )
        else:
            current = None

    return ".".join(path_parts)


def format_section_tree(sections: List[Section], indent: str = "  ") -> str:
    """Format sections as an indented tree structure."""
    lines = []

    def format_section(section: Section, all_sections: List[Section], depth: int = 0):
        path = build_section_path(section, all_sections)
        prefix = indent * depth
        lines.append(f"{prefix}{path}. {section.header}")

        content_lines = section.content.split("\n")
        for line in content_lines:
            if line.strip():
                lines.append(f"{prefix}{indent}{line}")

        # Add children
        children = [s for s in all_sections if s.parent_id == section.section_id]
        children.sort(key=lambda s: s.order)
        for child in children:
            format_section(child, all_sections, depth + 1)

    # Start with root sections
    roots = [s for s in sections if s.parent_id is None]
    roots.sort(key=lambda s: s.order)
    for root in roots:
        format_section(root, sections)

    return "\n".join(lines)
