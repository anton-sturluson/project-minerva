"""Main Minerva knowledge base system."""

from typing import Any

from minerva.api.client import close_all_clients
from minerva.core.base import BaseRelation
from minerva.core.node import EntityNode, SourceNode
from minerva.core.relation import MentionsRelation, RelatesToRelation
from minerva.kb.driver import Neo4jDriver
from minerva.prompt.entity import extract_entities, resolve_entities
from minerva.prompt.model import (
    EntityExtractionResult,
    EntityResolution,
    FactExtractionResult,
)
from minerva.prompt.relation import extract_facts
from minerva.util.env import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


class Minerva:
    """Main Minerva knowledge base system for learning from text."""

    def __init__(
        self,
    ):
        """
        Initialize Minerva with Neo4j connection.

        Args:
            neo4j_uri: Neo4j connection URI (defaults to NEO4J_URI env var)
            neo4j_user: Neo4j username (defaults to NEO4J_USER env var)
            neo4j_password: Neo4j password (defaults to NEO4J_PASSWORD env var)
            neo4j_database: Neo4j database name (defaults to NEO4J_DATABASE env var)
        """
        self.driver: Neo4jDriver = Neo4jDriver(
            uri=NEO4J_URI,
            user=NEO4J_USER,
            password=NEO4J_PASSWORD,
            database=NEO4J_DATABASE,
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
        await self.driver.bulk_create_nodes([source_node])

        extraction_result: EntityExtractionResult = await extract_entities(source)
        entities: list[EntityNode] = await self._resolve_entities(
            source, extraction_result.entities
        )

        relations: list[BaseRelation] = await self._create_relations(
            source_node=source_node, entities=entities, context=source
        )

        await self._summarize_entities(entities=entities)

        return {
            "source_id": source_node.id,
            "entity_ids": [e.id for e in entities],
            "relation_ids": [rel.id for rel in relations],
        }

    async def _resolve_entities(
        self,
        context: str,
        extracted_entities: list[str],
        model: str = "gemini-2.5-flash",
    ) -> list[EntityNode]:
        """
        Resolve entities from extracted entities.

        Args:
            context: Source text for context
            extracted_entities: List of extracted entity names
            model: LLM model to use for resolution

        Returns:
            Tuple of (new_entities, all_entities)
        """
        existing_entities: list[EntityNode] = await self.driver.find_similar_entities(
            name_embedding=[1.0] * 10
        )

        resolution_results: list[EntityResolution] = await resolve_entities(
            context=context,
            new_entities=extracted_entities,
            existing_entities=existing_entities,
            model=model,
        )

        new_entity_nodes: list[EntityNode] = []
        all_entities: list[EntityNode] = []

        for resolution in resolution_results:
            if resolution.is_duplicate and resolution.existing_entity_id:
                for entity in existing_entities:
                    if entity.id == resolution.existing_entity_id:
                        all_entities.append(entity)
                        break
            else:
                new_node: EntityNode = EntityNode(
                    name=resolution.name,
                    name_embedding=[1.0] * 10,
                    summary="",
                )
                new_entity_nodes.append(new_node)
                all_entities.append(new_node)

        if new_entity_nodes:
            await self.driver.bulk_create_nodes(new_entity_nodes)

        return all_entities

    async def _create_relations(
        self,
        source_node: SourceNode,
        entities: list[EntityNode],
        context: str,
        model: str = "gemini-2.5-flash",
    ) -> list[BaseRelation]:
        """
        Create MENTIONS and RELATES_TO relations for entities.

        Args:
            source_node: Source node that mentions the entities
            entities: List of entities to create relations for
            context: Source text for extracting facts
            model: LLM model to use for fact extraction

        Returns:
            List of created relations
        """
        entity_map: dict[str, str] = {e.name: e.id for e in entities}
        relations: list[BaseRelation] = []

        for entity in entities:
            relations.append(MentionsRelation(from_id=source_node.id, to_id=entity.id))

        if len(entities) >= 2:
            fact_extraction_result: FactExtractionResult = await extract_facts(
                context=context, entities=entities, model=model
            )

            for fact in fact_extraction_result.facts:
                from_id: str | None = entity_map.get(fact.from_entity)
                to_id: str | None = entity_map.get(fact.to_entity)

                if from_id and to_id and from_id != to_id:
                    relations.append(
                        RelatesToRelation(
                            from_id=from_id,
                            to_id=to_id,
                            relation_type=fact.relation_type,
                            fact=fact.fact,
                            fact_embedding=[1.0] * 10,
                            sources=[source_node.id],
                            contradictory_relations=[],
                        )
                    )

        if relations:
            await self.driver.bulk_create_relations(relations)

        return relations

    async def _summarize_entities(
        self, entities: list[EntityNode], model: str = "gemini-2.5-flash"
    ) -> None:
        """
        Generate summaries for entities based on their relationships.

        Args:
            entities: List of entities to summarize
            model: LLM model to use for summarization
        """
        import asyncio

        tasks: list = [entity.summarize(self.driver) for entity in entities]
        summaries: list[str] = await asyncio.gather(*tasks)

        for entity, summary in zip(entities, summaries):
            await self.driver.query(
                "MATCH (e:Entity {id: $id}) SET e.summary = $summary",
                {"id": entity.id, "summary": summary},
            )

    async def close(self) -> None:
        """Close the Neo4j driver connection and all LLM client sessions."""
        await self.driver.close()
        await close_all_clients()
