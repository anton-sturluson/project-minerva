"""Knowledge Base module with MongoDB and Chroma integration."""

from .kb import KnowledgeBase
from .models import Section, VectorDocument, QueryResult

__all__ = ["KnowledgeBase", "Section", "VectorDocument", "QueryResult"]
