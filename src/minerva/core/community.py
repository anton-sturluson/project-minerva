"""Community detection algorithms for entity clustering."""

from collections import defaultdict
from typing import Protocol

import community as community_louvain
import networkx as nx
from pydantic import BaseModel, Field

from minerva.clustering.link_clustering import HLC
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
    updated_relations: list[RelatesToRelation] = Field(
        description="Relations with updated topic_id assignments"
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


class HLCDetector:
    """Hierarchical Link Community detection algorithm."""

    def __init__(self, driver: Neo4jDriver, threshold: float | None = None):
        """
        Initialize HLC detector.

        Args:
            driver: Neo4j driver for graph queries
            threshold: Similarity threshold to cut dendrogram (None = use optimal partition density)
        """
        self.driver: Neo4jDriver = driver
        self.threshold: float | None = threshold

    async def detect(
        self,
        entities: list[EntityNode],
        relations: list[RelatesToRelation],
    ) -> CommunityHierarchy:
        """Detect edge-centric communities using HLC with overlapping node membership."""
        graph: nx.Graph = self._build_graph(entities, relations)

        if not len(graph.nodes()) or not len(graph.edges()):
            return CommunityHierarchy(
                topics=[],
                subtopic_relations=[],
                belongs_to_relations=[],
                updated_relations=[],
                num_levels=0,
            )

        adj, edges, node_to_id, edge_to_relation = self._convert_to_hlc_format(
            graph, relations
        )

        hlc: HLC = HLC(adj, edges)
        edge2cid, S_max, D_max, list_D, orig_cid2edge, linkage = hlc.single_linkage(
            threshold=self.threshold, dendro_flag=True
        )

        hierarchy: CommunityHierarchy = self._build_hierarchy_from_linkage(
            edge2cid, linkage, edge_to_relation
        )

        return hierarchy

    async def assign(
        self, entity: EntityNode, topics: list[TopicNode], alpha: float = 0.5
    ) -> str:
        """Assign entity to all topics that its connected edges belong to."""
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

    def _convert_to_hlc_format(
        self, graph: nx.Graph, relations: list[RelatesToRelation]
    ) -> tuple[dict[str, set[str]], set[tuple[str, str]], dict[str, str], dict[tuple[str, str], RelatesToRelation]]:
        """Convert NetworkX graph to HLC format with ID mappings."""
        adj: dict[str, set[str]] = {}
        for node in graph.nodes():
            adj[node] = set(graph.neighbors(node))

        edges: set[tuple[str, str]] = set()
        edge_to_relation: dict[tuple[str, str], RelatesToRelation] = {}

        for relation in relations:
            edge: tuple[str, str] = tuple(sorted([relation.from_id, relation.to_id]))
            edges.add(edge)
            edge_to_relation[edge] = relation

        node_to_id: dict[str, str] = {node: node for node in graph.nodes()}

        return adj, edges, node_to_id, edge_to_relation

    def _build_hierarchy_from_linkage(
        self,
        edge2cid: dict[tuple[str, str], int],
        linkage: list[tuple[int, int, float]],
        edge_to_relation: dict[tuple[str, str], RelatesToRelation],
    ) -> CommunityHierarchy:
        """Build multi-level topic hierarchy from HLC linkage dendrogram."""
        topics: list[TopicNode] = []
        subtopic_relations: list[IsSubtopicRelation] = []
        belongs_to_relations: list[BelongsToRelation] = []

        cid_to_edges: dict[int, set[tuple[str, str]]] = defaultdict(set)
        for edge, cid in edge2cid.items():
            cid_to_edges[cid].add(edge)

        cid_to_topic_id: dict[int, str] = {}
        cid_to_level: dict[int, int] = {}

        for cid in set(edge2cid.values()):
            topic: TopicNode = TopicNode(
                name=f"EdgeCommunity_0_{cid}",
                summary="",
                summary_embedding=[],
                level=0,
            )
            topics.append(topic)
            cid_to_topic_id[cid] = topic.id
            cid_to_level[cid] = 0

        node_to_topics: dict[str, set[str]] = defaultdict(set)
        for edge, cid in edge2cid.items():
            n1, n2 = edge
            topic_id: str = cid_to_topic_id[cid]
            node_to_topics[n1].add(topic_id)
            node_to_topics[n2].add(topic_id)

            if edge in edge_to_relation:
                edge_to_relation[edge].topic_id = topic_id

        for node_id, topic_ids in node_to_topics.items():
            for topic_id in topic_ids:
                belongs_to_relations.append(
                    BelongsToRelation(from_id=node_id, to_id=topic_id)
                )

        if not linkage:
            return CommunityHierarchy(
                topics=topics,
                subtopic_relations=subtopic_relations,
                belongs_to_relations=belongs_to_relations,
                updated_relations=list(edge_to_relation.values()),
                num_levels=1,
            )

        next_cid: int = max(edge2cid.values()) + 1

        for child1_cid, child2_cid, similarity in linkage:
            child1_exists: bool = child1_cid in cid_to_topic_id
            child2_exists: bool = child2_cid in cid_to_topic_id

            if not child1_exists and not child2_exists:
                continue

            parent_cid: int = next_cid
            next_cid += 1

            child1_level: int = cid_to_level.get(child1_cid, -1) if child1_exists else -1
            child2_level: int = cid_to_level.get(child2_cid, -1) if child2_exists else -1
            parent_level: int = max(child1_level, child2_level) + 1

            parent_topic: TopicNode = TopicNode(
                name=f"EdgeCommunity_{parent_level}_{parent_cid}",
                summary="",
                summary_embedding=[],
                level=parent_level,
            )
            topics.append(parent_topic)
            cid_to_topic_id[parent_cid] = parent_topic.id
            cid_to_level[parent_cid] = parent_level

            if child1_exists:
                subtopic_relations.append(
                    IsSubtopicRelation(
                        from_id=cid_to_topic_id[child1_cid], to_id=parent_topic.id
                    )
                )

            if child2_exists:
                subtopic_relations.append(
                    IsSubtopicRelation(
                        from_id=cid_to_topic_id[child2_cid], to_id=parent_topic.id
                    )
                )

            child1_edges: set[tuple[str, str]] = cid_to_edges.get(child1_cid, set()) if child1_exists else set()
            child2_edges: set[tuple[str, str]] = cid_to_edges.get(child2_cid, set()) if child2_exists else set()
            cid_to_edges[parent_cid] = child1_edges | child2_edges

        num_levels: int = max(t.level for t in topics) + 1 if topics else 0

        return CommunityHierarchy(
            topics=topics,
            subtopic_relations=subtopic_relations,
            belongs_to_relations=belongs_to_relations,
            updated_relations=list(edge_to_relation.values()),
            num_levels=num_levels,
        )

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
