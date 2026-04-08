"""Delegated document reading via Anthropic."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pdfplumber
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup

from harness.commands.common import async_retry_call, should_retry_anthropic_error
from harness.context import estimate_tokens

MAX_DELEGATE_TOKENS: int = 100_000
TARGET_CHUNK_TOKENS: int = 7_500


def extract_text_from_path(path: Path) -> str:
    """Extract readable text from a PDF, HTML, or plain-text document."""
    suffix: str = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    if suffix in {".html", ".htm"}:
        return _extract_html_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def build_delegate_context(document_text: str, question: str, max_tokens: int = MAX_DELEGATE_TOKENS) -> str:
    """Select the full document or the most relevant chunks under a token budget."""
    if estimate_tokens(document_text) <= max_tokens:
        return document_text

    chunks: list[str] = _chunk_text(document_text)
    ranked_chunks: list[str] = _rank_chunks(chunks, question)
    selected: list[str] = []
    total_tokens: int = 0

    for chunk in ranked_chunks:
        chunk_tokens: int = estimate_tokens(chunk)
        if selected and total_tokens + chunk_tokens > max_tokens:
            continue
        if not selected and chunk_tokens > max_tokens:
            return chunk[: max_tokens * 4]
        selected.append(chunk)
        total_tokens += chunk_tokens
        if total_tokens >= max_tokens:
            break

    if not selected:
        return document_text[: max_tokens * 4]

    selected_set: set[str] = set(selected)
    ordered: list[str] = [chunk for chunk in chunks if chunk in selected_set]
    return "\n\n".join(ordered)


async def delegate_read(
    document_text: str,
    question: str,
    *,
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> str:
    """Ask Anthropic to extract question-relevant details from a document."""
    resolved_api_key: str | None = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not resolved_api_key:
        raise ValueError(
            "Missing ANTHROPIC_API_KEY.\n"
            "What to do instead: export ANTHROPIC_API_KEY before using delegated reads.\n"
            "Available alternatives: `cat <file>`, `knowledge search <query>`"
        )

    client = AsyncAnthropic(api_key=resolved_api_key)
    context: str = build_delegate_context(document_text, question)
    response = await async_retry_call(
        lambda: client.messages.create(
            model=model,
            max_tokens=1_000,
            system=(
                f"Extract information relevant to: {question}. "
                "Be concise and specific. Cite page/section numbers when possible."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Question:\n"
                        f"{question}\n\n"
                        "Document:\n"
                        f"{context}"
                    ),
                }
            ],
        ),
        should_retry=should_retry_anthropic_error,
    )
    text_blocks: list[str] = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "\n".join(part.strip() for part in text_blocks if part.strip()).strip()


async def delegate_read_many(
    document_text: str,
    questions: list[str],
    *,
    parallel: int = 4,
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> list[str]:
    """Run multiple delegated reads against the same document concurrently."""
    semaphore = asyncio.Semaphore(max(1, parallel))

    async def _run(question: str) -> str:
        async with semaphore:
            return await delegate_read(document_text, question, api_key=api_key, model=model)

    return await asyncio.gather(*[_run(question) for question in questions])


def _extract_pdf_text(path: Path) -> str:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text: str = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {index}]\n{text.strip()}")
    return "\n\n".join(pages).strip()


def _extract_html_text(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title: str = soup.title.get_text(" ", strip=True) if soup.title else path.name
    parts: list[str] = []
    for node in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        text: str = node.get_text(" ", strip=True)
        if text:
            parts.append(text)
    if not parts:
        parts.append(soup.get_text("\n", strip=True))
    return f"{title}\n\n" + "\n".join(parts).strip()


def _chunk_text(text: str, target_tokens: int = TARGET_CHUNK_TOKENS) -> list[str]:
    chars_per_chunk: int = target_tokens * 4
    paragraphs: list[str] = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len: int = 0

    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        paragraph_len: int = len(paragraph)
        if current and current_len + paragraph_len > chars_per_chunk:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = paragraph_len
            continue
        current.append(paragraph)
        current_len += paragraph_len

    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def _rank_chunks(chunks: list[str], question: str) -> list[str]:
    keywords: set[str] = {token for token in re.findall(r"[a-zA-Z0-9]{3,}", question.lower())}
    if not keywords:
        return chunks

    scored: list[tuple[int, int, str]] = []
    for index, chunk in enumerate(chunks):
        lowered: str = chunk.lower()
        score: int = sum(lowered.count(keyword) for keyword in keywords)
        scored.append((score, -index, chunk))

    ranked: list[str] = [chunk for _, _, chunk in sorted(scored, reverse=True)]
    return ranked
