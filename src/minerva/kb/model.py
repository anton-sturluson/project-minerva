"""Data models for the Knowledge Base."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class Section(BaseModel):
    """Represents a section or subsection in the knowledge base."""

    section_id: str
    parent_id: str | None = None
    slug: str | None = None
    header: str
    content: str
    level: int = 0
    order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class VectorDocument(BaseModel):
    """Represents a document in the vector database."""

    document_id: str
    section_id: str
    chunk_index: int = 0
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResult(BaseModel):
    """Unified result from knowledge base queries."""

    section_id: str
    header: str
    content: str
    similarity: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    path: str | None = None  # e.g., "1.2.3" or "section/subsection"
