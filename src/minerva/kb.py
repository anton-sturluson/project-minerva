from pymongo import MongoClient


class CompanyKB:
    def __init__(self):
        self.client = MongoClient()
        self.db = self.client["company_db"]

    def add_transcript(self, ticker: str, transcript_info: dict):
        """
        Add transcripts to the database.

        *NOTE*: This code is buggy and will overwrite existing transcripts.
        """
        self.transcripts.update_one(
            {"ticker": ticker},
            {"$set": transcript_info},
            upsert=True
        )

    @property
    def transcripts(self):
        return self.db.transcripts