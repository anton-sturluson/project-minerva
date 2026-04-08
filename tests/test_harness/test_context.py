"""Tests for harness.context helpers."""

from harness.context import estimate_tokens, is_binary, smart_truncate


def test_estimate_tokens_uses_chars_divided_by_four() -> None:
    text: str = "a" * 40
    assert estimate_tokens(text) == 10


def test_is_binary_detects_null_bytes() -> None:
    assert is_binary(b"abc\x00def") is True


def test_is_binary_accepts_plain_utf8_text() -> None:
    assert is_binary("plain text".encode("utf-8")) is False


def test_smart_truncate_summarizes_csv() -> None:
    csv_text: str = "name,value\nalpha,1\nbeta,2\ngamma,3"
    result: str = smart_truncate(csv_text, "csv")
    assert "CSV summary:" in result
    assert "Row count: 3" in result
    assert "name,value" in result


def test_smart_truncate_returns_head_and_tail_for_large_text() -> None:
    text: str = "\n".join(f"line {index}" for index in range(100))
    result: str = smart_truncate(text, "text")
    assert "Large text preview: 100 total lines." in result
    assert "line 0" in result
    assert "line 99" in result
