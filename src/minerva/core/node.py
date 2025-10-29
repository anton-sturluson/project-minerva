"""Node models for the knowledge graph."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from neo4j import AsyncResult, AsyncSession

from minerva.core.base import BaseNode
from minerva.prompt.entity import summarize_entity
from minerva.prompt.model import TopicSummary
from minerva.prompt.topic import summarize_leaf_topic, summarize_parent_topic

if TYPE_CHECKING:
    from minerva.kb.driver import Neo4jDriver


class SourceNode(BaseNode):
    """Source document node containing original text."""

    content: str


class EntityNode(BaseNode):
    """Entity node representing a concept or object."""

    name: str
    name_embedding: list[float]
    summary: str

    async def summarize(self, driver: Neo4jDriver) -> str:
        """
        Generate summary for this entity based on 1-hop relations.

        Args:
            driver: Neo4j driver for querying relations

        Returns:
            Generated summary string
        """
        results: list[dict] = await driver.query(
            """
            MATCH (e:Entity {id: $entity_id})-[r:RELATES_TO]-(neighbor:Entity)
            RETURN neighbor.name as neighbor_name,
                   r.relation_type as relation_type,
                   r.fact as fact,
                   CASE
                     WHEN startNode(r) = e THEN 'outgoing'
                     ELSE 'incoming'
                   END as direction
            """,
            {"entity_id": self.id},
        )

        relations: list[dict] = [
            {
                "neighbor_name": r["neighbor_name"],
                "relation_type": r["relation_type"],
                "fact": r["fact"],
                "direction": r["direction"],
            }
            for r in results
        ]

        summary: str = await summarize_entity(
            entity_name=self.name,
            relations=relations,
        )

        self.summary = summary
        return summary


class TopicNode(BaseNode):
    """Topic node for categorizing entities."""

    name: str
    summary: str
    summary_embedding: list[float]
    level: int

    async def get_entities(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ) -> list[EntityNode]:
        """Fetch all entities belonging to this topic."""
        query: str = """
            MATCH (e:Entity)-[:BELONGS_TO]->(t:Topic {id: $topic_id})
            RETURN e
            """
        params: dict = {"topic_id": self.id}

        if session:
            results: AsyncResult = await session.run(query, params)
            records: list[dict] = [dict(record) async for record in results]
        elif driver:
            records: list[dict] = await driver.query(query, params)
        else:
            raise ValueError("Must provide either driver or session")

        return [
            EntityNode(
                id=r["e"]["id"],
                name=r["e"]["name"],
                name_embedding=r["e"]["name_embedding"],
                summary=r["e"]["summary"],
            )
            for r in records
        ]

    async def get_relations(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """Fetch all relations between entities in this topic."""
        query: str = """
            MATCH (e1:Entity)-[:BELONGS_TO]->(t:Topic {id: $topic_id})
            MATCH (e2:Entity)-[:BELONGS_TO]->(t)
            MATCH (e1)-[r:RELATES_TO]->(e2)
            RETURN e1.name as from_name, e2.name as to_name, r.relation_type as relation_type, r.fact as fact
            """
        params: dict = {"topic_id": self.id}

        if session:
            results = await session.run(query, params)
            return [dict(record) async for record in results]
        elif driver:
            return await driver.query(query, params)
        else:
            raise ValueError("Must provide either driver or session")

    async def get_children(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ) -> list["TopicNode"]:
        """Fetch all child topics of this topic."""
        query: str = """
            MATCH (child:Topic)-[:IS_SUBTOPIC]->(parent:Topic {id: $topic_id})
            RETURN child
            """
        params: dict = {"topic_id": self.id}

        if session:
            results: AsyncResult = await session.run(query, params)
            records: list[dict] = [dict(record) async for record in results]
        elif driver:
            records: list[dict] = await driver.query(query, params)
        else:
            raise ValueError("Must provide either driver or session")

        return [
            TopicNode(
                id=r["child"]["id"],
                name=r["child"]["name"],
                summary=r["child"]["summary"],
                summary_embedding=r["child"]["summary_embedding"],
                level=r["child"]["level"],
            )
            for r in records
        ]

    async def summarize(
        self,
        driver: Neo4jDriver | None = None,
        session: AsyncSession | None = None,
    ) -> TopicSummary:
        """
        Generate summary for this topic with fully parallel data fetching.

        Args:
            driver: Neo4j driver (creates temp session if session not provided)
            session: Existing session (prioritized if provided)

        Returns:
            TopicSummary with name and summary
        """

        if self.level == 0:
            entities, relations = await asyncio.gather(
                self.get_entities(driver=driver, session=session),
                self.get_relations(driver=driver, session=session),
            )
            return await summarize_leaf_topic(entities, relations)
        else:
            children: list["TopicNode"] = await self.get_children(
                driver=driver, session=session
            )
            return await summarize_parent_topic(children)
