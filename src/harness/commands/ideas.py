"""Original-source weekly research inside the primary Minerva CLI."""

from __future__ import annotations

import json
import subprocess
from functools import wraps
from pathlib import Path
from uuid import UUID

import httpx
import psycopg
import typer

from harness.ideas import store
from harness.ideas.model import ModelError

app = typer.Typer(
    no_args_is_help=True, help="Research weekly leads from original manager documents."
)


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (
            ModelError,
            ValueError,
            OSError,
            psycopg.Error,
            httpx.HTTPError,
            subprocess.SubprocessError,
        ) as exc:
            # Connection errors may contain DSNs. Never echo driver details.
            message = (
                "Postgres operation failed; check MINERVA_DATABASE_URL and database access."
                if isinstance(exc, psycopg.Error)
                else str(exc)
            )
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
    emit({"schema": "minerva_ideas", "status": "ready"})


@app.command("import")
@guarded
def import_issue(path: Path, run_id: UUID | None = typer.Option(None)):
    """Import a discovery roster JSON; --run-id makes retries idempotent."""
    result = store.import_issue(json.loads(path.read_text()), run_id=run_id)
    emit(store.status(result))


@app.command("status")
@guarded
def status(run_id: UUID | None = typer.Argument(None)):
    """Return research and delivery state as JSON; defaults to the latest issue."""
    emit(store.status(run_id))


@app.command("source")
@guarded
def source(run_id: UUID, ordinal: int, url: str):
    """Archive an original document candidate; this does not approve its thesis."""
    from harness.ideas.documents import attach

    with store.run_lock(run_id):
        emit(attach(run_id, ordinal, url))


@app.command("research")
@guarded
def research(
    run_id: UUID,
    ordinal: int,
    model: str | None = typer.Option(
        None, help="Override all stage models for this invocation."
    ),
):
    """Find and verify an original manager source: at most 2 searches/6 downloads/3 assessments."""
    from harness.ideas.research import discover

    with store.run_lock(run_id):
        emit(discover(run_id, ordinal, model=model))


@app.command("extract")
@guarded
def extract(
    run_id: UUID,
    ordinal: int,
    model: str | None = typer.Option(
        None, help="Override all stage models for this invocation."
    ),
):
    """Extract and independently review an equity view from its original source."""
    from harness.ideas.extraction import extract as extract_view

    with store.run_lock(run_id):
        emit(extract_view(run_id, ordinal, model=model))


@app.command("run")
@guarded
def run(
    fresh: bool = typer.Option(
        False,
        help="Create a new run and redo all research, preserving previous evidence.",
    ),
    limit: int = typer.Option(50, min=1, max=50),
    model: str | None = typer.Option(
        None, help="Override all stage models for this invocation."
    ),
):
    """Discover the latest issue and research its original manager sources."""
    from harness.ideas.workflow import start

    emit(start(limit=limit, model=model, fresh=fresh))


@app.command("resume")
@guarded
def resume(
    run_id: UUID,
    limit: int = typer.Option(50, min=1, max=50),
    model: str | None = typer.Option(
        None, help="Override all stage models for this invocation."
    ),
    retry_gaps: bool = False,
):
    """Continue incomplete work; completed views and known gaps are skipped."""
    from harness.ideas.workflow import resume as resume_run

    emit(resume_run(run_id, limit=limit, model=model, retry_gaps=retry_gaps))


@app.command("render")
@guarded
def render(run_id: UUID):
    """Print publishable ideas without changing delivery state or calling a model."""
    from harness.ideas.publication import render as render_digest

    typer.echo(render_digest(run_id))


@app.command("prepare")
@guarded
def prepare(run_id: UUID, job_id: UUID):
    """Prepare a single delivery through the named existing OpenClaw job."""
    from harness.ideas.publication import prepare as prepare_digest

    with store.run_lock(run_id):
        typer.echo(prepare_digest(run_id, job_id))


@app.command("reconcile")
@guarded
def reconcile(job_id: UUID):
    """Confirm the exact digest in OpenClaw's durable transport records."""
    from harness.ideas.publication import reconcile as reconcile_delivery

    emit(reconcile_delivery(job_id))


@app.command("weekly")
@guarded
def weekly(
    job_id: UUID,
    model: str | None = typer.Option(
        None, help="Override all stage models for this invocation."
    ),
    limit: int = typer.Option(50, min=1, max=50),
):
    """Scheduled entry point: research and publish one parent with summary replies."""
    from harness.ideas.publication import (
        publish_thread,
    )
    from harness.ideas.publication import (
        reconcile as reconcile_delivery,
    )
    from harness.ideas.workflow import start

    reconcile_delivery(job_id)
    result = start(limit=limit, model=model)
    run_id = UUID(result["run_id"])
    if (
        result["counts"]["failed"]
        or result["counts"]["pending"]
        or result["counts"]["sourced"]
    ):
        raise ValueError(
            f"Research incomplete; resume run {run_id}. No publication prepared."
        )
    with store.run_lock(run_id):
        publish_thread(run_id, job_id)
        typer.echo("NO_REPLY")
