"""Utilities for scraping transcripts from the web."""
import json
import logging
import re
import requests

import yfinance as yf

logging.basicConfig(level=logging.INFO)

def get_company_info(ticker: str) -> dict | None:
    try:
        return yf.Ticker(ticker).info
    except yf.exceptions.YFException as e:
        logging.error(f"`get_company_info`: Error fetching company info for {ticker}: {e}")
        return None


def parse_transcript(transcript: str) -> list[dict[str, int | str]]:
    """
    Parse the transcript dictionary into the format of
    ```python
    [
        {
            "speaker_index": int,
            "speaker": str,
            "text": str
        }
    ]
    ```
    """
    # Regular expression to capture the speaker and their text
    speaker_regex = re.compile(
        r"([A-Za-z\s]+):\s*(.*?)(?=(?:\n[A-Za-z\s]+:|$))", re.DOTALL)

    # Find all matches
    matches = speaker_regex.findall(transcript)
    
    # Add them to the parsed list in the desired format
    parsed: list[dict[str, str| int]] = []
    for i, match in enumerate(matches):
        speaker: str = match[0].strip()
        text: str = match[1].strip()
        parsed.append({"speaker_index": i, "speaker": speaker, "text": text})

    return parsed


def get_one_transcript(ticker: str, year: int, quarter: int) -> dict[str, int | str] | None:
    """
    Get the transcript for a given ticker, year, and quarter, in the format of
    ```python
    {
        "year": int,
        "quarter": int,
        "speakers": [
            {
                "speaker_index": int,
                "speaker": str,
                "text": str
            }
        ],
        "full_transcript": str
    }
    ```
    """
    api_url: str = ("https://api.api-ninjas.com/v1/earningstranscript?"
                    f"ticker={ticker}&year={year}&quarter={quarter}")
    response = requests.get(api_url, headers={'X-Api-Key': 'YOUR_API_KEY'})
    if response.status_code == requests.codes.ok:
        # it returns an empty list when there is no data
        # or a dictionary when there is data
        transcript_info: list | dict = json.loads(response.text)
        if not transcript_info or "transcript" not in transcript_info:
            logging.info("`get_one_transcript`: No transcript found for %s, Y%s Q%s",
                         ticker, year, quarter)
            return None
        
        speakers: list[dict] = parse_transcript(transcript_info["transcript"])
        full_transcript: str = "\n\n".join(
            f"[{speaker['speaker']}] {speaker['text']}" for speaker in speakers)

        return {
            "year": year,
            "quarter": quarter,
            "speakers": speakers,
            "full_transcript": full_transcript
        }
    else:
        logging.error("Error: %s, %s", response.status_code, response.text)
        return None


def get_transcripts(
    ticker: str, 
    start_year: int, 
    end_year: int,
    start_quarter: int,
    end_quarter: int
) -> list[dict[str, int | str]]:
    """
    Get the transcripts for a given ticker, start year, and end year, in the format of
    ```python
    [
        {
            "year": int,
            "quarter": int,
            "speakers": [
                {
                    "speaker_index": int,
                    "speaker": str,
                    "text": str
                }
            ],
            "full_transcript": str
        }
    ]
    ```

    Args:
        ticker: The ticker of the company.
        start_year: The start year to get transcripts.
        end_year: The end year to get transcripts.
        start_quarter: The start quarter to get transcripts.
        end_quarter: The end quarter to get transcripts.
    """
    logging.info("`get_transcripts`: Ticker: %s", ticker)
    transcripts: list[dict[str, int | str]] = []
    for year in range(start_year, end_year + 1):
        for quarter in range(start_quarter, end_quarter + 1):
            try:
                transcript_map: dict[str, int | str] | None = get_one_transcript(ticker, year, quarter)
                if not transcript_map:
                    continue
                transcripts.append(transcript_map)

            except Exception as e:
                logging.error("get_transcripts: Error fetching transcript for %s "
                              "Y%s-Q%s: %s", ticker, year, quarter, e)
                raise

    return transcripts


def init_company_kb(ticker: str) -> dict[str, list | str]:
    """
    Get the transcript for a given ticker, year, and quarter, in the format of
    ```python
    {
        "ticker": str,
        "company_name": str,
        "sector": str,
        "industry": str
    }
    ```

    Args:
        ticker: The ticker of the company.
    """
    company_info: dict[str, str] | None = get_company_info(ticker)
    out = {"ticker": ticker}
    if company_info:
        out["company_name"] = company_info.get("longName", "")
        out["sector"] = company_info.get("sector", "")
        out["industry"] = company_info.get("industry", "")
    out["transcripts"] = []
    return out
