"""Neo4j driver for knowledge graph operations."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncResult

from minerva.core.node import EntityNode, TopicNode
if TYPE_CHECKING:
    from minerva.core.base import BaseNode, BaseRelation


class Neo4jDriver:
    """Simple Neo4j driver for bulk graph operations."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
    ):
        self.uri: str = uri
        self.user: str = user
        self.password: str = password
        self.database: str = database
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def bulk_create_nodes(self, nodes: list[BaseNode]) -> None:
        """
        Bulk create nodes in the graph using UNWIND for efficiency.

        Args:
            nodes: List of node objects
        """
        if not nodes:
            return

        from collections import defaultdict
        nodes_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for node in nodes:
            node_type: str = node.type
            node_data: dict[str, Any] = node.model_dump()
            node_data['created_at'] = node.created_at.isoformat()
            nodes_by_type[node_type].append(node_data)

        async with self.driver.session(database=self.database) as session:
            for node_type, node_list in nodes_by_type.items():
                await session.run(
                    f"""
                    UNWIND $nodes AS node
                    CREATE (n:{node_type})
                    SET n = node
                    SET n.created_at = datetime(node.created_at)
                    """,
                    {'nodes': node_list}
                )

    async def bulk_create_relations(self, relations: list[BaseRelation]) -> None:
        """
        Bulk create relationships in the graph using UNWIND for efficiency.

        Args:
            relations: List of relation objects
        """
        if not relations:
            return

        from collections import defaultdict
        relations_by_class: dict[type, list[dict[str, Any]]] = defaultdict(list)

        for relation in relations:
            relation_class: type = type(relation)
            relation_data: dict[str, Any] = relation.model_dump()
            relation_data['created_at'] = relation.created_at.isoformat()
            relations_by_class[relation_class].append(relation_data)

        async with self.driver.session(database=self.database) as session:
            for relation_class, relation_list in relations_by_class.items():
                sample_relation: BaseRelation = relation_class(**relation_list[0])
                relation_type: str = sample_relation.type

                all_fields: set[str] = set(relation_list[0].keys())
                base_fields: set[str] = {'id', 'created_at', 'from_id', 'to_id', 'type'}
                property_fields: list[str] = sorted(all_fields - base_fields)

                properties: str = ', '.join([
                    f'{field}: rel.{field}' for field in ['id', 'created_at'] + property_fields
                ])

                query: str = f"""
                UNWIND $relations AS rel
                MATCH (from_node {{id: rel.from_id}})
                MATCH (to_node {{id: rel.to_id}})
                CREATE (from_node)-[r:{relation_type} {{{properties}}}]->(to_node)
                SET r.created_at = datetime(rel.created_at)
                """

                await session.run(query, {'relations': relation_list})

    async def create_vector_indexes(self) -> None:
        """Create vector indexes for embedding fields."""
        async with self.driver.session(database=self.database) as session:
            await session.run(
                """
                CREATE VECTOR INDEX entity_name_embedding IF NOT EXISTS
                FOR (n:Entity)
                ON n.name_embedding
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 10,
                    `vector.similarity_function`: 'cosine'
                }}
                """
            )

            await session.run(
                """
                CREATE VECTOR INDEX fact_embedding IF NOT EXISTS
                FOR ()-[r:RELATES_TO]-()
                ON r.fact_embedding
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 10,
                    `vector.similarity_function`: 'cosine'
                }}
                """
            )

    async def clear_graph(self) -> None:
        """Delete all nodes and relationships in the graph."""
        async with self.driver.session(database=self.database) as session:
            await session.run("MATCH (n) DETACH DELETE n")

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Execute a Cypher query.

        Args:
            cypher: Cypher query string
            params: Query parameters

        Returns:
            List of result records as dictionaries
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(cypher, params or {})
            records: list[dict[str, Any]] = [dict(record) async for record in result]
            return records

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        await self.driver.close()

    async def find_similar_entities(
        self, name_embedding: list[float], limit: int = 10, threshold: float = 0.9
    ) -> list[EntityNode]:
        """Find similar entities using vector similarity search."""
        async with self.driver.session(database=self.database) as session:
            result: AsyncResult = await session.run(
                """
                CALL db.index.vector.queryNodes('entity_name_embedding', $limit, $embedding) YIELD node, score
                WHERE score >= $threshold
                RETURN node, score
                """,
                limit=limit,
                embedding=name_embedding,
                threshold=threshold,
            )
            records: list[dict[str, Any]] = [dict(record) async for record in result]
            return [
                EntityNode(
                    id=record["node"]["id"],
                    name=record["node"]["name"],
                    name_embedding=record["node"]["name_embedding"],
                    summary=record["node"]["summary"],
                )
                for record in records
            ]

    async def get_entities(self, topic_id: str) -> list[EntityNode]:
        """Get all entities belonging to a topic."""
        results: list[dict[str, Any]] = await self.query(
            """
            MATCH (e:Entity)-[:BELONGS_TO]->(t:Topic {id: $topic_id})
            RETURN e
            """,
            {"topic_id": topic_id},
        )
        return [
            EntityNode(
                id=r["e"]["id"],
                name=r["e"]["name"],
                name_embedding=r["e"]["name_embedding"],
                summary=r["e"]["summary"],
            )
            for r in results
        ]

    async def get_hierarchy(self, root_id: str | None = None) -> dict[str, Any]:
        """
        Get topic hierarchy as a nested dictionary.

        Args:
            root_id: Optional root topic ID. If None, returns all root topics.

        Returns:
            Nested dictionary representing the hierarchy
        """
        if root_id:
            query: str = """
                MATCH (root:Topic {id: $root_id})
                OPTIONAL MATCH path = (root)-[:IS_SUBTOPIC*]->(child:Topic)
                WITH root, collect(DISTINCT child) as children
                RETURN root, children
            """
            params: dict[str, Any] = {"root_id": root_id}
        else:
            query: str = """
                MATCH (root:Topic)
                WHERE NOT (:Topic)-[:IS_SUBTOPIC]->(root)
                OPTIONAL MATCH path = (root)-[:IS_SUBTOPIC*]->(child:Topic)
                WITH root, collect(DISTINCT child) as children
                RETURN root, children
            """
            params: dict[str, Any] = {}

        results: list[dict[str, Any]] = await self.query(query, params)

        if not results:
            return {}

        hierarchy: dict[str, Any] = {}
        for r in results:
            root_data: dict[str, Any] = r["root"]
            hierarchy[root_data["id"]] = {
                "id": root_data["id"],
                "name": root_data["name"],
                "summary": root_data["summary"],
                "level": root_data["level"],
                "children": [child["id"] for child in r["children"]]
                if r["children"]
                else [],
            }

        return hierarchy

    async def get_topics(self, entity_id: str) -> list[TopicNode]:
        """Get all topics an entity belongs to."""
        results: list[dict[str, Any]] = await self.query(
            """
            MATCH (e:Entity {id: $entity_id})-[:BELONGS_TO]->(t:Topic)
            RETURN t
            """,
            {"entity_id": entity_id},
        )
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

    async def get_children(self, topic_id: str) -> list[TopicNode]:
        """Get all child topics of a parent topic."""
        results: list[dict[str, Any]] = await self.query(
            """
            MATCH (parent:Topic {id: $topic_id})-[:IS_SUBTOPIC]->(child:Topic)
            RETURN child
            """,
            {"topic_id": topic_id},
        )
        return [
            TopicNode(
                id=r["child"]["id"],
                name=r["child"]["name"],
                summary=r["child"]["summary"],
                summary_embedding=r["child"]["summary_embedding"],
                level=r["child"]["level"],
            )
            for r in results
        ]

    async def get_parent(self, topic_id: str) -> TopicNode | None:
        """Get parent topic of a child topic."""
        results: list[dict[str, Any]] = await self.query(
            """
            MATCH (parent:Topic)-[:IS_SUBTOPIC]->(child:Topic {id: $topic_id})
            RETURN parent
            """,
            {"topic_id": topic_id},
        )
        if not results:
            return None

        r: dict[str, Any] = results[0]
        return TopicNode(
            id=r["parent"]["id"],
            name=r["parent"]["name"],
            summary=r["parent"]["summary"],
            summary_embedding=r["parent"]["summary_embedding"],
            level=r["parent"]["level"],
        )
