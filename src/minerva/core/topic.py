"""Topic management and orchestration."""

import asyncio

from minerva.core.community import CommunityDetector, CommunityHierarchy
from minerva.core.node import EntityNode, TopicNode
from minerva.core.relation import BelongsToRelation, RelatesToRelation
from minerva.kb.driver import Neo4jDriver
from minerva.prompt.model import TopicSummary


class TopicManager:
    """Orchestrator for topic detection and management."""

    def __init__(
        self,
        driver: Neo4jDriver,
        algorithm: CommunityDetector,
    ):
        """
        Initialize topic manager.

        Args:
            driver: Neo4j driver for graph operations
            algorithm: Community detection algorithm to use
        """
        self.driver: Neo4jDriver = driver
        self.algorithm: CommunityDetector = algorithm

    async def detect(self, **kwargs) -> CommunityHierarchy:
        """
        Detect topics in the knowledge graph and generate summaries.

        Args:
            **kwargs: Additional arguments to pass to the detection algorithm
                     (e.g., threshold_selector for HLCDetector)

        Returns:
            CommunityHierarchy with fully summarized topics
        """
        entities: list[EntityNode] = await self._get_entities()
        relations: list[RelatesToRelation] = await self._get_relations()

        hierarchy: CommunityHierarchy = await self.algorithm.detect(
            entities, relations, **kwargs
        )

        await self.driver.bulk_create_nodes(hierarchy.topics)
        await self.driver.bulk_create_relations(
            hierarchy.subtopic_relations + hierarchy.belongs_to_relations
        )
        await self.driver.bulk_update_relations(hierarchy.updated_relations)

        await self._generate_summaries(hierarchy.topics)

        return hierarchy

    async def assign(self, entity: EntityNode) -> str:
        """
        Assign entity to existing topic.

        Args:
            entity: Entity to assign

        Returns:
            ID of assigned topic
        """
        topics: list[TopicNode] = await self._get_all_topics()
        topic_id: str = await self.algorithm.assign(entity, topics)

        await self.driver.bulk_create_relations(
            [BelongsToRelation(from_id=entity.id, to_id=topic_id)]
        )

        return topic_id

    async def _get_entities(self) -> list[EntityNode]:
        """Fetch all entities from the graph."""
        results: list[dict] = await self.driver.query("MATCH (e:Entity) RETURN e")
        return [
            EntityNode(
                id=r["e"]["id"],
                name=r["e"]["name"],
                name_embedding=r["e"]["name_embedding"],
            )
            for r in results
        ]

    async def _get_relations(self) -> list[RelatesToRelation]:
        """Fetch all relations from the graph."""
        results: list[dict] = await self.driver.query(
            """
            MATCH (e1:Entity)-[r:RELATES_TO]->(e2:Entity)
            RETURN r, e1.id as from_id, e2.id as to_id
            """
        )
        return [
            RelatesToRelation(
                id=r["r"]["id"],
                from_id=r["from_id"],
                to_id=r["to_id"],
                relation_type=r["r"]["relation_type"],
                fact=r["r"]["fact"],
                fact_embedding=r["r"]["fact_embedding"],
                sources=r["r"]["sources"],
                contradictory_relations=r["r"]["contradictory_relations"],
            )
            for r in results
        ]

    async def _get_all_topics(self) -> list[TopicNode]:
        """Fetch all topics."""
        results: list[dict] = await self.driver.query("MATCH (t:Topic) RETURN t")
        return [
            TopicNode(
                id=r["t"]["id"],
                name=r["t"]["name"],
                summary=r["t"]["summary"],
                summary_embedding=r["t"]["summary_embedding"],
                level=r["t"]["level"],
            )
            for r in results
        ]

    async def _generate_summaries(self, topics: list[TopicNode]):
        """Generate summaries for all topics in parallel (level by level)."""
        if not topics:
            return

        topics_by_level: dict[int, list[TopicNode]] = {}
        for topic in topics:
            if topic.level not in topics_by_level:
                topics_by_level[topic.level] = []
            topics_by_level[topic.level].append(topic)

        max_level: int = max(topics_by_level.keys())

        for level in range(max_level + 1):
            if level not in topics_by_level:
                continue

            level_topics: list[TopicNode] = topics_by_level[level]

            summaries: list[TopicSummary] = await asyncio.gather(
                *[topic.summarize(driver=self.driver) for topic in level_topics]
            )

            update_data: list[dict] = [
                {"id": topic.id, "name": summary.name, "summary": summary.summary}
                for topic, summary in zip(level_topics, summaries)
            ]

            for topic, summary in zip(level_topics, summaries):
                topic.name = summary.name
                topic.summary = summary.summary

            await self._bulk_update_topic_summaries(update_data)

    async def _bulk_update_topic_summaries(self, update_data: list[dict]):
        """Bulk update topic names and summaries."""
        for data in update_data:
            await self.driver.query(
                """
                MATCH (t:Topic {id: $id})
                SET t.name = $name, t.summary = $summary
                """,
                data,
            )
