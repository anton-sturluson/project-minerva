"""One resumable operation over persisted roster items."""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from uuid import UUID, uuid4

import httpx
import yaml

from harness.ideas import store
from harness.ideas.model import ModelError, StageModels, check_model, resolve_models
from harness.ideas.roster import parse_roster

FEED = "https://hfbestideas.substack.com/feed"


def fetch_issue(issue_url: str | None = None) -> tuple[dict, bytes]:
    """Read the latest newsletter roster, or select an explicit URL from its feed."""
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
        if issue_url is not None and item.findtext("link") != issue_url:
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
        raise ValueError(
            "No matching issue roster in feed; use minerva ideas import for an archived issue."
        )
    _, issue, body = max(choices, key=lambda row: row[0])
    # Downloaded XML is converted to YAML for readable research artifacts.
    readable = yaml.safe_dump(
        {"feed_url": FEED, "issue": issue, "issue_html": body},
        allow_unicode=True,
        sort_keys=False,
    ).encode()
    return issue, readable


def start(
    *,
    limit: int = 50,
    model: str | None = None,
    fresh: bool = False,
    issue_url: str | None = None,
) -> dict:
    """Archive a newsletter and start or resume agent-directed original research."""
    issue, feed = fetch_issue(issue_url)
    # Avoid generating a duplicate run when the scheduler sees the same newsletter.
    with store.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(719234002)")
        existing = conn.execute(
            "SELECT id FROM minerva_ideas.runs WHERE issue_url=%s ORDER BY created_at DESC LIMIT 1",
            (issue["url"],),
        ).fetchone()
        run_id = existing["id"] if existing and not fresh else None
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


def selected_ordinals(rows: list[dict], limit: int, retry_gaps: bool) -> list[int]:
    """Select pending work without repeating approved or explicitly skipped views."""
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    return [
        row["ordinal"]
        for row in rows
        if row["state"] != "ready" and (row["state"] != "gap" or retry_gaps)
    ][:limit]


def resume(
    run_id: UUID,
    *,
    limit: int = 50,
    model: str | None = None,
    retry_gaps: bool = False,
) -> dict:
    """Let Sol direct parallel Luna research while preserving completed evidence."""
    from harness.ideas.agents import discover

    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    with store.run_lock(run_id):
        run: dict = store.get_run(run_id)
        rows: list[dict] = store.items(run_id)
        ordinals: list[int] = selected_ordinals(rows, limit, retry_gaps)
        if ordinals:
            if not os.environ.get("BRAVE_API_KEY"):
                raise ValueError("BRAVE_API_KEY is required before starting research")
            models: StageModels = resolve_models(model)
            coordinator: str = model or os.environ.get(
                "MINERVA_IDEAS_ORCHESTRATOR_MODEL", "gpt-6.1-sol"
            )
            selected: str
            for selected in (*asdict(models).values(), coordinator):
                check_model(selected)
                if not selected.startswith("gpt-"):
                    raise ValueError(
                        "Agent research requires GPT models; use --model gpt-6-luna for cheaper diagnostics."
                    )
            store.json_artifact(
                store.run_folder(run),
                f"research/attempts/{uuid4()}.json",
                {
                    "models": {"orchestrator": coordinator, **asdict(models)},
                    "limit": limit,
                    "retry_gaps": retry_gaps,
                    "ordinals": ordinals,
                },
            )
            with store.connect() as conn:
                conn.execute(
                    "UPDATE minerva_ideas.items SET state='pending',error=NULL "
                    "WHERE run_id=%s AND ordinal=ANY(%s) AND state IN ('gap','failed')",
                    (run_id, ordinals),
                )
            try:
                discover(
                    run_id, ordinals, model=model, deadline=time.monotonic() + 1200
                )
            except ModelError:
                with store.connect() as conn:
                    conn.execute(
                        "UPDATE minerva_ideas.items SET state='failed',error=%s "
                        "WHERE run_id=%s AND ordinal=ANY(%s) AND state IN ('pending','sourced')",
                        (
                            "Model request failed; inspect archived agent traces and resume.",
                            run_id,
                            ordinals,
                        ),
                    )
                store.json_artifact(
                    store.run_folder(run),
                    f"research/status/{uuid4()}.json",
                    store.status(run_id),
                )
                raise
        result: dict = store.status(run_id)
        result["processed"] = (
            sum(
                row["ordinal"] in ordinals and row["state"] != "pending"
                for row in store.items(run_id)
            )
            if ordinals
            else 0
        )
        result["outcome"] = (
            "partial"
            if any(
                result["counts"][state] for state in ("pending", "sourced", "failed")
            )
            else "complete_with_gaps"
            if result["counts"]["gap"]
            else "complete"
        )
        store.json_artifact(
            store.run_folder(run), f"research/status/{uuid4()}.json", result
        )
        return result
