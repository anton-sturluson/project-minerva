from tqdm import tqdm

from minerva.kb import CompanyKB
from minerva.scrape import construct_company_kb


if __name__ == "__main__":
    kb_client = CompanyKB()

    start_year: int = 2018
    end_year: int = 2025
    tickers: list[str] = ["CHGG", "MSFT", "AMZN", "NVDA", "AVGO", "GOOG",
                          "DUOL", "COUR", "UDMY"]
    for ticker in tqdm(tickers):
        kb_client.add_transcript(ticker, construct_company_kb(ticker, start_year, end_year))