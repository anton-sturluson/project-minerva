"""Relation models for the knowledge graph."""

from __future__ import annotations

from typing import Any

from minerva.core.base import BaseRelation


class MentionsRelation(BaseRelation):
    """Relation from Source to Entity indicating the source mentions the entity."""

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Source",
            "to_label": "Entity",
            "properties": ["id", "created_at"],
        }


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


class IsSubtopicRelation(BaseRelation):
    """Relation from parent Topic to child Topic."""

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Topic",
            "to_label": "Topic",
            "properties": ["id", "created_at"],
        }


class BelongsToRelation(BaseRelation):
    """Relation from Entity to Topic indicating the entity belongs to the topic."""

    @classmethod
    def get_neo4j_metadata(cls) -> dict[str, Any]:
        return {
            "from_label": "Entity",
            "to_label": "Topic",
            "properties": ["id", "created_at"],
        }
