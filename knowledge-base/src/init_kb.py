import click
from pymongo import MongoClient
from tqdm import tqdm

from minerva.knowledge import kb_util
from minerva.knowledge.kb import CompanyKB
from minerva.knowledge.scrape import construct_company_kb, get_transcripts
from minerva.util.env import TEST_MODE


@click.command()
@click.option(
    "--tickers", type=str, default="",
    help="Tickers to add to the database (separated by comma)")
@click.option(
    "--years", type=str, default="2024-2025", show_default=True,
    help="Years to add transcripts (separated by '-')")
@click.option(
    "--quarters", type=str, default="1-4", show_default=True,
    help="Quarters to add transcripts (separated by '-')")
def main(tickers: str, years: str, quarters: str):
    client = MongoClient()
    kb_client = CompanyKB(client)

    start_year, end_year = map(int, years.split("-"))
    start_quarter, end_quarter = map(int, quarters.split("-"))

    for ticker in tqdm(tickers.split(","), desc="Tickers"):
        ticker = ticker.strip()
        if not kb_util.ticker_exists(client, ticker):
            company_info: dict = construct_company_kb(
                ticker, start_year, end_year, start_quarter, end_quarter)
            if not TEST_MODE:
                kb_client.add_company_info(ticker, company_info)

        else:
            transcripts: list[dict] = get_transcripts(
                ticker, start_year, end_year, start_quarter, end_quarter)
            if not TEST_MODE:
                kb_client.add_transcripts(ticker, transcripts)


if __name__ == "__main__":
    main() # pylint: disable=no-value-for-parameter
