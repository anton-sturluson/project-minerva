"""Data models for LLM-based extraction operations."""

from pydantic import BaseModel, Field


class EntityExtractionResult(BaseModel):
    """Result from entity extraction."""

    entities: list[str] = Field(description="List of entity names")


class EntityResolution(BaseModel):
    """Result of resolving a single entity."""

    reasoning: str = Field(description="A brief explanation of your decision.")
    is_duplicate: bool = Field(
        description="A boolean indicating if it is a duplicate of an existing entity."
    )
    name: str = Field(description="The name of the new entity.")
    existing_entity_name: str | None = Field(
        description="If it is a duplicate, the name of the existing entity that it matches.",
        default=None,
    )
    existing_entity_id: str | None = Field(
        description="If it is a duplicate, the ID of the existing entity that it matches.",
        default=None,
    )


class Fact(BaseModel):
    """A single fact extracted from a text."""

    reasoning: str = Field(
        description="A brief explanation of why this fact is extracted."
    )
    from_entity: str = Field(description="The name of the source entity.")
    to_entity: str = Field(description="The name of the target entity.")
    relation_type: str = Field(
        description="A concise, all-caps description of the fact (e.g., CEO_OF, PARTNERS_WITH, ACQUIRED_BY)."
    )
    fact: str = Field(
        description="A more detailed fact containing all relevant information."
    )


class FactExtractionResult(BaseModel):
    """Result from fact extraction."""

    facts: list[Fact] = Field(description="List of facts extracted from the text.")


class TopicSummary(BaseModel):
    """Result of topic summarization."""

    reasoning: str = Field(description="Brief explanation of the summary.")
    name: str = Field(
        description="Short, descriptive name for the topic (2-4 words, title case)."
    )
    summary: str = Field(
        description="Concise summary of the topic capturing key themes and concepts."
    )
