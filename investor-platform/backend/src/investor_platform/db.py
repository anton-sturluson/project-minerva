"""Database connections and the single local identity boundary."""

import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

LOCAL_OWNER = UUID("00000000-0000-4000-8000-000000000001")
LOCAL_WORKSPACE = UUID("00000000-0000-4000-8000-000000000002")
DEFAULT_URL = "postgresql+psycopg://minerva:minerva-local-only@127.0.0.1:55432/minerva"


def database_url():
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def make_engine(url=None):
    return create_engine(
        url or database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )


@dataclass(frozen=True)
class Actor:
    owner_id: UUID
    workspace_id: UUID


def get_actor(request: Request) -> Actor:
    if not getattr(request.state, "authenticated", False):
        raise HTTPException(status_code=403, detail="Access denied")
    return Actor(LOCAL_OWNER, LOCAL_WORKSPACE)


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
