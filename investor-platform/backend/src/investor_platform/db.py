"""Database connections and the single local identity boundary."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

LOCAL_OWNER: UUID = UUID("00000000-0000-4000-8000-000000000001")
LOCAL_WORKSPACE: UUID = UUID("00000000-0000-4000-8000-000000000002")
DEFAULT_URL: str = "postgresql+psycopg://minerva:minerva-local-only@127.0.0.1:55432/minerva"


def database_url() -> str:
    """Read the configured database URL, using the local development default."""
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def make_engine(url: str | URL | None = None) -> Engine:
    """Build the local database pool with bounded connection startup."""
    return create_engine(
        url or database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )


@dataclass(frozen=True)
class Actor:
    """Authenticated owner and workspace used to scope every portfolio operation."""

    owner_id: UUID
    workspace_id: UUID


def get_actor(request: Request) -> Actor:
    """Resolve the single local owner after the HTTP access boundary succeeds."""
    if not getattr(request.state, "authenticated", False):
        raise HTTPException(status_code=403, detail="Access denied")
    return Actor(LOCAL_OWNER, LOCAL_WORKSPACE)


def get_session(request: Request) -> Iterator[Session]:
    """Keep a database session open for one request, rolling back uncommitted work."""
    with Session(request.app.state.engine) as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
