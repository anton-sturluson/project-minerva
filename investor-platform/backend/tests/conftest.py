import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from investor_platform.app import app
from investor_platform.db import DEFAULT_URL


@pytest.fixture
def database():
    # Each test gets a fresh schema. Never truncate the user's portfolio.
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_URL)
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        config = Config("alembic.ini")
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def db_client(database):
    app.state.engine = database
    try:
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
