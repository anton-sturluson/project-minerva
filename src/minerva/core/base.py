"""Base classes for graph nodes and relations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from minerva.core.util import camel_to_snake


class BaseNode(BaseModel):
    """Base class for all graph nodes."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_params(self) -> dict[str, Any]:
        """
        Convert node to Neo4j-ready parameter dictionary.

        Returns:
            Dictionary with all fields converted for Neo4j storage
        """
        data: dict[str, Any] = self.model_dump()
        data["created_at"] = self.created_at.isoformat()
        return data

    @property
    def type(self) -> str:
        return type(self).__name__.replace("Node", "")


class BaseRelation(BaseModel):
    """Base class for all graph relationships."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    from_id: str
    to_id: str

    def to_neo4j_params(self) -> dict[str, Any]:
        """
        Convert relation to Neo4j-ready parameter dictionary.

        Returns:
            Dictionary with all fields converted for Neo4j storage
        """
        data: dict[str, Any] = self.model_dump()
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        """
        Get metadata needed for constructing Neo4j queries.
        Must be implemented by subclasses.

        Returns:
            Dictionary with:
                - from_label: Source node label (e.g., "Entity")
                - to_label: Target node label (e.g., "Topic")
                - properties: List of property names (excluding from_id, to_id)
        """
        raise NotImplementedError

    @property
    def type(self) -> str:
        snake: str = camel_to_snake(type(self).__name__).upper()
        suffix: str = "_RELATION"
        if snake.endswith(suffix):
            snake = snake[: -len(suffix)]
        return snake
