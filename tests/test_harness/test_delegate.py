"""Tests for delegated document reading helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from harness import delegate


def test_extract_text_from_path_reads_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "memo.txt"
    path.write_text("Plain text document", encoding="utf-8")

    assert delegate.extract_text_from_path(path) == "Plain text document"


def test_extract_text_from_path_extracts_html_content(tmp_path: Path) -> None:
    path = tmp_path / "memo.html"
    path.write_text(
        (
            "<html><head><title>Quarterly Update</title><script>ignore()</script></head>"
            "<body><h1>Highlights</h1><p>Revenue accelerated.</p><li>Margin expanded.</li></body></html>"
        ),
        encoding="utf-8",
    )

    text = delegate.extract_text_from_path(path)

    assert text.startswith("Quarterly Update")
    assert "Highlights" in text
    assert "Revenue accelerated." in text
    assert "Margin expanded." in text
    assert "ignore()" not in text


def test_extract_text_from_path_extracts_pdf_pages(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "memo.pdf"
    path.write_bytes(b"%PDF-1.4")

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePDF:
        def __enter__(self) -> "_FakePDF":
            self.pages = [_FakePage("First page"), _FakePage(""), _FakePage("Second page")]
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(delegate.pdfplumber, "open", lambda candidate: _FakePDF())

    text = delegate.extract_text_from_path(path)

    assert "[Page 1]\nFirst page" in text
    assert "[Page 3]\nSecond page" in text
    assert "[Page 2]" not in text


def test_rank_chunks_prioritizes_question_keywords() -> None:
    chunks = [
        "General company history.",
        "Gross margin expanded and margin leverage improved.",
        "Hiring plans stayed flat.",
    ]

    ranked = delegate._rank_chunks(chunks, "What changed in margin?")

    assert ranked[0] == chunks[1]


def test_build_delegate_context_chunks_and_applies_token_budget(monkeypatch) -> None:
    chunks = [
        "Company overview and history.",
        "Gross margin expanded due to pricing and margin discipline.",
        "Operating margin also improved with margin leverage.",
    ]
    document_text = "\n\n".join(chunks)
    token_map = {document_text: 50, chunks[0]: 4, chunks[1]: 4, chunks[2]: 4}

    monkeypatch.setattr(delegate, "estimate_tokens", lambda text: token_map[text])
    monkeypatch.setattr(delegate, "_chunk_text", lambda text, target_tokens=delegate.TARGET_CHUNK_TOKENS: chunks)

    context = delegate.build_delegate_context(document_text, "How did margin change?", max_tokens=8)

    assert chunks[0] not in context
    assert chunks[1] in context
    assert chunks[2] in context


def test_delegate_read_uses_ranked_context_and_returns_llm_text(monkeypatch) -> None:
    client_holder: dict[str, object] = {}

    class _FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="Key point"),
                    SimpleNamespace(type="text", text="Cited detail"),
                ]
            )

    class _FakeAsyncAnthropic:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.messages = _FakeMessages()
            client_holder["client"] = self

    monkeypatch.setattr(delegate, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setattr(delegate, "build_delegate_context", lambda document_text, question: "ranked context")

    answer = asyncio.run(
        delegate.delegate_read(
            "very long document",
            "What changed?",
            api_key="test-key",
            model="test-model",
        )
    )
    client = client_holder["client"]
    call = client.messages.calls[0]

    assert answer == "Key point\nCited detail"
    assert call["model"] == "test-model"
    assert "What changed?" in call["system"]
    assert "ranked context" in call["messages"][0]["content"]
