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
                saved_transcript: dict = saved_transcripts[key]
                # add new fields
                saved_transcript["speakers"] = transcript["speakers"]
                if "chunking_output" in transcript:
                    saved_transcript["chunking_output"] = transcript["chunking_output"]
                # delete old fields
                for field in list(saved_transcript.keys()):
                    if field not in transcript:
                        print(f"`add_transcripts`: Deleting field {field} from transcript: {key}")
                        del saved_transcript[field]
            else:
                saved_transcripts[key] = transcript

        transcripts: list[dict] = list(saved_transcripts.values())
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

    # properteis
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
