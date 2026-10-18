"""Source preservation and navigation parsing without live network requests."""

import hashlib
import json
from pathlib import Path

import pytest

from harness.ideas.documents import (
    PageLink,
    SourceDocument,
    SourcePart,
    _archive_discovery,
    _archive_payload,
    _parse_browser_page,
    archive,
    canonical_scope,
    is_discovery_url,
    load_sections,
    page_links,
    public_url,
    read,
    resolve_scope,
    sections,
    select_sections,
    validate_scope,
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


@pytest.mark.parametrize(
    "signature",
    [
        "X-Amz-Signature=example&X-Amz-Expires=3600",
        "Signature=example&Expires=2000000000",
    ],
)
def test_signed_download_keeps_stable_citation_and_private_transport_provenance(
    tmp_path: Path, signature: str
) -> None:
    """Archive real source bytes without publishing an expiring transport URL."""
    stable: str = "https://manager.example.com/api/v1/file/letter"
    transport: str = "https://files.example.com/source?" + signature
    payload: bytes = b"<article><p>Acme's pricing power and disciplined capital allocation support durable cash generation, giving Alpha Fund confidence in its long-term investment thesis.</p></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply a synthetic redirect response to the real archive pipeline."""
        return payload, transport

    document: SourceDocument = archive(tmp_path, stable, fetch=fetch)
    assert document["url"] == stable
    assert document["sha256"] == hashlib.sha256(payload).hexdigest()
    assert "Signature" not in json.dumps(document)
    assert (
        tmp_path / f"research/documents/{document['sha256']}.html"
    ).read_bytes() == payload
    assert load_sections(tmp_path, document)[0]["text"].startswith(
        "Acme's pricing power"
    )
    provenance: dict[str, str] = json.loads(
        next((tmp_path / "research/documents").glob("*.provenance.json")).read_text()
    )
    assert provenance == {
        "collection": "http",
        "requested_url": stable,
        "url": transport,
    }


def test_unsigned_redirect_keeps_its_canonical_final_citation(tmp_path: Path) -> None:
    """Only signed redirects need the original request as their citation."""
    canonical: str = "https://manager.example.com/letters/quarterly"
    payload: bytes = b"<article><p>Alpha Fund sees Acme's improving business economics and recurring customer demand as support for its attractive valuation and future cash generation.</p></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply an ordinary redirect response to the archive pipeline."""
        return payload, canonical

    document: SourceDocument = archive(
        tmp_path, "https://manager.example.com/latest", fetch=fetch
    )
    assert document["url"] == canonical
    assert not list((tmp_path / "research/documents").glob("*.provenance.json"))


def test_browser_archive_uses_the_same_stable_citation_boundary(tmp_path: Path) -> None:
    """Rendered HTML keeps source blocks while its signed transport stays private."""
    payload: bytes = b"<article><p>Acme has an attractive valuation supported by rising recurring demand and durable margins. Alpha Fund expects cash generation to improve with scale.</p></article>"
    kind: str
    parts: list[SourcePart]
    kind, parts = sections(payload)
    stable: str = "https://manager.example.com/letter"
    transport: str = "https://files.example.com/letter?X-Amz-Signature=example"
    document: SourceDocument = _archive_payload(
        tmp_path,
        transport,
        payload,
        kind,
        parts,
        requested_url=stable,
        collection="browser",
    )
    assert document["url"] == stable and document["collection"] == "browser"
    assert load_sections(tmp_path, document) == parts
    provenance: dict[str, str] = json.loads(
        next((tmp_path / "research/documents").glob("*.provenance.json")).read_text()
    )
    assert provenance["url"] == transport and provenance["collection"] == "browser"


def test_direct_signed_download_cannot_become_a_citation(tmp_path: Path) -> None:
    """Without a stable manager route an expiring source must fail closed."""
    payload: bytes = b"<article><p>Alpha Fund sees Acme's improving business economics and recurring customer demand as support for its attractive valuation and future cash generation.</p></article>"
    signed: str = "https://files.example.com/letter?X-Amz-Signature=example"

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply bytes from a directly requested signed URL."""
        return payload, signed

    with pytest.raises(ValueError, match="stable manager URL"):
        archive(tmp_path, signed, fetch=fetch)
    assert not (tmp_path / "research/documents").exists()


def test_large_original_is_archived_before_selecting_bounded_source_content(
    tmp_path: Path,
) -> None:
    """Keep complete bytes and IDs while the model reads one explicit source range."""
    payload: bytes = (
        "<article><h1>Alpha Capital Q3 2026 fund reports</h1>"
        + "".join(
            f"<p>Fund section {number}. " + "Source commentary. " * 160 + "</p>"
            for number in range(125)
        )
        + "<p>Selected Global Fund: Acme has pricing power supporting durable margins.</p></article>"
    ).encode()

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply a large real HTML document to the normal archive parser."""
        return payload, url

    document: SourceDocument = archive(
        tmp_path, "https://manager.example.com/report", fetch=fetch
    )
    assert (
        tmp_path / f"research/documents/{document['sha256']}.html"
    ).read_bytes() == payload
    assert len(load_sections(tmp_path, document)) == 127
    result: dict = read(tmp_path, document)
    assert result["status"] == "need_selection" and result["parts"] == []
    assert len(result["section_index"]) == 100 and result["next_index_offset"] == 100
    assert (
        read(tmp_path, document, index_offset=100)["section_index"][-1]["id"] == "b127"
    )
    search: dict = read(tmp_path, document, query="Acme")
    assert search["total_matches"] == 1 and search["section_index"][0]["id"] == "b127"
    assert "Acme" in search["section_index"][0]["preview"]
    selected: SourceDocument = select_sections(tmp_path, document, ["b127"], ["b1"])
    scope: dict = resolve_scope(tmp_path, selected)
    assert [part["id"] for part in scope["content"]] == ["b127"]
    assert [part["id"] for part in scope["identity"]] == ["b1", "b127"]
    assert len(load_sections(tmp_path, selected)) == 127
    assert selected["sha256"] == document["sha256"]


@pytest.mark.parametrize(
    ("content", "anchors"),
    [
        (["b2", "b4"], []),
        (["b3", "b2"], []),
        (["b2", "b2"], []),
        (["b99"], []),
        ([], []),
        (["b2"], ["b2"]),
        (["b2"], ["b1", "b1"]),
        (["b2"], ["b99"]),
    ],
)
def test_source_selection_rejects_missing_disordered_and_overlapping_ids(
    tmp_path: Path, content: list[str], anchors: list[str]
) -> None:
    """An explicit range cannot skip source blocks or borrow duplicate anchors."""
    payload: bytes = b"<article><h1>Alpha Capital Q3 2026</h1><h2>Global Fund</h2><p>Acme has pricing power supporting durable margins and cash generation.</p><h2>Other Fund</h2></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply two fund headings with unchanged source block IDs."""
        return payload, url

    document: SourceDocument = archive(
        tmp_path, "https://manager.example.com/report", fetch=fetch
    )
    with pytest.raises(ValueError):
        select_sections(tmp_path, document, content, anchors)


def test_scope_keeps_anchors_out_of_claim_evidence_and_requires_actual_identity_use(
    tmp_path: Path,
) -> None:
    """Publisher context cannot become company thesis evidence or authorize another fund."""
    from harness.ideas.extraction import Claim, View, materialize, passages

    payload: bytes = b"<article><h1>Alpha Capital Q3 2026</h1><h2>Global Fund</h2><p>Acme has pricing power supporting durable margins and cash generation.</p><h2>Other Fund</h2></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply the source used by the real evidence materializer."""
        return payload, url

    document: SourceDocument = archive(
        tmp_path, "https://manager.example.com/report", fetch=fetch
    )
    selected: SourceDocument = select_sections(tmp_path, document, ["b2", "b3"], ["b1"])
    identity: dict[str, str] = {
        "fund_block": "b2",
        "company_block": "b3",
        "publisher_block": "b1",
        "period_block": "b1",
    }
    validate_scope(selected, identity)
    with pytest.raises(ValueError, match="selected content"):
        validate_scope(selected, {**identity, "fund_block": "b4"})
    with pytest.raises(ValueError, match="Every source anchor"):
        validate_scope(
            selected, {**identity, "publisher_block": "b2", "period_block": "b2"}
        )
    content: list[SourcePart] = resolve_scope(tmp_path, selected)["content"]
    view: View = View(
        instrument="equity",
        stance="bull",
        action="not stated",
        claims=[Claim(text="Acme has pricing power.", passages=["b3.1"])],
        gap="",
    )
    assert (
        materialize(view, passages(content))["claims"][0]["evidence"][0]["block"]
        == "b3.1"
    )
    bad: View = view.model_copy(
        update={"claims": [Claim(text="Acme has pricing power.", passages=["b1.1"])]}
    )
    with pytest.raises(ValueError, match="unknown source passage"):
        materialize(bad, passages(content))


def test_attribution_anchors_count_toward_the_same_model_budget(tmp_path: Path) -> None:
    """Small company content cannot hide an oversized attribution context."""
    payload: bytes = (
        "<article><p>Publisher "
        + "Original text. " * 18000
        + "</p><p>Acme has pricing power and strong cash generation.</p></article>"
    ).encode()

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply a large attribution block and a small company block."""
        return payload, url

    document: SourceDocument = archive(
        tmp_path, "https://manager.example.com/report", fetch=fetch
    )
    assert (
        resolve_scope(tmp_path, select_sections(tmp_path, document, ["b2"]))["content"][
            0
        ]["id"]
        == "b2"
    )
    with pytest.raises(ValueError, match="need_selection"):
        select_sections(tmp_path, document, ["b2"], ["b1"])


def test_equivalent_source_scope_encodings_cannot_change_decision_identity(
    tmp_path: Path,
) -> None:
    """Explicit full content and reordered anchors cannot authorize another model attempt."""
    payload: bytes = b"<article><h1>Alpha Capital Q3 2026</h1><h2>Global Fund</h2><p>Acme has pricing power supporting durable margins and cash generation.</p><p>Alpha Capital manages the Global Fund.</p></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Supply exact source blocks for equivalent evidence scope encodings."""
        return payload, url

    document: SourceDocument = archive(
        tmp_path, "https://manager.example.com/report", fetch=fetch
    )
    explicit: SourceDocument = select_sections(
        tmp_path, document, ["b1", "b2", "b3", "b4"]
    )
    assert (
        canonical_scope(tmp_path, document)
        == canonical_scope(tmp_path, explicit)
        == ([], [])
    )
    first: SourceDocument = select_sections(
        tmp_path, document, ["b2", "b3"], ["b1", "b4"]
    )
    reordered: SourceDocument = select_sections(
        tmp_path, document, ["b2", "b3"], ["b4", "b1"]
    )
    assert (
        canonical_scope(tmp_path, first)
        == canonical_scope(tmp_path, reordered)
        == (["b2", "b3"], ["b1", "b4"])
    )


def test_publication_uses_selected_content_and_attribution_anchors_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real archived selection can render, but anchor-only claims cannot pass."""
    from datetime import date
    from uuid import UUID

    from harness.ideas import publication, store

    monkeypatch.setenv("MINERVA_IDEAS_ROOT", str(tmp_path))
    run: dict = {"id": UUID(int=9), "issue_date": date(2026, 10, 14)}
    payload: bytes = b"<article><h1>Alpha Capital Q3 2026</h1><h2>Global Fund</h2><p>Acme has pricing power supporting durable margins and cash generation.</p></article>"

    def fetch(url: str) -> tuple[bytes, str]:
        """Preserve real parsed source evidence without a network dependency."""
        return payload, url

    folder: Path = store.run_folder(run)
    document: SourceDocument = select_sections(
        folder,
        archive(folder, "https://manager.example.com/report", fetch=fetch),
        ["b2", "b3"],
        ["b1"],
    )
    identity: dict = {
        "accepted": True,
        "reason": "test original",
        "fund": "Global Fund",
        "company": "Acme",
        "period": "Q3 2026",
        "period_end": "2026-09-30",
        "publisher_block": "b1",
        "fund_block": "b2",
        "company_block": "b3",
        "period_block": "b1",
    }
    view: dict = {
        "instrument": "equity",
        "stance": "bull",
        "action": "not stated",
        "claims": [{"text": "Acme has pricing power.", "passages": ["b3.1"]}],
        "gap": "",
    }
    row: dict = {
        "company": "Acme",
        "fund": "Global Fund",
        "symbol": "ACM US",
        "document": {**document, "identity": identity},
        "view": view,
    }
    assert publication.checked_view(row, run) == view
    with pytest.raises(ValueError, match="unknown source passage"):
        publication.checked_view(
            {
                **row,
                "view": {
                    **view,
                    "claims": [
                        {"text": "Acme has pricing power.", "passages": ["b1.1"]}
                    ],
                },
            },
            run,
        )
    with pytest.raises(ValueError, match="selected content"):
        publication.checked_view(
            {
                **row,
                "document": {
                    **row["document"],
                    "identity": {**identity, "fund_block": "b1"},
                },
            },
            run,
        )
