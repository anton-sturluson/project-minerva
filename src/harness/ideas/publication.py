"""Deterministic digest preparation and durable Gateway delivery reconciliation."""

from __future__ import annotations

import hashlib
import json
import subprocess
from uuid import UUID

from psycopg.types.json import Jsonb

from harness.ideas import store
from harness.ideas.documents import load_sections
from harness.ideas.extraction import View, materialize, passages
from harness.ideas.research import resolve_identity, validate_match


def escape(text):
    return (
        " ".join(str(text).split())
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def checked_view(row: dict, run: dict) -> dict:
    document = row["document"]
    parts = load_sections(store.run_folder(run), document)
    validate_match(
        resolve_identity(document["identity"], parts), parts, run["issue_date"], row
    )
    view = View.model_validate(row["view"])
    materialize(view, passages(parts))
    return view.model_dump(mode="json")


def render(run_id: UUID) -> str:
    run = store.get_run(run_id)
    rows = [r for r in store.items(run_id) if r["state"] == "ready"]
    if not rows:
        return ""
    lines = [f"*Original manager ideas — {run['issue_date']}*", ""]
    for row in rows:
        view = checked_view(row, run)
        document = row["document"]
        # Stored ready records are created by extraction after both validation gates.
        if view["instrument"] != "equity" or view["stance"] == "unclear":
            continue
        period = document["identity"]["period"]
        lines.append(
            f"*{escape(document['identity'].get('company') or row['company'])}* — {escape(row['fund'])}"
        )
        action = (
            "" if view["action"] == "not stated" else f" · {escape(view['action'])}"
        )
        lines.append(f"{escape(view['stance'])}{action} · {escape(period)}")
        for claim in view["claims"]:
            lines.append("• " + escape(claim["text"]))
        lines.extend([f"<{document['url']}|Original manager letter>", ""])
    return "\n".join(lines).strip()


def gateway_json(*args):
    completed = subprocess.run(
        ["openclaw", "cron", *args, "--json"],
        capture_output=True,
        text=True,
        timeout=40,
        check=True,
    )
    return json.loads(completed.stdout)


def route_fields(route: dict) -> dict:
    return {key: route.get(key) for key in ("channel", "to", "threadId")}


def prepare(run_id: UUID, job_id: UUID) -> str:
    text = render(run_id)
    if not text:
        return "NO_REPLY"
    job = gateway_json("get", str(job_id))
    route = route_fields(job.get("delivery", {}))
    if (
        job.get("delivery", {}).get("mode") != "announce"
        or route["channel"] != "slack"
        or not route["to"]
    ):
        raise ValueError(
            "Publication requires the existing explicit Slack announce route"
        )
    digest = hashlib.sha256(
        (str(job_id) + json.dumps(route, sort_keys=True) + "\n" + text).encode()
    ).hexdigest()
    run = store.get_run(run_id)
    store.write_artifact(
        store.run_folder(run), f"publications/{digest}.slack.txt", text.encode()
    )
    with store.connect() as conn:
        row = conn.execute(
            "INSERT INTO minerva_ideas.publications(digest,run_id,job_id,state,route) VALUES(%s,%s,%s,'sending',%s) ON CONFLICT DO NOTHING RETURNING digest",
            (digest, run_id, job_id, Jsonb(route)),
        ).fetchone()
        if row:
            return text
        previous = conn.execute(
            "SELECT state FROM minerva_ideas.publications WHERE digest=%s", (digest,)
        ).fetchone()
        if previous["state"] == "delivered":
            return "NO_REPLY"
    raise ValueError(
        "Publication may already have been sent; reconcile delivery before another attempt"
    )


def reconcile(job_id: UUID) -> dict:
    entries = gateway_json("runs", "--id", str(job_id), "--limit", "20")["entries"]
    matched = 0
    with store.connect() as conn:
        pending = conn.execute(
            "SELECT * FROM minerva_ideas.publications WHERE job_id=%s AND state!='delivered'",
            (job_id,),
        ).fetchall()
        for publication in pending:
            run = store.get_run(publication["run_id"])
            path = (
                store.run_folder(run)
                / f"publications/{publication['digest']}.slack.txt"
            )
            text = path.read_text()
            for entry in entries:
                if entry.get("summary", "").strip() != text:
                    continue
                if entry.get("ts", 0) < publication["prepared_at"].timestamp() * 1000:
                    continue
                resolved = entry.get("delivery", {}).get("resolved", {})
                if route_fields(resolved) != publication["route"]:
                    continue
                if (
                    entry.get("delivered") is True
                    and entry.get("deliveryStatus") == "delivered"
                ):
                    # The receipt is the actual scheduler transport record, not a claim by the reporter.
                    conn.execute(
                        "UPDATE minerva_ideas.publications SET state='delivered',receipt=%s WHERE digest=%s",
                        (
                            Jsonb(
                                {
                                    "run_id": entry.get("runId")
                                    or entry.get("sessionId"),
                                    "delivered_at": entry.get("tsIso"),
                                    "route": route_fields(resolved),
                                }
                            ),
                            publication["digest"],
                        ),
                    )
                    matched += 1
                    break
            else:
                conn.execute(
                    "UPDATE minerva_ideas.publications SET state='unknown' WHERE digest=%s",
                    (publication["digest"],),
                )
    return {"confirmed_deliveries": matched}
