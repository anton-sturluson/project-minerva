"""Original-source weekly research inside the primary Minerva CLI."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID
from functools import wraps

import httpx
import subprocess
import psycopg
import typer
from harness.ideas import store

app = typer.Typer(no_args_is_help=True, help="Research weekly leads from original manager documents.")


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, OSError, psycopg.Error, httpx.HTTPError, subprocess.SubprocessError) as exc:
            # Connection errors may contain DSNs. Never echo driver details.
            message = "Postgres operation failed; check MINERVA_DATABASE_URL and database access." if isinstance(exc, psycopg.Error) else str(exc)
            typer.echo(message, err=True)
            raise typer.Exit(1) from None
    return call


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, default=str))


@app.command("init")
@guarded
def initialize():
    """Create only the minerva_ideas schema in the configured Postgres database."""
    store.initialize()
    emit({"schema":"minerva_ideas","status":"ready"})


@app.command("import")
@guarded
def import_issue(path: Path, run_id: UUID | None = typer.Option(None)):
    """Import a discovery roster JSON; --run-id makes retries idempotent."""
    result = store.import_issue(json.loads(path.read_text()), run_id=run_id)
    emit(store.status(result))


@app.command("status")
@guarded
def status(run_id: UUID):
    """Return persisted progress and explicit research gaps as JSON."""
    emit(store.status(run_id))


@app.command("source")
@guarded
def source(run_id: UUID, ordinal: int, url: str):
    """Archive an original document candidate; this does not approve its thesis."""
    from harness.ideas.documents import attach
    emit(attach(run_id,ordinal,url))
