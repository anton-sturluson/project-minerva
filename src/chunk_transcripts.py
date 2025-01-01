"""A script to chunk transcripts."""
from tqdm import tqdm

from minerva.knowledge.kb import CompanyKB
from minerva.data.scrape import _chunk


if __name__ == "__main__":
    kb = CompanyKB()
    tickers: list[str] = kb.transcripts.distinct("ticker")
    for ticker in tqdm(tickers, desc="Tickers"):
        print("Ticker:", ticker)
        company_map = kb.transcripts.find_one({"ticker": ticker})
        transcripts: list[dict] = company_map["transcripts"]
        for transcript_map in tqdm(transcripts, desc="Transcripts"):
            transcript_map["chunks"] = _chunk(transcript_map["speakers"])

        kb.add_transcripts(ticker, transcripts)
