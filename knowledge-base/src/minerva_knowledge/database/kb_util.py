"""Utility functions for knowledge base."""

from pymongo import MongoClient
import tiktoken


def ticker_exists(client: MongoClient, ticker: str) -> bool:
    """Check if a ticker exists in the database."""
    return client.company_db.transcripts.find_one({"ticker": ticker}) is not None


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))
