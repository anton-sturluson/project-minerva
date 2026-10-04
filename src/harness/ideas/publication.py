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
    groups = {}
    for row in rows:
        groups.setdefault(row["company"], []).append(row)
    for company_rows in groups.values():
        company = (
            company_rows[0]["document"]["identity"].get("company")
            or company_rows[0]["company"]
        )
        lines.append(f"*{escape(company)}*")
        for row in company_rows:
            lines.extend(render_fund(row, run))
        lines.append("")
    return "\n".join(lines).strip()


def render_fund(row, run):
    lines = []
    view = checked_view(row, run)
    document = row["document"]
    # Stored ready records are created by extraction after both validation gates.
    if view["instrument"] != "equity" or view["stance"] == "unclear":
        return []
    period = document["identity"]["period"]
    lines.append(f"*{escape(row['fund'])}*")
    action = "" if view["action"] == "not stated" else f" · {escape(view['action'])}"
    lines.append(f"{escape(view['stance'])}{action} · {escape(period)}")
    for claim in view["claims"]:
        lines.append("• " + escape(claim["text"]))
    lines.extend([f"<{document['url']}|Original manager letter>", ""])
    return lines


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
    prepared = prepare_publication(run_id, job_id)
    return prepared["text"] if prepared else "NO_REPLY"


def prepare_publication(run_id: UUID, job_id: UUID, *, threaded=False) -> dict | None:
    text = render(run_id)
    if not text:
        return None
    job = gateway_json("get", str(job_id))
    route = route_fields(job.get("delivery", {}))
    if threaded:
        route["format"] = "manager-thread-v1"
        if job.get("delivery", {}).get("accountId"):
            route["accountId"] = job["delivery"]["accountId"]
        if route.get("threadId"):
            raise ValueError("Thread publication requires no fixed delivery.threadId")
        title = f"🧵 Manager Ideas - {store.get_run(run_id)['issue_date']}"
        # Validate all parts before creating a publication or sending its parent.
        thread_parts(text)
        text = title + "\n\n" + text
    if (
        job.get("payload", {}).get("kind") != "command"
        or job.get("delivery", {}).get("mode") != ("none" if threaded else "announce")
        or route["channel"] != "slack"
        or not route["to"]
    ):
        raise ValueError(
            "Publication requires a native command job with an explicit Slack destination; threaded delivery requires mode=none, legacy prepare requires mode=announce"
        )
    digest = hashlib.sha256(
        (str(job_id) + json.dumps(route, sort_keys=True) + "\n" + text).encode()
    ).hexdigest()
    with store.connect() as conn:
        existing = conn.execute(
            "SELECT state FROM minerva_ideas.publications WHERE digest=%s", (digest,)
        ).fetchone()
        if existing and existing["state"] == "delivered":
            return None
        pending = conn.execute(
            "SELECT 1 FROM minerva_ideas.publications WHERE run_id=%s AND job_id=%s AND state!='delivered'",
            (run_id, job_id),
        ).fetchone()
        if pending:
            raise ValueError(
                "Publication may already have been sent; reconcile delivery before another attempt"
            )
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
            return {"digest": digest, "text": text, "route": route}
        previous = conn.execute(
            "SELECT state FROM minerva_ideas.publications WHERE digest=%s", (digest,)
        ).fetchone()
        if previous["state"] == "delivered":
            return None
    raise ValueError(
        "Publication may already have been sent; reconcile delivery before another attempt"
    )


def delivered_route(entry: dict) -> dict:
    delivery = entry.get("delivery", {})
    if delivery.get("resolved"):
        return route_fields(delivery["resolved"])
    # Native command receipts record the explicit destination without an agent session.
    execution = entry.get("diagnostics", {}).get("entries", [])
    if (
        not entry.get("sessionId")
        and entry.get("status") == "ok"
        and not delivery.get("fallbackUsed", False)
        and any(
            d.get("source") == "exec"
            and d.get("exitCode") == 0
            and not d.get("truncated", False)
            for d in execution
        )
        and delivery.get("intended", {}).get("source") == "explicit"
    ):
        return route_fields(delivery["intended"])
    return {}


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
                if entry.get("ts", 0) < publication["prepared_at"].timestamp() * 1000:
                    continue
                resolved = delivered_route(entry)
                if resolved != publication["route"] or entry.get("status") != "ok":
                    continue
                if (
                    entry.get("delivered") is True
                    and entry.get("deliveryStatus") == "delivered"
                ):
                    if entry.get("summary", "").strip() != text:
                        continue
                    # Native command history preserves full stdout; require exact equality.
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


