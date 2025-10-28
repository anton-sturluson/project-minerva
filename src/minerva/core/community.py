"""Community detection algorithms for entity clustering."""

from typing import Protocol

import community as community_louvain
import networkx as nx
from pydantic import BaseModel, Field

from minerva.core.node import EntityNode, TopicNode
from minerva.core.relation import (
    BelongsToRelation,
    IsSubtopicRelation,
    RelatesToRelation,
)
from minerva.kb.driver import Neo4jDriver


class CommunityHierarchy(BaseModel):
    """Result of hierarchical community detection."""

    topics: list[TopicNode] = Field(description="All topic nodes in the hierarchy")
    subtopic_relations: list[IsSubtopicRelation] = Field(
        description="Parent-child topic relations"
    )
    belongs_to_relations: list[BelongsToRelation] = Field(
        description="Entity-topic memberships (leaf level only)"
    )
    num_levels: int = Field(description="Number of hierarchy levels")


class CommunityDetector(Protocol):
    """Protocol for community detection algorithms."""

    async def detect(
        self,
        entities: list[EntityNode],
        relations: list[RelatesToRelation],
    ) -> CommunityHierarchy:
        """
        Detect communities in the entity graph.

        Args:
            entities: List of entities to cluster
            relations: List of relations between entities

        Returns:
            CommunityHierarchy with topics and relations
        """
        ...

    async def assign(self, entity: EntityNode, topics: list[TopicNode]) -> str:
        """
        Assign a new entity to an existing topic.

        Args:
            entity: Entity to assign
            topics: Existing leaf-level topics

        Returns:
            Topic ID of the assigned topic
        """
        ...


