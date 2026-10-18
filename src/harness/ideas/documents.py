"""Archive public original documents with stable evidence locations."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal, NotRequired, TextIO, TypedDict
from urllib.parse import SplitResult, parse_qsl, urljoin, urlsplit
from uuid import UUID

import httpx
import yaml
from lxml import etree, html

from harness.ideas import store

MAX_BYTES = 25 * 1024 * 1024
MAX_MODEL_CHARACTERS: int = 250000
LINK_PAGE_SIZE = 100
INDEX_PAGE_SIZE: int = 100


class SourcePart(TypedDict):
    """One numbered block extracted from the archived source."""

    id: str
    text: str


class SourceDocument(TypedDict):
    """Metadata compatible with the existing source archive and evidence loader."""

    url: str
    sha256: str
    sections: str
    collection: NotRequired[str]
    section_ids: NotRequired[list[str]]
    anchor_ids: NotRequired[list[str]]


class SectionIndex(TypedDict):
    """A source location and short heading preview, without changing its ID."""

    id: str
    characters: int
    preview: str


class ReadResult(TypedDict):
    """A bounded source scope or explicit instructions to select original sections."""

    status: Literal["ready", "need_selection"]
    document: SourceDocument
    parts: list[SourcePart]
    section_index: list[SectionIndex]
    next_index_offset: int | None
    total_matches: int
    full_block_count: int


class SourceScope(TypedDict):
    """Separate thesis content from attribution context in the same original."""

    content: list[SourcePart]
    identity: list[SourcePart]


class PageLink(TypedDict):
    """A navigation candidate that is revalidated before any network request."""

    url: str
    label: str


class BrowseResult(TypedDict):
    """A readable original or navigation page with explicit link pagination."""

    url: str
    document: SourceDocument | None
    parts: list[SourcePart]
    links: list[PageLink]
    link_offset: int
    next_link_offset: int | None
    total_links: int
    text_error: str | None
    discovery_only: bool
    need_selection: bool
    section_index: list[SectionIndex]
    next_index_offset: int | None
    full_block_count: int


def is_discovery_url(url: str) -> bool:
    """Identify HF Best Ideas hosts without accepting lookalike domains."""
    host: str = (urlsplit(url).hostname or "").rstrip(".").lower()
    return (
        host == "hfbestideas.com"
        or host.endswith(".hfbestideas.com")
        or host == "hfbestideas.substack.com"
    )


def _citation_url(requested_url: str, final_url: str) -> str:
    """Cite a stable manager route instead of its signed S3 download redirect."""
    signed_fields: set[str] = {"x-amz-signature", "signature"}
    final_fields: set[str] = {
        key.casefold()
        for key, _ in parse_qsl(urlsplit(final_url).query, keep_blank_values=True)
    }
    if not final_fields & signed_fields:
        return final_url
    requested_fields: set[str] = {
        key.casefold()
        for key, _ in parse_qsl(urlsplit(requested_url).query, keep_blank_values=True)
    }
    if requested_fields & signed_fields:
        raise ValueError(
            "Signed source download needs a stable manager URL for citation"
        )
    return requested_url


def public_url(url: str, *, allow_discovery: bool = False) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Source must be a public HTTPS URL without credentials")
    if is_discovery_url(url) and not allow_discovery:
        raise ValueError("HF Best Ideas is discovery only, never thesis evidence")
    if any(c in url for c in "\r\n\t<>|"):
        raise ValueError("Invalid source URL")
    addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(a[4][0]).is_global for a in addresses
    ):
        raise ValueError("Source must resolve to public Internet addresses")
    return url


def download(url: str, *, allow_discovery: bool = False) -> tuple[bytes, str]:
    with httpx.Client(
        timeout=30, headers={"User-Agent": "Minerva research/1.0"}
    ) as client:
        for _ in range(6):
            public_url(url, allow_discovery=allow_discovery)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Source exceeds 25 MB")
                    chunks.append(chunk)
                payload = b"".join(chunks)
                if not payload:
                    raise ValueError("Source is empty")
                return payload, url
    raise ValueError("Too many source redirects")


def _html_tree(payload: bytes) -> html.HtmlElement:
    """Normalize empty or invalid HTML into a recoverable collection failure."""
    try:
        return html.fromstring(payload)
    except (etree.ParserError, etree.XMLSyntaxError) as exc:
        raise ValueError(
            "Source contains too little readable text; invalid or empty HTML needs browser collection"
        ) from exc


def sections(payload: bytes) -> tuple[str, list[dict]]:
    """Extract source blocks or report a recoverable text-collection failure."""
    if payload.lstrip().startswith(b"%PDF-"):
        converter = shutil.which("pdftotext")
        if not converter:
            raise ValueError("Install pdftotext to read PDF letters")
        with tempfile.TemporaryDirectory(prefix="minerva-ideas-") as temp:
            path = Path(temp) / "source.pdf"
            path.write_bytes(payload)
            result = subprocess.run(
                [converter, "-layout", str(path), "-"],
                capture_output=True,
                timeout=40,
                check=True,
            )
        parts = [
            {"id": f"p{i}", "text": text.strip()}
            for i, text in enumerate(result.stdout.decode("utf-8").split("\f"), 1)
            if text.strip()
        ]
        kind = "pdf"
    else:
        tree = _html_tree(payload)
        for node in tree.xpath("//script | //style | //nav | //footer | //header"):
            node.drop_tree()
        bodies = tree.xpath("//article") or tree.xpath("//main") or [tree]
        body = max(bodies, key=lambda x: len(x.text_content()))
        # Paragraph blocks give readable, precise quote locations in HTML.
        nodes = body.xpath(".//h1 | .//h2 | .//h3 | .//p | .//li | .//tr")
        texts = [" ".join(n.text_content().split()) for n in nodes] or [
            " ".join(body.text_content().split())
        ]
        parts = [
            {"id": f"b{i}", "text": text} for i, text in enumerate(texts, 1) if text
        ]
        kind = "html"
    if not parts or sum(len(p["text"]) for p in parts) < 100:
        raise ValueError(
            "Source contains too little readable text; OCR or browser collection needed"
        )
    return kind, parts


def page_links(
    payload: bytes, url: str, *, allow_discovery: bool = False
) -> list[PageLink]:
    """Keep HTML article and document destinations without date or PDF filtering.

    Obvious nonpublic URLs are omitted here. DNS and redirect checks still run
    through public_url before a returned candidate can be fetched.
    """
    if payload.lstrip().startswith(b"%PDF-"):
        return []
    try:
        tree: html.HtmlElement = _html_tree(payload)
    except ValueError:
        return []
    found: dict[str, PageLink] = {}
    node: html.HtmlElement
    for node in tree.xpath("//a[@href]"):
        try:
            destination: str = urljoin(url, node.get("href", "")).split("#", 1)[0]
            parsed: SplitResult = urlsplit(destination)
            host: str = (parsed.hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or host.endswith((".local", ".localhost"))
            or (is_discovery_url(destination) and not allow_discovery)
            or any(character in destination for character in "\r\n\t<>|")
        ):
            continue
        try:
            if not ipaddress.ip_address(host).is_global:
                continue
        except ValueError:
            if "." not in host:
                continue
        label: str = " ".join(node.text_content().split()) or node.get("title", "")
        if destination not in found or not found[destination]["label"]:
            found[destination] = {"url": destination, "label": label[:500]}
    return list(found.values())


def _parse_browser_page(output: str) -> tuple[bytes, str]:
    """Parse complete JSON before CLI diagnostics, retaining embedded line separators."""
    content: str = output.lstrip()
    page: dict[str, str]
    end: int
    page, end = json.JSONDecoder().raw_decode(content)
    if (
        not isinstance(page, dict)
        or not isinstance(page.get("html"), str)
        or not isinstance(page.get("url"), str)
        or not content[end:].strip().startswith("[ok |")
    ):
        raise ValueError("Browser recovery returned an invalid page result")
    payload: bytes = page["html"].encode()
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("Rendered source is empty or exceeds 25 MB")
    return payload, page["url"]


def rendered_download(url: str, *, allow_discovery: bool = False) -> tuple[bytes, str]:
    """Read the actual rendered HTML in an owned browser tab and then close it."""
    public_url(url, allow_discovery=allow_discovery)
    browser: str | None = shutil.which("browser")
    if browser is None:
        raise ValueError(
            "Browser recovery is unavailable; browser CLI is not installed"
        )
    opened: subprocess.CompletedProcess[str] = subprocess.run(
        [browser, "open", url, "--new", "--window", "--no-delay"],
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    match: re.Match[str] | None = re.search(
        r"^Tab alias: (t[0-9]+)$", opened.stdout, re.M
    )
    if match is None:
        raise ValueError("Browser recovery did not return an owned tab alias")
    alias: str = match[1]
    try:
        subprocess.run(
            [browser, "wait", "--stable", "body", "--timeout", "15000", "--tab", alias],
            capture_output=True,
            text=True,
            timeout=25,
            check=True,
        )
        expression: str = "JSON.stringify({url:location.href,html:document.documentElement.outerHTML})"
        # The CLI exits before a large stdout pipe drains. Regular-file stdout
        # preserves the full DOM instead of truncating it at the pipe capacity.
        output: TextIO
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
            subprocess.run(
                [browser, "eval", expression, "--tab", alias],
                stdout=output,
                stderr=subprocess.PIPE,
                text=True,
                timeout=40,
                check=True,
            )
            output.seek(0)
            payload: bytes
            final_url: str
            payload, final_url = _parse_browser_page(output.read())
        public_url(final_url, allow_discovery=allow_discovery)
        return payload, final_url
    finally:
        subprocess.run(
            [browser, "close", alias],
            capture_output=True,
            text=True,
            timeout=25,
            check=True,
        )


def browse(folder: Path, url: str, *, link_offset: int = 0) -> BrowseResult:
    """Browse an original or archive page without discarding useful navigation links."""
    if link_offset < 0:
        raise ValueError("Link offset must be nonnegative")
    collection: str = "http"
    payload: bytes
    final_url: str
    try:
        payload, final_url = download(url, allow_discovery=True)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {403, 429}:
            raise
        payload, final_url = rendered_download(url, allow_discovery=True)
        collection = "browser"
    discovery_only: bool = is_discovery_url(url) or is_discovery_url(final_url)
    links: list[PageLink] = page_links(
        payload, final_url, allow_discovery=discovery_only
    )
    kind: str = ""
    parts: list[SourcePart] = []
    text_error: str | None = None
    try:
        kind, parts = sections(payload)
    except ValueError as exc:
        text_error = str(exc)
        if collection == "http" and "too little readable text" in text_error:
            try:
                payload, final_url = rendered_download(url, allow_discovery=True)
                collection = "browser"
                discovery_only = is_discovery_url(url) or is_discovery_url(final_url)
                links = page_links(payload, final_url, allow_discovery=discovery_only)
                kind, parts = sections(payload)
                text_error = None
            except (ValueError, OSError, subprocess.SubprocessError) as recovery:
                text_error += f"; browser recovery failed ({type(recovery).__name__})"
    document: SourceDocument | None = None
    reading: ReadResult | None = None
    if discovery_only:
        _archive_discovery(folder, final_url, payload, parts)
    elif text_error is None:
        document = _archive_payload(
            folder,
            final_url,
            payload,
            kind,
            parts,
            requested_url=url,
            collection=collection,
        )
        reading = read(folder, document)
        parts = reading["parts"]
    next_offset: int = link_offset + LINK_PAGE_SIZE
    return {
        "url": final_url,
        "document": document,
        "parts": parts,
        "links": links[link_offset:next_offset],
        "link_offset": link_offset,
        "next_link_offset": next_offset if next_offset < len(links) else None,
        "total_links": len(links),
        "text_error": text_error,
        "discovery_only": discovery_only,
        "need_selection": reading is not None and reading["status"] == "need_selection",
        "section_index": reading["section_index"] if reading else [],
        "next_index_offset": reading["next_index_offset"] if reading else None,
        "full_block_count": reading["full_block_count"] if reading else len(parts),
    }


def _archive_discovery(
    folder: Path, url: str, payload: bytes, parts: list[SourcePart]
) -> None:
    """Keep newsletter clues outside the original-document archive and indexes."""
    digest: str = hashlib.sha256(payload).hexdigest()
    base: str = f"research/discovery/{digest}"
    if payload.lstrip().startswith(b"<?xml"):
        # XML feeds are converted to readable YAML instead of saving raw XML.
        readable_feed: str = yaml.safe_dump(
            {"url": url, "parts": parts}, allow_unicode=True, sort_keys=False
        )
        store.write_artifact(folder, f"{base}.yaml", readable_feed.encode())
    else:
        store.write_artifact(folder, f"{base}.html", payload)
    store.json_artifact(folder, f"{base}.json", parts)
    readable: str = (
        "\n\n".join(f"## {part['id']}\n\n{part['text']}" for part in parts) + "\n"
    )
    store.write_artifact(folder, f"{base}.md", readable.encode())


def _archive_payload(
    folder: Path,
    url: str,
    payload: bytes,
    kind: str,
    parts: list[SourcePart],
    *,
    requested_url: str | None = None,
    collection: str | None = None,
) -> SourceDocument:
    """Save eligible source bytes and blocks once for archive and browse callers."""
    requested: str = requested_url or url
    citation: str = _citation_url(requested, url)
    digest: str = hashlib.sha256(payload).hexdigest()
    base: str = f"research/documents/{digest}"
    store.write_artifact(folder, f"{base}.{kind}", payload)
    store.json_artifact(folder, f"{base}.json", parts)
    readable: str = "\n\n".join(f"## {p['id']}\n\n{p['text']}" for p in parts) + "\n"
    store.write_artifact(folder, f"{base}.md", readable.encode())
    document: SourceDocument = {
        "url": citation,
        "sha256": digest,
        "sections": f"{base}.json",
    }
    if collection:
        document["collection"] = collection
    if citation != url or collection == "browser":
        request_hash: str = hashlib.sha256(requested.encode()).hexdigest()[:16]
        store.json_artifact(
            folder,
            f"{base}.{request_hash}.provenance.json",
            {
                "collection": collection or "http",
                "requested_url": requested,
                "url": url,
            },
        )
    return document


def archive(
    folder: Path,
    url: str,
    *,
    fetch: Callable[[str], tuple[bytes, str]] = download,
) -> SourceDocument:
    """Archive the complete readable original independently of model scope limits."""
    payload: bytes
    final_url: str
    payload, final_url = fetch(url)
    kind: str
    parts: list[SourcePart]
    kind, parts = sections(payload)
    return _archive_payload(folder, final_url, payload, kind, parts, requested_url=url)


def load_sections(folder: Path, document: dict) -> list[SourcePart]:
    """Load stable original blocks from the application-generated hash path."""
    # All paths are generated from the archived byte hash, never supplied by the LLM.
    digest: str = document["sha256"]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("Invalid document hash")
    return json.loads((folder / f"research/documents/{digest}.json").read_text())


def _scope(document: dict, parts: list[SourcePart]) -> tuple[list[str], list[str]]:
    """Validate explicit content ranges and separate attribution-only anchors."""
    ids: list[str] = [part["id"] for part in parts]
    if "section_ids" not in document and "anchor_ids" not in document:
        return ids, []
    content: list[str] = document.get("section_ids", [])
    anchors: list[str] = document.get("anchor_ids", [])
    if (
        not isinstance(content, list)
        or not content
        or any(not isinstance(key, str) for key in content)
        or len(set(content)) != len(content)
        or any(key not in ids for key in content)
    ):
        raise ValueError("Source content needs unique existing section IDs")
    start: int = ids.index(content[0])
    if ids[start : start + len(content)] != content:
        raise ValueError("Source content must be one ordered contiguous section range")
    if (
        not isinstance(anchors, list)
        or any(not isinstance(key, str) for key in anchors)
        or len(set(anchors)) != len(anchors)
        or any(key not in ids or key in content for key in anchors)
    ):
        raise ValueError("Source anchors need unique existing IDs outside the content")
    return content, anchors


def select_sections(
    folder: Path,
    document: SourceDocument,
    section_ids: list[str],
    anchor_ids: list[str] | None = None,
) -> SourceDocument:
    """Select exact original content and attribution anchors without renumbering."""
    selected: SourceDocument = {
        **document,
        "section_ids": list(section_ids),
        "anchor_ids": list(anchor_ids or []),
    }
    # A prior approval cannot authorize a different evidence scope.
    selected.pop("identity", None)
    resolve_scope(folder, selected)
    return selected


def resolve_scope(folder: Path, document: dict) -> SourceScope:
    """Validate one bounded scope, keeping attribution anchors outside thesis content."""
    parts: list[SourcePart] = load_sections(folder, document)
    content: list[str]
    anchors: list[str]
    content, anchors = _scope(document, parts)
    allowed: set[str] = set(content + anchors)
    scoped: list[SourcePart] = [part for part in parts if part["id"] in allowed]
    if sum(len(part["text"]) for part in scoped) > MAX_MODEL_CHARACTERS:
        raise ValueError(
            "need_selection: select a bounded fund section using the source reader"
        )
    content_set: set[str] = set(content)
    return {
        "identity": scoped,
        "content": [part for part in scoped if part["id"] in content_set],
    }


def validate_scope(document: dict, identity: dict) -> None:
    """Require thesis identity inside content and every anchor used for attribution."""
    if "section_ids" not in document and "anchor_ids" not in document:
        return
    content: set[str] = set(document.get("section_ids", []))
    anchors: set[str] = set(document.get("anchor_ids", []))
    if any(
        identity.get(role + "_block") not in content for role in ("fund", "company")
    ):
        raise ValueError(
            "Fund and company identity must belong to the selected content section"
        )
    attribution: set[str] = {
        identity.get("publisher_block", ""),
        identity.get("period_block", ""),
        *identity.get("relationship_blocks", []),
    }
    if not anchors <= attribution:
        raise ValueError(
            "Every source anchor must support publisher, period or fund relationship identity"
        )


def canonical_scope(folder: Path, document: dict) -> tuple[list[str], list[str]]:
    """Give equivalent validated evidence scopes the same decision-key representation."""
    scope: SourceScope = resolve_scope(folder, document)
    content: list[str] = [part["id"] for part in scope["content"]]
    content_set: set[str] = set(content)
    anchors: list[str] = [
        part["id"] for part in scope["identity"] if part["id"] not in content_set
    ]
    all_ids: list[str] = [part["id"] for part in load_sections(folder, document)]
    return ([], []) if content == all_ids and not anchors else (content, anchors)


def read(
    folder: Path,
    document: SourceDocument,
    *,
    section_ids: list[str] | None = None,
    anchor_ids: list[str] | None = None,
    index_offset: int = 0,
    query: str | None = None,
) -> ReadResult:
    """Inspect archived blocks or select a bounded range with stable evidence IDs."""
    if index_offset < 0:
        raise ValueError("Section index offset must be nonnegative")
    if anchor_ids is not None and section_ids is None:
        raise ValueError("Attribution anchors require an explicit content range")
    selected: SourceDocument = (
        select_sections(folder, document, section_ids, anchor_ids)
        if section_ids is not None
        else document
    )
    parts: list[SourcePart] = load_sections(folder, selected)
    content: list[str]
    anchors: list[str]
    content, anchors = _scope(selected, parts)
    allowed: set[str] = set(content + anchors)
    scoped: list[SourcePart] = [part for part in parts if part["id"] in allowed]
    needs_selection: bool = (
        sum(len(part["text"]) for part in scoped) > MAX_MODEL_CHARACTERS
    )
    next_offset: int = index_offset + INDEX_PAGE_SIZE
    matches: list[SourcePart] = [
        part
        for part in parts
        if not query or query.casefold() in part["text"].casefold()
    ]
    index: list[SectionIndex] = []
    part: SourcePart
    for part in matches[index_offset:next_offset]:
        compact: str = " ".join(part["text"].split())
        position: int = (
            max(0, compact.casefold().find(query.casefold()) - 100) if query else 0
        )
        index.append(
            {
                "id": part["id"],
                "characters": len(part["text"]),
                "preview": compact[position : position + 300],
            }
        )
    return {
        "status": "need_selection" if needs_selection else "ready",
        "document": selected,
        "parts": [] if needs_selection else scoped,
        "section_index": index,
        "next_index_offset": next_offset if next_offset < len(matches) else None,
        "total_matches": len(matches),
        "full_block_count": len(parts),
    }


def attach(
    run_id: UUID,
    ordinal: int,
    url: str,
    *,
    section_ids: list[str] | None = None,
    anchor_ids: list[str] | None = None,
) -> dict:
    """Use the shared unpublished-run and exact-approval attachment boundary."""
    from harness.ideas.extraction import attach_source

    return attach_source(
        run_id, ordinal, url, section_ids=section_ids, anchor_ids=anchor_ids
    )
