"""Data models for Minerva learning platform."""

from enum import Enum

from pydantic import BaseModel, Field


class KnowledgeItem(BaseModel):
    """Represents a single extracted knowledge item."""

    header: str = Field(description="Clear, descriptive title for the knowledge item")
    content: str = Field(description="Compressed knowledge with essential information")


class KnowledgeExtraction(BaseModel):
    """Response model for knowledge extracton from text."""

    items: list[KnowledgeItem] = Field(
        description="List of extracted knowledge items with headers and content"
    )


class MetricTiming(str, Enum):
    """When to run a metric."""

    BEFORE = "before"
    AFTER = "after"


class MetricBehavior(str, Enum):
    """What to do when metric returns True."""

    HALT = "halt"
    CONTINUE = "continue"


class MetricConfig(BaseModel):
    """Configuration for a metric."""

    metric_name: str = Field(description="Name of the metric class")
    timing: MetricTiming = Field(description="When to run the metric")
    on_true: MetricBehavior = Field(description="Behavior when metric returns True")
    on_false: MetricBehavior = Field(description="Behavior when metric returns False")
