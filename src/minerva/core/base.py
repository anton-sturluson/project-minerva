"""Base classes for graph nodes and relations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from neo4j import AsyncSession
from pydantic import BaseModel, Field

from minerva.core.util import camel_to_snake
if TYPE_CHECKING:
    from minerva.kb.driver import Neo4jDriver


class BaseNode(BaseModel):
    """Base class for all graph nodes."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    async def create(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ):
        """
        Create this node in the graph. Must be implemented by subclasses.

        Args:
            driver: Neo4j driver (creates temp session if session not provided)
            session: Existing session (prioritized if provided)
        """
        raise NotImplementedError

    async def _run_query(
        self,
        query: str,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
        **params,
    ):
        """Helper to run query with session or driver."""
        if session:
            await session.run(query, params)
        elif driver:
            await driver.run(query, params)
        else:
            raise ValueError("Must provide either driver or session")

    @property
    def type(self) -> str:
        return type(self).__name__.replace('Node', '')


class BaseRelation(BaseModel):
    """Base class for all graph relationships."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    from_id: str
    to_id: str

    async def create(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ):
        """
        Create this relation in the graph. Must be implemented by subclasses.

        Args:
            driver: Neo4j driver (creates temp session if session not provided)
            session: Existing session (prioritized if provided)
        """
        raise NotImplementedError

    async def _run_query(
        self,
        query: str,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
        **params,
    ):
        """Helper to run query with session or driver."""
        if session:
            await session.run(query, params)
        elif driver:
            await driver.run(query, params)
        else:
            raise ValueError("Must provide either driver or session")
    
    @property
    def type(self) -> str:
        snake: str = camel_to_snake(type(self).__name__).upper()
        suffix: str = "_RELATION"
        if snake.endswith(suffix):
            snake = snake[: -len(suffix)]
        return snake
