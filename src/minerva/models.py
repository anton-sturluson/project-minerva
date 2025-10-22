"""Data models for Minerva learning platform."""

from typing import List, Optional
from pydantic import BaseModel, Field


class KnowledgeItem(BaseModel):
    """Represents a single extracted knowledge item."""

    header: str = Field(description="Clear, descriptive title for the knowledge item")
    content: str = Field(description="Compressed knowledge with essential information")


class KnowledgeExtraction(BaseModel):
    """Response model for knowledge extraction from text."""

    items: List[KnowledgeItem] = Field(
        description="List of extracted knowledge items with headers and content"
    )
