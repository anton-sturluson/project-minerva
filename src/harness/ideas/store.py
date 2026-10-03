"""Two workflow tables; report artifacts are ordinary files, never database blobs."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS minerva_ideas;
CREATE TABLE IF NOT EXISTS minerva_ideas.runs (
    id uuid PRIMARY KEY,
    issue_url text NOT NULL,
    issue_date date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS minerva_ideas.items (
    run_id uuid NOT NULL REFERENCES minerva_ideas.runs(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    company text NOT NULL,
    fund text NOT NULL,
    symbol text NOT NULL DEFAULT '',
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','sourced','ready','gap','failed')),
    error text,
    PRIMARY KEY (run_id, ordinal)
);
ALTER TABLE minerva_ideas.items ADD COLUMN IF NOT EXISTS document jsonb;
ALTER TABLE minerva_ideas.items ADD COLUMN IF NOT EXISTS view jsonb;
CREATE TABLE IF NOT EXISTS minerva_ideas.publications (
    digest text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES minerva_ideas.runs(id),
    job_id uuid NOT NULL,
    state text NOT NULL CHECK(state IN ('sending','delivered','unknown')),
    route jsonb NOT NULL,
    prepared_at timestamptz NOT NULL DEFAULT now(),
    receipt jsonb
);
"""


def root() -> Path:
    return Path(
        os.environ.get("MINERVA_IDEAS_ROOT", "hard-disk/reports/05-weekly-ideas")
    ).resolve()


def connect():
    dsn = os.environ.get("MINERVA_DATABASE_URL")
    if not dsn:
        raise ValueError(
            "Set MINERVA_DATABASE_URL to the shared Postgres connection; credentials are never logged."
        )
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10)


def initialize() -> None:
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(719234001)")
        conn.execute(SCHEMA)


def write_artifact(folder: Path, relative: str, payload: bytes) -> str:
    """Finish an immutable file before a caller commits its database reference."""
    path = folder / relative
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(
                f"Artifact already exists with different content: {relative}"
            )
        return relative
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link creation is atomic and cannot overwrite a concurrent writer.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError(f"Concurrent artifact conflict: {relative}")
    finally:
        temporary.unlink(missing_ok=True)
    return relative


def json_artifact(folder: Path, relative: str, value) -> str:
    return write_artifact(
        folder,
        relative,
        (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode(),
    )


def run_folder(run: dict) -> Path:
    return root() / str(run["issue_date"]) / "runs" / str(run["id"])


def get_run(run_id: UUID) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM minerva_ideas.runs WHERE id=%s", (run_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown run: {run_id}")
    return row


def items(run_id: UUID) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM minerva_ideas.items WHERE run_id=%s ORDER BY ordinal",
            (run_id,),
        ).fetchall()


def import_issue(issue: dict, *, run_id: UUID | None = None) -> UUID:
    from harness.ideas.roster import Issue

    parsed = Issue.model_validate(issue)
    run_id = run_id or uuid4()
    run = {"id": run_id, "issue_date": parsed.date}
    # Archive first. A crash can leave unregistered files, never a partial DB roster.
    json_artifact(
        run_folder(run), "research/issue.json", parsed.model_dump(mode="json")
    )
    with connect() as conn:
        inserted = conn.execute(
            "INSERT INTO minerva_ideas.runs(id,issue_url,issue_date) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
            (run_id, parsed.url, parsed.date),
        ).fetchone()
        if inserted:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO minerva_ideas.items(run_id,ordinal,company,fund,symbol) VALUES(%s,%s,%s,%s,%s)",
                    [
                        (run_id, n, row.company, row.fund, row.symbol)
                        for n, row in enumerate(parsed.roster, 1)
                    ],
                )
        else:
            current = conn.execute(
                "SELECT issue_url,issue_date FROM minerva_ideas.runs WHERE id=%s",
                (run_id,),
            ).fetchone()
            if current != {"issue_url": parsed.url, "issue_date": parsed.date}:
                raise ValueError("Run ID belongs to another issue")
    return run_id


def status(run_id: UUID | None = None) -> dict:
    if run_id is None:
        with connect() as conn:
            latest = conn.execute(
                "SELECT id FROM minerva_ideas.runs ORDER BY issue_date DESC,created_at DESC LIMIT 1"
            ).fetchone()
        if latest is None:
            raise ValueError("No weekly ideas runs yet; use minerva ideas run")
        run_id = latest["id"]
    run = get_run(run_id)
    rows = items(run_id)
    counts = {
        state: sum(r["state"] == state for r in rows)
        for state in ("pending", "sourced", "ready", "gap", "failed")
    }
    with connect() as conn:
        publications = conn.execute(
            "SELECT digest,job_id,state,route,receipt FROM minerva_ideas.publications WHERE run_id=%s ORDER BY prepared_at DESC",
            (run_id,),
        ).fetchall()
    return {
        "run_id": str(run_id),
        "issue_date": str(run["issue_date"]),
        "roster": len(rows),
        "counts": counts,
        "publications": publications,
        "artifact_dir": str(run_folder(run)),
        "gaps": [
            {
                "ordinal": r["ordinal"],
                "company": r["company"],
                "fund": r["fund"],
                "reason": r["error"],
            }
            for r in rows
            if r["state"] in ("gap", "failed")
        ],
    }


@contextmanager
def run_lock(run_id: UUID):
    """A session lock releases automatically on process exit or connection loss."""
    key = int.from_bytes(
        hashlib.sha256(str(run_id).encode()).digest()[:8], "big", signed=True
    )
    with connect() as conn:
        conn.autocommit = True
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS locked", (key,)
        ).fetchone()["locked"]
        if not acquired:
            raise ValueError("This run is already being processed")
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
