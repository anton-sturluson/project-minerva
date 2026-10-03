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
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
from lxml import html
from psycopg.types.json import Jsonb

from harness.ideas import store

MAX_BYTES = 25 * 1024 * 1024


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Source must be a public HTTPS URL without credentials")
    if (
        host == "hfbestideas.com"
        or host.endswith(".hfbestideas.com")
        or host == "hfbestideas.substack.com"
    ):
        raise ValueError("HF Best Ideas is discovery only, never thesis evidence")
    if any(c in url for c in "\r\n\t<>|"):
        raise ValueError("Invalid source URL")
    addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(a[4][0]).is_global for a in addresses
    ):
        raise ValueError("Source must resolve to public Internet addresses")
    return url


def download(url: str) -> tuple[bytes, str]:
    with httpx.Client(
        timeout=30, headers={"User-Agent": "Minerva research/1.0"}
    ) as client:
        for _ in range(6):
            public_url(url)
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


def sections(payload: bytes) -> tuple[str, list[dict]]:
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
        tree = html.fromstring(payload)
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
    if sum(len(p["text"]) for p in parts) > 250000:
        raise ValueError(
            "Document exceeds extraction budget; select a specific fund letter"
        )
    return kind, parts


def archive(folder: Path, url: str, *, fetch=download) -> dict:
    payload, final_url = fetch(url)
    digest = hashlib.sha256(payload).hexdigest()
    kind, parts = sections(payload)
    base = f"research/documents/{digest}"
    store.write_artifact(folder, f"{base}.{kind}", payload)
    store.json_artifact(folder, f"{base}.json", parts)
    readable = "\n\n".join(f"## {p['id']}\n\n{p['text']}" for p in parts) + "\n"
    store.write_artifact(folder, f"{base}.md", readable.encode())
    return {"url": final_url, "sha256": digest, "sections": f"{base}.json"}


def load_sections(folder: Path, document: dict) -> list[dict]:
    # All paths are generated from the archived byte hash, never supplied by the LLM.
    digest = document["sha256"]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("Invalid document hash")
    return json.loads((folder / f"research/documents/{digest}.json").read_text())


def attach(run_id: UUID, ordinal: int, url: str) -> dict:
    run = store.get_run(run_id)
    if not any(r["ordinal"] == ordinal for r in store.items(run_id)):
        raise ValueError("Unknown roster ordinal")
    document = archive(store.run_folder(run), url)
    with store.connect() as conn:
        conn.execute(
            "UPDATE minerva_ideas.items SET document=%s,state='sourced',error=NULL WHERE run_id=%s AND ordinal=%s",
            (Jsonb(document), run_id, ordinal),
        )
    return document
