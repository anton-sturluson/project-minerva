#!/usr/bin/env python
from urllib.request import urlopen
import certifi
import json

from knowledge.util.env import FMP_API_KEY
from knowledge.database.kb import CompanyKB


def get_jsonparsed_data(url):
    response = urlopen(url, cafile=certifi.where())
    data = response.read().decode("utf-8")
    return json.loads(data)


def main():
    url = f"https://financialmodelingprep.com/api/v3/stock/list?apikey={FMP_API_KEY}"
    tickers = get_jsonparsed_data(url)
    print(len(tickers))
    with open("../data/tickers.json", "w") as f:
        json.dump(tickers, f)

    with open("tickers.json", "r") as f:
        tickers = json.load(f)

    kb = CompanyKB()
    for ticker_map in tickers:
        del ticker_map["price"]
        ticker: str = ticker_map["symbol"]
        kb.add_ticker(ticker, ticker_map)


if __name__ == "__main__":
    main()
