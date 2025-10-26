"""Data models for metric evaluation."""

from pydantic import BaseModel, Field


class MetricResult(BaseModel):
    """Result from metric evaluation."""

    gradient: str = Field(description="Feedback or explanation for the decision")
    decision: bool = Field(description="Binary decision: True for Yes, False for No")
