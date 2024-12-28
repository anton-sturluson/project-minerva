from pymongo import MongoClient
from tqdm import tqdm

from minerva.kb import CompanyKB
from minerva.scrape import construct_company_kb, get_transcripts


def ticker_exists(client: MongoClient, ticker: str) -> bool:
    """Check if a ticker exists in the database."""
    return client.company_db.transcripts.find_one({"ticker": ticker}) is not None


if __name__ == "__main__":
    client = MongoClient()
    kb_client = CompanyKB(client)

    start_year: int = 2024
    end_year: int = 2025
    tickers: list[str] = ["COUR"]
    for ticker in tqdm(tickers):
        if not ticker_exists(client, ticker):
            kb_client.add_company_info(
                ticker, construct_company_kb(ticker, start_year, end_year))

        else:
            transcripts: list[dict] = get_transcripts(ticker, start_year, end_year)
            kb_client.add_transcripts(ticker, transcripts)
