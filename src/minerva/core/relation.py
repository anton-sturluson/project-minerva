"""Relation models for the knowledge graph."""

from __future__ import annotations

from typing import Any

from neo4j import AsyncSession

from minerva.core.base import BaseRelation
from minerva.kb.driver import Neo4jDriver


class MentionsRelation(BaseRelation):
    """Relation from Source to Entity indicating the source mentions the entity."""

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Source",
            "to_label": "Entity",
            "properties": ["id", "created_at"],
        }

    async def create(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ):
        """Create this MENTIONS relation in the graph."""
        await self._run_query(
            """
            MATCH (s:Source {id: $from_id})
            MATCH (e:Entity {id: $to_id})
            CREATE (s)-[r:MENTIONS {
                id: $id,
                created_at: datetime($created_at)
            }]->(e)
            """,
            driver=driver,
            session=session,
            id=self.id,
            created_at=self.created_at.isoformat(),
            from_id=self.from_id,
            to_id=self.to_id,
        )


class RelatesToRelation(BaseRelation):
    """Relation between two Entities describing their relationship."""

    relation_type: str
    fact: str
    fact_embedding: list[float]
    sources: list[str]
    contradictory_relations: list[str]

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Entity",
            "to_label": "Entity",
            "properties": [
                "id",
                "created_at",
                "relation_type",
                "fact",
                "fact_embedding",
                "sources",
                "contradictory_relations",
            ],
        }

    async def create(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ):
        """Create this RELATES_TO relation in the graph."""
        await self._run_query(
            """
            MATCH (e1:Entity {id: $from_id})
            MATCH (e2:Entity {id: $to_id})
            CREATE (e1)-[r:RELATES_TO {
                id: $id,
                created_at: datetime($created_at),
                relation_type: $relation_type,
                fact: $fact,
                fact_embedding: $fact_embedding,
                sources: $sources,
                contradictory_relations: $contradictory_relations
            }]->(e2)
            """,
            driver=driver,
            session=session,
            id=self.id,
            created_at=self.created_at.isoformat(),
            relation_type=self.relation_type,
            fact=self.fact,
            fact_embedding=self.fact_embedding,
            sources=self.sources,
            contradictory_relations=self.contradictory_relations,
            from_id=self.from_id,
            to_id=self.to_id,
        )


class IsSubtopicRelation(BaseRelation):
    """Relation from parent Topic to child Topic."""

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Topic",
            "to_label": "Topic",
            "properties": ["id", "created_at"],
        }

    async def create(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ):
        """Create this IS_SUBTOPIC relation in the graph."""
        await self._run_query(
            """
            MATCH (parent:Topic {id: $from_id})
            MATCH (child:Topic {id: $to_id})
            CREATE (parent)-[r:IS_SUBTOPIC {
                id: $id,
                created_at: datetime($created_at)
            }]->(child)
            """,
            driver=driver,
            session=session,
            id=self.id,
            created_at=self.created_at.isoformat(),
            from_id=self.from_id,
            to_id=self.to_id,
        )


class BelongsToRelation(BaseRelation):
    """Relation from Entity to Topic indicating the entity belongs to the topic."""

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Entity",
            "to_label": "Topic",
            "properties": ["id", "created_at"],
        }

    async def create(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ):
        """Create this BELONGS_TO relation in the graph (using MERGE to prevent duplicates)."""
        await self._run_query(
            """
            MATCH (e:Entity {id: $from_id})
            MATCH (t:Topic {id: $to_id})
            MERGE (e)-[r:BELONGS_TO]->(t)
            ON CREATE SET r.id = $id, r.created_at = datetime($created_at)
            """,
            driver=driver,
            session=session,
            id=self.id,
            created_at=self.created_at.isoformat(),
            from_id=self.from_id,
            to_id=self.to_id,
        )
