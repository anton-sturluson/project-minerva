import requests
import json

import yfinance as yf


def get_company_info(ticker: str) -> dict | None:
    try:
        return yf.Ticker(ticker).info
    except yf.exceptions.YFException as e:
        print(f"Error fetching company info for {ticker}: {e}")
        return None


def parse_transcript(transcript: str) -> dict[str, int | str]:
    """
    Parse the transcript dictionary into the format of
    ```python
    [
        {
            "index": int,
            "speaker": str,
            "text": str
        }
    ]
    ```
    """
    parsed_lst: list[dict[str, str]] = []
    for i, line in enumerate(transcript.split("\n")):
        line_split: list[str] = line.split(":")
        speaker: str = line_split[0]
        text: str = ":".join(line_split[1:])
        parsed_lst.append({"index": i, "speaker": speaker, "text": text})
    return parsed_lst


def get_one_transcript(ticker: str, year: int, quarter: int) -> dict[str, int | str] | None:
    """
    Get the transcript for a given ticker, year, and quarter, in the format of
    ```python
    {
        "year": int,
        "quarter": int,
        "transcript": [
            {
                "index": int,
                "speaker": str,
                "text": str
            }
        ]
    }
    ```
    """
    api_url: str = ("https://api.api-ninjas.com/v1/earningstranscript?"
                    f"ticker={ticker}&year={year}&quarter={quarter}")
    response = requests.get(api_url, headers={'X-Api-Key': 'YOUR_API_KEY'})
    if response.status_code == requests.codes.ok:
        transcript_info: list | dict = json.loads(response.text)
        if not transcript_info or "transcript" not in transcript_info: # empty list
            return None
        return {
            "year": year,
            "quarter": quarter,
            "transcript": parse_transcript(transcript_info["transcript"])
        }
    else:
        print("Error:", response.status_code, response.text)
        return None


def get_transcripts(ticker: str, start_year: int, end_year: int) -> list[dict[str, int | str]]:
    """
    Get the transcripts for a given ticker, start year, and end year, in the format of
    ```python
    [
        {
            "year": int,
            "quarter": int,
            "transcript": [
                {
                    "index": int,
                    "speaker": str,
                    "text": str
                }
            ]
        }
    ]
    ```
    """
    transcripts: list[dict[str, int | str]] = []
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            transcript: dict[str, int | str] | None = get_one_transcript(ticker, year, quarter)
            if transcript:
                transcripts.append(transcript)
            else:
                print(f"No transcript found for {ticker} {year}-Q{quarter}")
    return transcripts


def construct_company_kb(ticker: str, start_year: int, end_year: int) -> dict[str, list | str]:
    """
    Get the transcript for a given ticker, year, and quarter, in the format of
    ```python
    {
        "ticker": str,
        "company_name": str,
        "sector": str,
        "industry": str,
        "transcripts": [
            {
                "year": int,
                "quarter": int,
                "transcript": [
                    {
                        "index": int,
                        "speaker": str,
                        "text": str
                    }
                ]
            }
        ]
    }
    ```
    """
    company_info: dict[str, str] | None = get_company_info(ticker)
    return {
        "ticker": ticker,
        "company_name": company_info["longName"] if company_info else "",
        "sector": company_info["sector"] if company_info else "",
        "industry": company_info["industry"] if company_info else "",
        "transcripts": get_transcripts(ticker, start_year, end_year)
    }