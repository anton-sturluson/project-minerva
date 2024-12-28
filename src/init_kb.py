import click
from pymongo import MongoClient
from tqdm import tqdm

from minerva.data.scrape import construct_company_kb, get_transcripts
from minerva.knowledge.kb import CompanyKB
from minerva.util.env import TEST_MODE


def ticker_exists(client: MongoClient, ticker: str) -> bool:
    """Check if a ticker exists in the database."""
    return client.company_db.transcripts.find_one({"ticker": ticker}) is not None


@click.command()
@click.option(
    "--tickers", type=str, default="",
    help="Tickers to add to the database (separated by comma)")
@click.option(
    "--start-year", type=int, default=2024, show_default=True,
    help="Start year to add transcripts")
@click.option(
    "--end-year", type=int, default=2025, show_default=True,
    help="End year to add transcripts")
@click.option(
    "--chunk-transcripts", type=bool, default=False, is_flag=True,
    help="Whether to chunk transcripts")
def main(tickers: str, start_year: int, end_year: int, chunk_transcripts: bool):
    client = MongoClient()
    kb_client = CompanyKB(client)

    for ticker in tqdm(tickers.split(","), desc="Tickers"):
        ticker = ticker.strip()
        if not ticker_exists(client, ticker):
            company_info: dict = construct_company_kb(
                ticker, start_year, end_year, chunk_transcripts=chunk_transcripts)
            if not TEST_MODE:
                kb_client.add_company_info(ticker, company_info)

        else:
            transcripts: list[dict] = get_transcripts(
                ticker, start_year, end_year, chunk_transcripts=chunk_transcripts)
            if not TEST_MODE:
                kb_client.add_transcripts(ticker, transcripts)


if __name__ == "__main__":
    main() # pylint: disable=no-value-for-parameter
