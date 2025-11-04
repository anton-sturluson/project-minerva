"""API Ninjas client for fetching earnings call transcripts and other data."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from minerva.util.env import APININJAS_API_KEY


@dataclass
class EarningsTranscript:
    """Earnings call transcript data."""

    ticker: str
    cik: str
    year: int
    quarter: int
    date: str
    transcript: str


class ApiNinjasClient:
    """Client for API Ninjas services."""

    def __init__(self, api_key: str | None = None, data_dir: str = "data") -> None:
        self.api_key: str | None = api_key or APININJAS_API_KEY
        self.data_dir: Path = Path(data_dir)
        self.base_url: str = "https://api.api-ninjas.com/v1"
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "ApiNinjasClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            await self._session.close()

    async def fetch_transcript(
        self,
        ticker: str | None = None,
        cik: str | None = None,
        year: int | None = None,
        quarter: int | None = None,
    ) -> EarningsTranscript:
        """Fetch earnings call transcript."""
        if not self.api_key:
            raise ValueError("API key is required")

        if not ticker and not cik:
            raise ValueError("Either ticker or cik must be provided")

        if self._session is None:
            raise RuntimeError("Client must be used as async context manager")

        params: dict[str, str | int] = {}
        if ticker:
            params["ticker"] = ticker
        if cik:
            params["cik"] = cik
        if year:
            params["year"] = year
        if quarter:
            params["quarter"] = quarter

        headers: dict[str, str] = {"X-Api-Key": self.api_key}

        async with self._session.get(
            f"{self.base_url}/earningstranscript", params=params, headers=headers
        ) as response:
            response.raise_for_status()
            data: dict = await response.json()

        return EarningsTranscript(
            ticker=data["ticker"],
            cik=data["cik"],
            year=data["year"],
            quarter=data["quarter"],
            date=data["date"],
            transcript=data["transcript"],
        )

    async def save_transcript(self, transcript: EarningsTranscript) -> None:
        """Save transcript to data directory following project conventions."""
        ticker_dir: Path = self.data_dir / transcript.ticker
        transcripts_dir: Path = ticker_dir / "earnings-calls"
        transcripts_dir.mkdir(parents=True, exist_ok=True)

        filename: str = f"{transcript.year}Q{transcript.quarter}.txt"
        file_path: Path = transcripts_dir / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(transcript.transcript)

        metadata_path: Path = transcripts_dir / "metadata.json"

        metadata_entry: dict[str, str | int] = {
            "filename": filename,
            "ticker": transcript.ticker,
            "cik": transcript.cik,
            "year": transcript.year,
            "quarter": transcript.quarter,
            "date": transcript.date,
        }

        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata: list[dict] = json.load(f)
        else:
            metadata = []

        existing_idx: int | None = None
        for idx, entry in enumerate(metadata):
            if (
                entry["ticker"] == transcript.ticker
                and entry["year"] == transcript.year
                and entry["quarter"] == transcript.quarter
            ):
                existing_idx = idx
                break

        if existing_idx is not None:
            metadata[existing_idx] = metadata_entry
        else:
            metadata.append(metadata_entry)

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
