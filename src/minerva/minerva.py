"""Main Minerva knowledge base system."""

import asyncio
from typing import Any

from minerva.api.client import close_all_clients
from minerva.core.base import BaseRelation, BaseNode
from minerva.core.extractor import EmbeddingExtractor
from minerva.core.node import EntityNode, SourceNode
from minerva.core.relation import MentionsRelation, RelatesToRelation
from minerva.kb.driver import Neo4jDriver
from minerva.prompt.entity import extract_entities, resolve_entity
from minerva.prompt.model import (
    EntityExtractionResult,
    EntityResolution,
    FactExtractionResult,
    FactResolution,
)
from minerva.prompt.relation import extract_facts, resolve_fact


class Minerva:
    """Main Minerva knowledge base system for learning from text."""

    def __init__(
        self,
        embedding_model: str = "google/embeddinggemma-300m",
        embedding_batch_size: int = 32,
    ):
        """
        Initialize Minerva with Neo4j connection and embedding extractor.

        Args:
            embedding_model: HuggingFace model for embeddings
            embedding_batch_size: Batch size for embedding extraction
        """
        self.driver: Neo4jDriver = Neo4jDriver()
        self.embedding_extractor: EmbeddingExtractor = EmbeddingExtractor(
            model_name=embedding_model,
            batch_size=embedding_batch_size,
        )

    async def learn(self, source: str) -> dict[str, Any]:
        """
        Learn from a source text by extracting and storing entities and their relations.

        Args:
            source: Source text to learn from

        Returns:
            Dictionary with created source_id, entity_ids, and relation_ids
        """
        source_node: SourceNode = SourceNode(content=source)

        extraction_result: EntityExtractionResult = await extract_entities(source)
        new_entities, entities = await self._resolve_entities(
            source, extraction_result.entities
        )

        mentions_relations: list[
            MentionsRelation
        ] = await self._create_mention_relations(
            source_node=source_node, entities=entities
        )

        extracted_relations: list[RelatesToRelation] = []
        if len(entities) >= 2:
            extracted_relations = await self._extract_facts(
                source_node=source_node, entities=entities, context=source
            )

        new_relations: list[RelatesToRelation] = []
        relations_to_update: list[RelatesToRelation] = []
        if extracted_relations:
            new_relations, relations_to_update = await self._resolve_relations(
                context=source,
                relations=extracted_relations,
                entities=entities,
            )

        nodes_to_create: list[BaseNode] = [source_node] + new_entities
        edges_to_create: list[BaseRelation] = mentions_relations + new_relations
        await self.driver.bulk_create_nodes(nodes_to_create)
        await self.driver.bulk_create_relations(edges_to_create)
        await self.driver.bulk_update_relations(relations_to_update)

        return {
            "source_id": source_node.id,
            "entity_ids": [e.id for e in entities],
            "relation_ids": [rel.id for rel in edges_to_create + relations_to_update],
        }

    async def _resolve_entities(
        self,
        context: str,
        extracted_entities: list[str],
    ) -> tuple[list[EntityNode], list[EntityNode]]:
        """
        Resolve entities from extracted entities.

        Args:
            context: Source text for context
            extracted_entities: List of extracted entity names

        Returns:
            Tuple of (new_entities, all_entities)
        """
        if not extracted_entities:
            return [], []

        entity_embeddings: list[list[float]] = self.embedding_extractor.extract_batch(
            extracted_entities
        )

        async def process_entity(i: int, entity_name: str) -> tuple[int, EntityNode]:
            name_embedding: list[float] = entity_embeddings[i]
            similar_entities: list[
                EntityNode
            ] = await self.driver.find_similar_entities(name_embedding=name_embedding)

            print()

            if similar_entities:
                resolution: EntityResolution = await resolve_entity(
                    context=context,
                    new_entity=entity_name,
                    existing_entities=similar_entities,
                )

                if resolution.is_duplicate and resolution.existing_entity_id:
                    for existing in similar_entities:
                        if existing.id == resolution.existing_entity_id:
                            return (1, existing)

            new_node: EntityNode = EntityNode(
                name=entity_name,
                name_embedding=name_embedding,
            )
            return (0, new_node)

        results: list[tuple[int, EntityNode]] = await asyncio.gather(
            *[process_entity(i, e) for i, e in enumerate(extracted_entities)]
        )

        new_entities: list[EntityNode] = [
            entity for action, entity in results if action == 0
        ]
        all_entities: list[EntityNode] = [entity for _, entity in results]

        return new_entities, all_entities

    async def _create_mention_relations(
        self,
        source_node: SourceNode,
        entities: list[EntityNode],
    ) -> list[MentionsRelation]:
        """
        Create MENTIONS relations from source to entities.

        Args:
            source_node: Source node that mentions the entities
            entities: List of entities to create relations for

        Returns:
            List of MENTIONS relations
        """
        return [
            MentionsRelation(from_id=source_node.id, to_id=entity.id)
            for entity in entities
        ]

    async def _extract_facts(
        self,
        source_node: SourceNode,
        entities: list[EntityNode],
        context: str,
    ) -> list[RelatesToRelation]:
        """
        Extract facts and create RELATES_TO relations.

        Args:
            source_node: Source node that mentions the entities
            entities: List of entities to extract facts between
            context: Source text for extracting facts

        Returns:
            List of RELATES_TO relations extracted from facts
        """
        entity_map: dict[str, str] = {e.name: e.id for e in entities}

        fact_extraction_result: FactExtractionResult = await extract_facts(
            context=context, entities=entities
        )

        valid_facts: list = []
        for fact in fact_extraction_result.facts:
            from_id: str | None = entity_map.get(fact.from_entity)
            to_id: str | None = entity_map.get(fact.to_entity)
            if from_id and to_id and from_id != to_id:
                valid_facts.append((fact, from_id, to_id))

        if not valid_facts:
            return []

        fact_texts: list[str] = [fact.fact for fact, _, _ in valid_facts]
        fact_embeddings: list[list[float]] = self.embedding_extractor.extract_batch(
            fact_texts
        )

        relations: list[RelatesToRelation] = []
        for (fact, from_id, to_id), fact_embedding in zip(valid_facts, fact_embeddings):
            relations.append(
                RelatesToRelation(
                    from_id=from_id,
                    to_id=to_id,
                    relation_type=fact.relation_type,
                    fact=fact.fact,
                    fact_embedding=fact_embedding,
                    sources=[source_node.id],
                    contradictory_relations=[],
                )
            )

        return relations

    async def _resolve_relations(
        self,
        context: str,
        relations: list[RelatesToRelation],
        entities: list[EntityNode],
    ) -> tuple[list[RelatesToRelation], list[RelatesToRelation]]:
        """
        Resolve relations against existing relations in the graph.

        Args:
            context: Source text for context
            relations: List of newly extracted relations to resolve
            entities: List of entities (for entity name to ID mapping)

        Returns:
            Tuple of (new_relations, relations_to_update)
        """
        if not relations:
            return [], []

        entity_map: dict[str, str] = {e.id: e.name for e in entities}

        async def process_relation(
            relation: RelatesToRelation,
        ) -> tuple[int, RelatesToRelation]:
            similar_relations: list[
                RelatesToRelation
            ] = await self.driver.find_similar_relations(
                fact_embedding=relation.fact_embedding
            )

            print()

            if similar_relations:
                resolution: FactResolution = await resolve_fact(
                    context=context,
                    new_relation=relation,
                    existing_relations=similar_relations,
                    entity_map=entity_map,
                )

                if resolution.is_duplicate and resolution.existing_relation_id:
                    for candidate in similar_relations:
                        if candidate.id == resolution.existing_relation_id:
                            updated_sources: list[str] = sorted(
                                set(candidate.sources + relation.sources)
                            )
                            return (
                                1,
                                candidate.model_copy(
                                    update={"sources": updated_sources}
                                ),
                            )

            return (0, relation)

        results: list[tuple[int, RelatesToRelation]] = await asyncio.gather(
            *[process_relation(r) for r in relations]
        )

        new_relations: list[RelatesToRelation] = [
            rel for action, rel in results if action == 0
        ]
        relations_to_update: list[RelatesToRelation] = [
            rel for action, rel in results if action == 1
        ]

        return new_relations, relations_to_update

    async def close(self) -> None:
        """Close the Neo4j driver connection and all LLM client sessions."""
        await self.driver.close()
        await close_all_clients()
