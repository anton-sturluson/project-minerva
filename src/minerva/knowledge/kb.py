from copy import deepcopy

from pymongo import MongoClient, UpdateOne


class CompanyKB:
    def __init__(self, mongo_client: MongoClient | None = None):
        if not mongo_client:
            mongo_client = MongoClient()
        self.client = mongo_client
        self.db = self.client["company_db"]

    def add_company_info(self, ticker: str, transcript_info: dict):
        """
        Add transcripts to the database.

        *NOTE*: This code is buggy and will overwrite existing transcripts.
        """
        self.transcripts.update_one(
            {"ticker": ticker},
            {"$set": transcript_info},
            upsert=True
        )

    def add_transcripts(self, ticker: str, new_transcripts: list[dict]):
        """Add transcripts to the database."""
        transcript_map: dict | None = self.transcripts.find_one({"ticker": ticker})
        if not transcript_map:
            raise ValueError(f"Ticker {ticker} does not exist in the database.")

        saved_transcripts: dict[tuple[int, int], dict] = {
            (transcript["year"], transcript["quarter"]): transcript
            for transcript in transcript_map["transcripts"]
        }

        for transcript in new_transcripts:
            key: tuple[int, int] = (transcript["year"], transcript["quarter"])
            if key in saved_transcripts:
                saved_transcripts[key]["transcript"] = transcript["transcript"]
            else:
                saved_transcripts[key] = transcript

        transcripts: list[dict] = list(saved_transcripts.values())
        self.transcripts.update_one(
            {"ticker": ticker},
            {"$set": {"transcripts": transcripts}},
            upsert=True
        )
      
    @property
    def transcripts(self):
        """Get transcripts collection"""
        return self.db.transcripts

    @property
    def tickers(self) -> list[str]:
        """Get unique tickers in the database."""
        return self.db.transcripts.distinct("ticker")
