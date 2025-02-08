"""Script to manage the company knowledge base."""
import logging

import click
from pymongo import MongoClient

from minerva.knowledge import kb_util
from minerva.knowledge.kb import CompanyKB
from minerva.knowledge.scrape import init_company_kb, get_transcripts
from minerva.util.env import TEST_MODE

logging.basicConfig(level=logging.INFO)

@click.command()
@click.option(
    "--tickers", type=str, default="all",
    help="Tickers to add to the database (separated by comma)")
@click.option(
    "--years", type=str, default="2024-2025", show_default=True,
    help="Years to add transcripts (separated by '-')")
@click.option(
    "--quarters", type=str, default="1-4", show_default=True,
    help="Quarters to add transcripts (separated by '-')")
@click.option(
    "--add-recent-transcripts", is_flag=True,
    help="Find and add recent transcripts to the database")
def main(tickers: str, years: str, quarters: str, add_recent_transcripts: bool):
    client = MongoClient()
    kb_client = CompanyKB(client)

    default_start_year, default_end_year = map(int, years.split("-"))
    default_start_quarter, default_end_quarter = map(int, quarters.split("-"))

    if tickers == "all":
        tickers = kb_client.unique_tickers
    else:
        tickers = [t.strip() for t in tickers.split(",")]

    for ticker in tickers:
        ticker_exists: bool = kb_util.ticker_exists(client, ticker)

        if not ticker_exists:
            logging.info("Ticker %s doesn't exist in the database. Initializing...", ticker)
            company_info: dict = init_company_kb(ticker)
            kb_client.add_company_info(ticker, company_info)

        if add_recent_transcripts:
            recent_year: int | None = kb_client.get_most_recent_year(ticker)
            recent_quarter: int | None = kb_client.get_most_recent_quarter(ticker)
            if recent_year is None or recent_quarter is None:
                start_year, end_year = default_start_year, default_end_year
                start_quarter, end_quarter = default_start_quarter, default_end_quarter
                logging.info("Ticker %s doesn't have any transcripts in the database. "
                             "Using default years and quarters...", ticker)

            else:
                # search for one more year if the most recent quarter is 4
                if recent_quarter == 4:
                    start_quarter, end_quarter = 1, 4
                    start_year, end_year = recent_year + 1, recent_year + 1
                # search for the rest of the year if not
                else:
                    start_year, end_year = recent_year, recent_year
                    start_quarter, end_quarter = recent_quarter + 1, 4

            logging.info(
                "[%s] Searching for transcripts from Y%s-%s, Q%s-%s",
                ticker, start_year, end_year, start_quarter, end_quarter)
            transcripts: list[dict] = get_transcripts(
                ticker, start_year, end_year, start_quarter, end_quarter)
            kb_client.add_transcripts(ticker, transcripts)

if __name__ == "__main__":
    main() # pylint: disable=no-value-for-parameter
