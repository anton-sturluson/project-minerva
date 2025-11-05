"""Base parser classes and data models."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Line(BaseModel):
    """A single line from the original text."""

    index: int
    text: str


class ParsedOutput(BaseModel):
    """Output from parser."""

    chunks: list[dict]
    metadata: dict


class BaseParser(ABC):
    """Abstract base parser for document processing."""

    def __init__(self, text: str) -> None:
        self.text: str = text

    def _split_lines(self) -> list[Line]:
        """Split text into Line objects."""
        lines: list[str] = self.text.split("\n")
        return [Line(index=idx, text=line) for idx, line in enumerate(lines)]

    @abstractmethod
    def parse(self) -> ParsedOutput:
        """Parse the text into structured output."""
        pass