class LouvainDetector:
    """Hierarchical Louvain community detection algorithm."""

    def __init__(self, driver: Neo4jDriver, resolution: float = 1.0):
        """
        Initialize Louvain detector.

        Args:
            driver: Neo4j driver for graph queries
            resolution: Resolution parameter for Louvain (higher = more communities)
        """
        self.driver: Neo4jDriver = driver
        self.resolution: float = resolution

    async def detect(
        self,
        entities: list[EntityNode],
        relations: list[RelatesToRelation],
    ) -> CommunityHierarchy:
        """Detect communities using hierarchical Louvain."""
        graph: nx.Graph = self._build_graph(entities, relations)

        if not len(graph.nodes()):
            return CommunityHierarchy(
                topics=[],
                subtopic_relations=[],
                belongs_to_relations=[],
                num_levels=0,
            )

        dendrogram: list[dict] = community_louvain.generate_dendrogram(
            graph, resolution=self.resolution
        )
        print("dendrogram:", dendrogram)

        topics: list[TopicNode] = []
        subtopic_relations: list[IsSubtopicRelation] = []
        belongs_to_relations: list[BelongsToRelation] = []

        num_dendrogram_levels: int = len(dendrogram)

        if num_dendrogram_levels <= 1:
            return CommunityHierarchy(
                topics=[],
                subtopic_relations=[],
                belongs_to_relations=[],
                num_levels=0,
            )

        level_partitions: list[dict[str, int]] = []

        for level in range(1, num_dendrogram_levels):
            partition_at_level: dict[str, int] = {}
            for node in graph.nodes():
                community: int = dendrogram[0].get(node, 0)
                for i in range(1, level + 1):
                    community = dendrogram[i].get(community, 0)
                partition_at_level[node] = community
            level_partitions.append(partition_at_level)

        num_levels: int = len(level_partitions)
        level_topic_map: dict[tuple[int, int], str] = {}

        for stored_level in range(num_levels):
            communities_at_level: set[int] = set(
                level_partitions[stored_level].values()
            )
            for community_id in communities_at_level:
                topic: TopicNode = TopicNode(
                    name=f"Topic_{stored_level}_{community_id}",
                    summary="",
                    summary_embedding=[],
                    level=stored_level,
                )
                topics.append(topic)
                level_topic_map[(stored_level, community_id)] = topic.id

        for entity_id, community_id in level_partitions[0].items():
            topic_id: str = level_topic_map[(0, community_id)]
            belongs_to_relations.append(
                BelongsToRelation(from_id=entity_id, to_id=topic_id)
            )

        for stored_level in range(num_levels - 1):
            child_to_parent: dict[int, int] = {}
            for node in graph.nodes():
                child_comm: int = level_partitions[stored_level][node]
                parent_comm: int = level_partitions[stored_level + 1][node]
                child_to_parent[child_comm] = parent_comm

            for child_comm, parent_comm in child_to_parent.items():
                child_topic_id: str = level_topic_map[(stored_level, child_comm)]
                parent_topic_id: str = level_topic_map[(stored_level + 1, parent_comm)]
                subtopic_relations.append(
                    IsSubtopicRelation(from_id=child_topic_id, to_id=parent_topic_id)
                )

        return CommunityHierarchy(
            topics=topics,
            subtopic_relations=subtopic_relations,
            belongs_to_relations=belongs_to_relations,
            num_levels=num_levels,
        )

    async def assign(
        self, entity: EntityNode, topics: list[TopicNode], alpha: float = 0.5
    ) -> str:
        """Assign entity to topic using hybrid scoring."""
        leaf_topics: list[TopicNode] = [t for t in topics if t.level == 0]

        if not leaf_topics:
            raise ValueError("No leaf-level topics available for assignment")

        edge_scores: dict[str, float] = await self._compute_edge_scores(
            entity.id, leaf_topics
        )
        embedding_scores: dict[str, float] = self._compute_embedding_scores(
            entity, leaf_topics
        )

        combined_scores: dict[str, float] = {}
        for topic in leaf_topics:
            edge_score: float = edge_scores.get(topic.id, 0.0)
            embedding_score: float = embedding_scores.get(topic.id, 0.0)
            combined_scores[topic.id] = (
                alpha * edge_score + (1 - alpha) * embedding_score
            )

        if not combined_scores:
            return leaf_topics[0].id

        best_topic_id: str = max(combined_scores, key=combined_scores.get)
        return best_topic_id

    def _build_graph(
        self, entities: list[EntityNode], relations: list[RelatesToRelation]
    ) -> nx.Graph:
        """Build NetworkX graph from entities and relations."""
        graph: nx.Graph = nx.Graph()

        for entity in entities:
            graph.add_node(entity.id)

        for relation in relations:
            graph.add_edge(relation.from_id, relation.to_id)

        return graph

    async def _compute_edge_scores(
        self, entity_id: str, topics: list[TopicNode]
    ) -> dict[str, float]:
        """Compute edge connectivity scores for entity to each topic."""
        scores: dict[str, float] = {}

        for topic in topics:
            result: list[dict] = await self.driver.query(
                """
                MATCH (e:Entity {id: $entity_id})-[:RELATES_TO]-(neighbor:Entity)-[:BELONGS_TO]->(t:Topic {id: $topic_id})
                RETURN count(DISTINCT neighbor) as neighbor_count
                """,
                {"entity_id": entity_id, "topic_id": topic.id},
            )

            neighbor_count: int = result[0]["neighbor_count"] if result else 0
            scores[topic.id] = float(neighbor_count)

        max_score: float = max(scores.values()) if scores else 1.0
        if max_score > 0:
            scores = {k: v / max_score for k, v in scores.items()}

        return scores

    def _compute_embedding_scores(
        self, entity: EntityNode, topics: list[TopicNode]
    ) -> dict[str, float]:
        """Compute embedding similarity scores for entity to each topic."""
        scores: dict[str, float] = {}

        for topic in topics:
            if not topic.summary_embedding:
                scores[topic.id] = 0.0
                continue

            similarity: float = self._cosine_similarity(
                entity.name_embedding, topic.summary_embedding
            )
            scores[topic.id] = max(0.0, similarity)

        return scores

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product: float = sum(a * b for a, b in zip(vec1, vec2))
        norm1: float = sum(a * a for a in vec1) ** 0.5
        norm2: float = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0

        return dot_product / (norm1 * norm2)
