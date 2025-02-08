"""Utility functions for knowledge base."""
from pymongo import MongoClient

def ticker_exists(client: MongoClient, ticker: str) -> bool:
    """Check if a ticker exists in the database."""
    return client.company_db.transcripts.find_one({"ticker": ticker}) is not None
