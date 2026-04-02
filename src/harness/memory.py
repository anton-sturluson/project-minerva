"""Workspace-scoped memory storage for the investment harness."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from pathlib import Path
from typing import Any

from harness.config import HarnessSettings, get_settings


def get_memory_db_path(settings: HarnessSettings | None = None) -> Path:
    """Return the workspace-local SQLite path for harness memory."""
    active_settings: HarnessSettings = settings or get_settings()
    workspace_root: Path = active_settings.ensure_workspace_root()
    db_path: Path = workspace_root / ".minerva" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_db(settings: HarnessSettings | None = None) -> None:
    """Create the memory database and required tables if absent."""
    db_path: Path = get_memory_db_path(settings)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                embedding BLOB
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY,
                summary TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                embedding BLOB
            )
            """
        )
        conn.commit()


def store_fact(content: str, settings: HarnessSettings | None = None) -> int:
    """Persist a memory fact and return its row id."""
    init_db(settings)
    embedding: bytes | None = _embed_text(content)
    with sqlite3.connect(get_memory_db_path(settings)) as conn:
        cursor = conn.execute(
            "INSERT INTO facts (content, embedding) VALUES (?, ?)",
            (content, embedding),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_facts(settings: HarnessSettings | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Return facts ordered from newest to oldest."""
    init_db(settings)
    query: str = "SELECT id, content, created_at, embedding FROM facts ORDER BY id DESC"
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with sqlite3.connect(get_memory_db_path(settings)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_fact(row) for row in rows]


def recent_facts(limit: int = 10, settings: HarnessSettings | None = None) -> list[dict[str, Any]]:
    """Return the most recent facts."""
    return list_facts(settings=settings, limit=limit)


def forget_fact(fact_id: int, settings: HarnessSettings | None = None) -> bool:
    """Delete a fact by id."""
    init_db(settings)
    with sqlite3.connect(get_memory_db_path(settings)) as conn:
        cursor = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        conn.commit()
        return cursor.rowcount > 0


def search_facts_text(query: str, settings: HarnessSettings | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Search facts with a case-insensitive LIKE query."""
    init_db(settings)
    pattern: str = f"%{query}%"
    with sqlite3.connect(get_memory_db_path(settings)) as conn:
        rows = conn.execute(
            """
            SELECT id, content, created_at, embedding
            FROM facts
            WHERE content LIKE ? COLLATE NOCASE
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
    return [_row_to_fact(row) for row in rows]


def search_facts(query: str, settings: HarnessSettings | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Search facts semantically when embeddings are available, else use text search."""
    init_db(settings)
    query_embedding: list[float] | None = _embed_text_vector(query)
    if query_embedding is None:
        return search_facts_text(query, settings=settings, limit=limit)

    facts: list[dict[str, Any]] = list_facts(settings=settings)
    scored: list[dict[str, Any]] = []
    for fact in facts:
        vector: list[float] | None = fact.get("embedding")
        if not vector:
            continue
        scored.append({**fact, "score": _cosine_similarity(query_embedding, vector)})

    if not scored:
        return search_facts_text(query, settings=settings, limit=limit)

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _row_to_fact(row: tuple[Any, ...]) -> dict[str, Any]:
    embedding: list[float] | None = None
    if row[3]:
        embedding = json.loads(row[3].decode("utf-8"))
    return {
        "id": row[0],
        "content": row[1],
        "created_at": row[2],
        "embedding": embedding,
    }


def _embed_text(text: str) -> bytes | None:
    vector: list[float] | None = _embed_text_vector(text)
    if vector is None:
        return None
    return json.dumps(vector).encode("utf-8")


def _embed_text_vector(text: str) -> list[float] | None:
    api_key: str | None = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import openai
    except ImportError:
        return None

    client = openai.OpenAI(api_key=api_key)
    response = client.embeddings.create(model="text-embedding-3-small", input=text)
    return list(response.data[0].embedding)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot: float = sum(x * y for x, y in zip(a, b, strict=False))
    a_norm: float = math.sqrt(sum(x * x for x in a))
    b_norm: float = math.sqrt(sum(y * y for y in b))
    if a_norm == 0 or b_norm == 0:
        return -1.0
    return dot / (a_norm * b_norm)
