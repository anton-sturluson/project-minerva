"""Source preservation and navigation parsing without live network requests."""

import pytest

from harness.ideas.documents import (
    PageLink,
    archive,
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