def thread_parts(text: str, limit: int = 3000) -> list[str]:
    """Bound each send below Slack chunking limits without splitting links or lines."""
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(line.encode()) > limit:
            raise ValueError("A digest line exceeds the Slack message size budget")
        if current and len((current + line).encode()) > limit:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    return parts


def slack_send(route: dict, text: str, folder, artifact: str, *, parent=None) -> dict:
    """No automatic send retry: a timeout may follow a successful Slack write."""
    import re

    argv = [
        "openclaw",
        "message",
        "send",
        "--channel",
        "slack",
        "--target",
        route["to"],
        "--message",
        text,
        "--json",
    ]
    if route.get("accountId"):
        argv.extend(["--account", route["accountId"]])
    if parent:
        argv.extend(["--reply-to", parent])
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=90, check=True
    )
    response = json.loads(result.stdout)
    store.json_artifact(folder, artifact, response)
    payload = response.get("payload", {})
    receipt = payload.get("result", {})
    message_id = receipt.get("messageId", "")
    channel_id = route["to"].removeprefix("channel:")
    if (
        response.get("dryRun") is True
        or payload.get("ok") is not True
        or receipt.get("channelId") != channel_id
        or not re.fullmatch(r"\d+\.\d+", str(message_id))
    ):
        raise ValueError(
            "Slack did not confirm the intended message; inspect its saved receipt"
        )
    return {"message_id": message_id, "channel_id": channel_id, "thread_id": parent}


def save_thread_receipt(digest: str, receipt: dict, state: str) -> None:
    with store.connect() as conn:
        conn.execute(
            "UPDATE minerva_ideas.publications SET receipt=%s,state=%s WHERE digest=%s",
            (Jsonb(receipt), state, digest),
        )


def publish_thread(run_id: UUID, job_id: UUID) -> dict | None:
    """Caller holds the run lock. Confirmed duplicates are silent; ambiguity blocks retry."""
    from datetime import datetime, timezone

    prepared = prepare_publication(run_id, job_id, threaded=True)
    if prepared is None:
        return None
    title, _, body = prepared["text"].partition("\n\n")
    parts = thread_parts(body)
    folder = store.run_folder(store.get_run(run_id))
    digest, route = prepared["digest"], prepared["route"]
    receipt = {
        "format": "manager-thread-v1",
        "route": route,
        "parent": None,
        "replies": [],
    }
    try:
        receipt["inflight"] = "parent"
        save_thread_receipt(digest, receipt, "sending")
        receipt["parent"] = slack_send(
            route, title, folder, f"publications/{digest}.parent.json"
        )
        receipt["inflight"] = None
        save_thread_receipt(digest, receipt, "sending")
        for index, part in enumerate(parts):
            receipt["inflight"] = f"reply-{index}"
            save_thread_receipt(digest, receipt, "sending")
            receipt["replies"].append(
                slack_send(
                    route,
                    part,
                    folder,
                    f"publications/{digest}.reply-{index}.json",
                    parent=receipt["parent"]["message_id"],
                )
            )
            receipt["inflight"] = None
            save_thread_receipt(digest, receipt, "sending")
        receipt["delivered_at"] = datetime.now(timezone.utc).isoformat()
        save_thread_receipt(digest, receipt, "delivered")
        return receipt
    except Exception:
        save_thread_receipt(digest, receipt, "unknown")
        raise ValueError(
            "Slack thread publication is incomplete or uncertain; inspect saved receipts and the thread before retrying. No automatic resend."
        ) from None
