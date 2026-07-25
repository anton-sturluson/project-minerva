"""Small Finnhub provider boundary shared by news consumers."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import requests

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_CALL_DELAY_SECONDS = 0.1


@dataclass(slots=True)
class FinnhubNewsPayload:
    """Raw Finnhub news grouped by endpoint, plus request failures."""

    general: list[dict[str, object]]
    company: list[dict[str, object]]
    errors: int = 0


def fetch_finnhub_news(
    *,
    api_key: str,
    publication_date: date,
    symbols: Mapping[str, str],
    delay: float = FINNHUB_CALL_DELAY_SECONDS,
) -> FinnhubNewsPayload:
    """Fetch general news and one publication day of company news.

    ``symbols`` maps Finnhub symbols to canonical security IDs. Endpoint
    failures are isolated so one unsupported company does not abort the batch.
    """
    session = requests.Session()
    general: list[dict[str, object]] = []
    company: list[dict[str, object]] = []
    errors = 0

    try:
        time.sleep(delay)
        response = session.get(
            f"{FINNHUB_BASE_URL}/news",
            params={"category": "general", "token": api_key},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            general = [dict(item) for item in payload if isinstance(item, dict)]
    except (requests.RequestException, ValueError) as exc:
        errors += 1
        logger.warning("failed to fetch general market news: %s", exc)

    date_string = publication_date.isoformat()
    for symbol, security_id in symbols.items():
        try:
            time.sleep(delay)
            response = session.get(
                f"{FINNHUB_BASE_URL}/company-news",
                params={
                    "symbol": symbol,
                    "from": date_string,
                    "to": date_string,
                    "token": api_key,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                continue
            for raw_item in payload:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item["_security_id"] = security_id
                item["_finnhub_symbol"] = symbol
                company.append(item)
        except (requests.RequestException, ValueError) as exc:
            errors += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "skipping company-news for %s: %s",
                symbol,
                f"HTTP {status}" if status else type(exc).__name__,
            )

    return FinnhubNewsPayload(general=general, company=company, errors=errors)
