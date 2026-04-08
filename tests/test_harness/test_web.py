"""Tests for web command helpers."""

from __future__ import annotations

import httpx

from harness.commands import web
from harness.config import HarnessSettings


class _FakeResponse:
    def __init__(self, *, payload=None, text: str = "") -> None:
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_search_web_returns_formatted_results(tmp_path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, brave_api_key="brave-key")
    calls: list[dict[str, object]] = []

    def fake_get(url: str, *, headers: dict[str, str], params: dict[str, object], timeout: float):
        calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return _FakeResponse(
            payload={
                "web": {
                    "results": [
                        {
                            "title": "Result One",
                            "url": "https://example.com/one",
                            "description": "First snippet.",
                        },
                        {
                            "title": "Result Two",
                            "url": "https://example.com/two",
                            "description": "Second snippet.",
                        },
                    ]
                }
            }
        )

    monkeypatch.setattr(web.httpx, "get", fake_get)

    result = web.search_web("vertical software", settings=settings)
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert calls[0]["url"] == "https://api.search.brave.com/res/v1/web/search"
    assert calls[0]["headers"]["X-Subscription-Token"] == "brave-key"
    assert calls[0]["params"] == {"q": "vertical software", "count": 5}
    assert "Result One\nhttps://example.com/one\nFirst snippet." in output
    assert "Result Two\nhttps://example.com/two\nSecond snippet." in output


def test_search_web_handles_timeout_errors(tmp_path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, brave_api_key="brave-key")
    monkeypatch.setattr("harness.commands.common.time.sleep", lambda _: None)
    monkeypatch.setattr(
        web.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")),
    )

    result = web.search_web("vertical software", settings=settings)

    assert result.exit_code == 1
    assert "Search failed: timed out" in result.stderr.decode("utf-8")


def test_fetch_url_extracts_readable_text(tmp_path, monkeypatch) -> None:
    html = (
        "<html><head><title>Example Article</title><style>.hidden{}</style></head>"
        "<body><h1>Headline</h1><p>Readable paragraph.</p><li>Bullet detail.</li>"
        "<script>ignore()</script></body></html>"
    )
    monkeypatch.setattr(
        web.httpx,
        "get",
        lambda url, timeout, follow_redirects: _FakeResponse(text=html),
    )

    result = web.fetch_url("https://example.com/article")
    output: str = result.stdout.decode("utf-8")

    assert result.exit_code == 0
    assert output.startswith("Example Article")
    assert "Headline" in output
    assert "Readable paragraph." in output
    assert "Bullet detail." in output
    assert "ignore()" not in output


def test_fetch_url_handles_bad_urls(monkeypatch) -> None:
    monkeypatch.setattr(
        web.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.InvalidURL("bad url")),
    )

    result = web.fetch_url("not-a-url")

    assert result.exit_code == 1
    assert "Fetch failed: bad url" in result.stderr.decode("utf-8")
