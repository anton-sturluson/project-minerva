"""Source preservation and navigation parsing without live network requests."""

import json
from pathlib import Path

import pytest

from harness.ideas.documents import (
    PageLink,
    SourcePart,
    _archive_discovery,
    _parse_browser_page,
    archive,
    is_discovery_url,
    load_sections,
    page_links,
    public_url,
    sections,
)


def test_archive_hashes_bytes_and_preserves_locations(tmp_path):
    payload = b"<html><article><h1>Alpha Fund Q2 2026</h1><p>Acme pricing power supports cash generation. This is substantive company commentary with enough readable text for the source archive.</p></article></html>"
    fetch = lambda url: (payload, url)
    a = archive(tmp_path, "https://manager.com/letter", fetch=fetch)
    b = archive(tmp_path, "https://manager.com/other-link", fetch=fetch)
    assert a["sha256"] == b["sha256"]
    assert len(list((tmp_path / "research/documents").glob("*.html"))) == 1
    assert load_sections(tmp_path, a)[1]["id"] == "b2"
    assert "Acme" in load_sections(tmp_path, a)[1]["text"]


@pytest.mark.parametrize(
    "url",
    [
        "http://manager.com/letter",
        "https://hfbestideas.com/stock/A",
        "https://hfbestideas.substack.com/p/a",
        "https://user:password@example.com/a",
        "https://127.0.0.1/a",
    ],
)
def test_rejects_aggregator_and_nonpublic_sources(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_landing_page_links_survive_unreadable_text_and_keep_html_letters() -> None:
    """An archive can supply original links without itself being thesis evidence."""
    payload: bytes = b"""<html><nav>
      <a href="/insights/q3-letter">Q3 commentary</a>
      <a href="//manager.example.com/reports/current.pdf">PDF letter</a>
      <a href="/insights/q3-letter#company">Repeated destination</a>
      <a href="https://127.0.0.1/private">Private</a>
      <a href="https://10.0.0.1/private">Private</a>
      <a href="https://localhost/private">Private</a>
      <a href="https://user:password@example.com/private">Credentials</a>
      <a href="https://hfbestideas.substack.com/p/roster">Discovery</a>
      <a href="mailto:someone@example.com">Contact</a>
      <a href="https://[invalid">Malformed</a>
    </nav></html>"""
    with pytest.raises(ValueError, match="too little readable text"):
        sections(payload)
    assert page_links(payload, "https://manager.example.com/archive") == [
        {
            "url": "https://manager.example.com/insights/q3-letter",
            "label": "Q3 commentary",
        },
        {
            "url": "https://manager.example.com/reports/current.pdf",
            "label": "PDF letter",
        },
    ]


def test_archive_navigation_keeps_more_than_one_page_of_original_links() -> None:
    """Do not lose manager letters because they lack a dated PDF filename."""
    payload: bytes = (
        "<html><main>"
        + "".join(
            f'<a href="/letters/{number}">Letter {number}</a>' for number in range(125)
        )
        + "</main></html>"
    ).encode()
    links: list[PageLink] = page_links(payload, "https://manager.example.com/archive")
    assert len(links) == 125
    assert links[-1] == {
        "url": "https://manager.example.com/letters/124",
        "label": "Letter 124",
    }


def test_browser_page_preserves_large_html_and_unicode_line_separators() -> None:
    """Read complete rendered HTML beyond pipe capacity without splitting source text."""
    source: str = (
        "<html><article>"
        + "Evidence\u2028and\u2029qualifications. " * 6000
        + "</article></html>"
    )
    url: str = "https://manager.example.com/commentary"
    output: str = (
        json.dumps({"url": url, "html": source}, ensure_ascii=False)
        + "\n[ok | url: "
        + url
        + " | 1ms]\n"
    )
    payload: bytes
    final_url: str
    payload, final_url = _parse_browser_page(output)
    assert len(payload) > 65536
    assert payload.decode() == source
    assert final_url == url


def test_browser_page_rejects_truncated_html_or_failed_cli_output() -> None:
    """A partial DOM or failed command cannot become archived source evidence."""
    complete: str = json.dumps(
        {"url": "https://manager.example.com", "html": "<p>source</p>"}
    )
    with pytest.raises(ValueError):
        _parse_browser_page(complete[:-3])
    with pytest.raises(ValueError, match="invalid page result"):
        _parse_browser_page(complete + "\n[error | url: unavailable | 0ms]\n")


def test_newsletter_clues_cannot_enter_the_original_source_archive(
    tmp_path: Path,
) -> None:
    """Newsletter text and links remain separate from independently verified originals."""
    url: str = "https://hfbestideas.substack.com/p/weekly-ideas"
    payload: bytes = b'<article><p>Research clues name Acme and Alpha Fund and explain where to find their original quarterly commentary.</p><a href="/p/source-clues">More clues</a><a href="https://manager.example.com/letter">Original</a></article>'
    parts: list[SourcePart] = [{"id": "b1", "text": "Acme research clues"}]
    _archive_discovery(tmp_path, url, payload, parts)
    assert not (tmp_path / "research/documents").exists()
    assert not (tmp_path / "research/candidates").exists()
    assert (
        next((tmp_path / "research/discovery").glob("*.html")).read_bytes() == payload
    )
    assert (
        page_links(payload, url, allow_discovery=True)[0]["url"]
        == "https://hfbestideas.substack.com/p/source-clues"
    )
    assert page_links(payload, url) == [
        {"url": "https://manager.example.com/letter", "label": "Original"}
    ]
    with pytest.raises(ValueError, match="discovery only"):
        public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://hfbestideas.substack.com/p/weekly",
        "https://user:password@example.com/p/weekly",
        "https://127.0.0.1/private",
        "https://10.0.0.1/private",
    ],
)
def test_discovery_exception_preserves_public_url_security(url: str) -> None:
    """The newsletter exception changes only the discovery-host evidence ban."""
    with pytest.raises(ValueError):
        public_url(url, allow_discovery=True)


def test_discovery_host_detection_does_not_trust_lookalike_domains() -> None:
    """Classify requested and redirect destinations by their actual hostname."""
    assert is_discovery_url("https://www.hfbestideas.com/ideas")
    assert is_discovery_url("https://HFBestIdeas.Substack.com./p/weekly")
    assert not is_discovery_url("https://hfbestideas.substack.com.example.com/letter")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b" \n\t\r ",
        b"<!-- comment without a document -->",
        b"<!DOCTYPE html>",
        b"<!-- incomplete",
    ],
)
def test_empty_or_unparseable_html_remains_a_recoverable_collection_failure(
    payload: bytes,
) -> None:
    """Real parser failures expose no links and request browser text recovery."""
    assert page_links(payload, "https://manager.example.com/letter") == []
    with pytest.raises(
        ValueError, match="too little readable text.*browser collection"
    ):
        sections(payload)


def test_recoverable_html_markup_still_preserves_source_text_and_links() -> None:
    """Normal HTML parser repair must keep readable originals usable."""
    text: str = "Acme's recurring revenue and pricing power support durable cash generation. The manager sees an attractive valuation despite near-term demand uncertainty."
    payload: bytes = (
        "<article><h1>Fund commentary</h1><p>"
        + text
        + '<a href="/original-letter">Full original'
    ).encode()
    kind: str
    parts: list[dict[str, str]]
    kind, parts = sections(payload)
    assert kind == "html"
    assert any(text in part["text"] for part in parts)
    assert page_links(payload, "https://manager.example.com/archive") == [
        {"url": "https://manager.example.com/original-letter", "label": "Full original"}
    ]
