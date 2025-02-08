"""Knowledge base for company information."""
import logging

from pymongo import MongoClient
from pymongo.collection import Collection


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

    def add_transcripts(
        self, 
        ticker: str, 
        new_transcripts: list[dict], 
        overwrite: bool = False
    ):
        """
        Add transcripts to the database.

        Args:
            ticker: The ticker of the company.
            new_transcripts: The transcripts to add.
            overwrite: Whether to overwrite existing transcripts.
        """
        transcript_map: dict | None = self.transcripts.find_one({"ticker": ticker})
        if not transcript_map:
            raise ValueError(f"Ticker {ticker} does not exist in the database.")

        saved_transcripts: dict[tuple[int, int], dict] = {
            (transcript["year"], transcript["quarter"]): transcript
            for transcript in transcript_map.get("transcripts", [])
        }

        for transcript in new_transcripts:
            key: tuple[int, int] = (transcript["year"], transcript["quarter"])
            if key in saved_transcripts and overwrite:
                saved_transcript: dict = saved_transcripts[key]
                # add new fields
                saved_transcript["speakers"] = transcript["speakers"]
                if "chunking_output" in transcript:
                    saved_transcript["chunking_output"] = transcript["chunking_output"]

                # delete old fields - probably too aggressive
                # for field in list(saved_transcript.keys()):
                #     if field not in transcript: 
                #         logging.info("`add_transcripts`: Deleting field %s from transcript: %s", 
                #                      field, key)
                #         del saved_transcript[field]
            else:
                saved_transcripts[key] = transcript

        transcripts: list[dict] = list(saved_transcripts.values())
        transcripts.sort(key=lambda x: (x["year"], x["quarter"]))
        self.transcripts.update_one(
            {"ticker": ticker},
            {"$set": {"transcripts": transcripts}},
            upsert=True
        )

    def add_ticker(self, ticker: str, ticker_info: dict):
        """Add a ticker to the database."""
        self.tickers.update_one(
            {"ticker": ticker},
            {"$set": ticker_info},
            upsert=True
        )

    def get_most_recent_year(self, ticker: str) -> int | None:
        """Get the most recent year for a ticker."""
        transcript_map: dict | None = self.transcripts.find_one({"ticker": ticker})
        if not transcript_map:
            raise ValueError(f"Ticker {ticker} does not exist in the database.")

        if not transcript_map.get("transcripts"):
            return None
        return transcript_map["transcripts"][-1]["year"]

    def get_most_recent_quarter(self, ticker: str) -> int | None:
        """Get the most recent quarter for a ticker."""
        transcript_map: dict | None = self.transcripts.find_one({"ticker": ticker})
        if not transcript_map:
            raise ValueError(f"Ticker {ticker} does not exist in the database.")

        if not transcript_map.get("transcripts"):
            return None
        return transcript_map["transcripts"][-1]["quarter"]

    # properties
    @property
    def transcripts(self) -> Collection:
        """Get transcripts collection"""
        return self.db.transcripts

    @property
    def tickers(self) -> Collection:
        """Get tickers collection"""
        return self.db.tickers

    @property
    def unique_tickers(self) -> list[str]:
        """Get unique tickers in the database."""
        return self.db.transcripts.distinct("ticker")
