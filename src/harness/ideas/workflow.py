"""One resumable operation over persisted roster items."""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from uuid import UUID, uuid4

import httpx
import yaml

from harness.ideas import store
from harness.ideas.extraction import extract
from harness.ideas.model import DEFAULT_MODEL, ModelError
from harness.ideas.research import discover
from harness.ideas.roster import parse_roster

FEED = "https://hfbestideas.substack.com/feed"


def fetch_issue() -> tuple[dict, bytes]:
    response = httpx.get(FEED, timeout=30, follow_redirects=True)
    response.raise_for_status()
    if len(response.content) > 5 * 1024 * 1024:
        raise ValueError("Newsletter feed exceeds size limit")
    tree = ET.fromstring(response.content)
    choices = []
    for item in tree.findall("./channel/item"):
        body = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
        if "🔹" not in unescape(body):
            continue
        raw_date = item.findtext("pubDate")
        if not raw_date:
            continue
        published = parsedate_to_datetime(raw_date).astimezone(timezone.utc)
        roster = parse_roster(body)
        choices.append(
            (
                published,
                {
                    "url": item.findtext("link"),
                    "date": published.date().isoformat(),
                    "roster": [r.model_dump() for r in roster],
                },
                body,
            )
        )
    if not choices:
        raise ValueError("No issue roster found in feed")
    _, issue, body = max(choices, key=lambda row: row[0])
    # Downloaded XML is converted to YAML for readable research artifacts.
    readable = yaml.safe_dump(
        {"feed_url": FEED, "issue": issue, "issue_html": body},
        allow_unicode=True,
        sort_keys=False,
    ).encode()
    return issue, readable


def start(*, limit: int = 50, model: str = DEFAULT_MODEL) -> dict:
    issue, feed = fetch_issue()
    # Avoid generating a duplicate run when the scheduler sees the same newsletter.
    with store.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(719234002)")
        existing = conn.execute(
            "SELECT id FROM minerva_ideas.runs WHERE issue_url=%s ORDER BY created_at DESC LIMIT 1",
            (issue["url"],),
        ).fetchone()
        run_id = existing["id"] if existing else None
        if run_id:
            previous_folder = store.run_folder(store.get_run(run_id))
            if (
                json.loads((previous_folder / "research/issue.json").read_text())
                != issue
            ):
                run_id = None
        run_id = run_id or store.import_issue(issue)
        folder = store.run_folder(store.get_run(run_id))
        if not (folder / "research/feed.yaml").exists():
            store.write_artifact(folder, "research/feed.yaml", feed)
    return resume(run_id, limit=limit, model=model)


def resume(
    run_id: UUID,
    *,
    limit: int = 50,
    model: str = DEFAULT_MODEL,
    retry_gaps: bool = False,
) -> dict:
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if not os.environ.get("BRAVE_API_KEY") or not os.environ.get("GEMINI_API_KEY"):
        raise ValueError(
            "BRAVE_API_KEY and GEMINI_API_KEY are required before starting research"
        )
    deadline = time.monotonic() + 1200
    processed = 0
    with store.run_lock(run_id):
        run = store.get_run(run_id)
        store.json_artifact(
            store.run_folder(run),
            f"research/attempts/{uuid4()}.json",
            {"model": model, "limit": limit, "retry_gaps": retry_gaps},
        )
        for row in store.items(run_id):
            if row["state"] == "ready" or (row["state"] == "gap" and not retry_gaps):
                continue
            if processed >= limit or time.monotonic() > deadline:
                break
            processed += 1
            try:
                if not row.get("document") or (retry_gaps and row["state"] == "gap"):
                    outcome = discover(run_id, row["ordinal"], model=model)
                    if "gap" in outcome:
                        continue
                extract(run_id, row["ordinal"], model=model)
            except Exception as exc:
                # One failed item must not discard the valid work on other companies.
                # Provider exception text may contain request details; save only a safe class.
                reason = (
                    str(exc)[:500]
                    if isinstance(exc, ValueError)
                    else f"{type(exc).__name__}: collection/model request failed"
                )
                with store.connect() as conn:
                    conn.execute(
                        "UPDATE minerva_ideas.items SET state='failed',error=%s WHERE run_id=%s AND ordinal=%s",
                        (reason, run_id, row["ordinal"]),
                    )
                if isinstance(exc, ModelError):
                    break
        result = store.status(run_id)
        result["processed"] = processed
        result["outcome"] = (
            "partial"
            if result["counts"]["pending"]
            or result["counts"]["sourced"]
            or result["counts"]["failed"]
            else "complete"
        )
        store.json_artifact(
            store.run_folder(run), f"research/status/{uuid4()}.json", result
        )
        return result
