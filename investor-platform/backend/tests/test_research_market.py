"""Verify exact public identity mapping and quarter-specific observed close context."""

import io
import json
from datetime import date, datetime
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from test_research_activity import manager, position, quarter

from investor_platform import market, research_market, tiingo
from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import MarketCache, Owner, ResearchManager, Workspace
from investor_platform.research_market import Mapping, parse_mapping, summarize


def mapped_row(symbol: str = "SYNTH", composite: str = "BBG000000001") -> dict:
    """Return a synthetic exact US composite equity mapping."""
    return {
        "ticker": symbol,
        "compositeFIGI": composite,
        "marketSector": "Equity",
        "exchCode": "US",
    }


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([], "No exact"),
        ([mapped_row(), mapped_row(composite="BBG000000002")], "Ambiguous"),
        ([mapped_row(), mapped_row(symbol="OTHER")], "Ambiguous"),
        ([mapped_row(symbol="SYNTH/A")], "unsupported"),
        ([mapped_row(symbol="SYNTH.A")], "unsupported"),
        ([mapped_row() | {"marketSector": "Corp"}], "verified"),
        ([mapped_row() | {"exchCode": "LN"}], "verified"),
        ([mapped_row(composite="")], "verified"),
        ([mapped_row() | {"ticker": None}], "verified"),
        ([mapped_row(), None], "verified"),
    ],
)
def test_mapping_rejects_ambiguous_or_unsupported_identity(rows: list[dict], reason: str) -> None:
    """A matching issuer name cannot substitute for one complete supported security identity."""
    result: Mapping = parse_mapping({"data": rows})
    assert result["symbol"] is None and result["composite_figi"] is None
    assert reason in result["reason"]


def test_mapping_accepts_repeated_records_only_for_same_composite_and_ticker() -> None:
    """Multiple venue records may agree on one US composite without selecting a first match."""
    result: Mapping = parse_mapping({"data": [mapped_row(), mapped_row()]})
    assert result["symbol"] == "SYNTH" and result["composite_figi"] == "BBG000000001"
    assert result["reason"] is None
    assert datetime.fromisoformat(result["mapped_at"]).tzinfo is not None


def test_summary_uses_daily_close_mean_and_range_with_exact_quarter_boundaries() -> None:
    """Sessions receive equal weight; adjusted prices and adjacent-quarter closes are excluded."""
    closes: dict[date, Decimal] = {
        date(2026, 3, 31): Decimal("1"),
        date(2026, 4, 1): Decimal("10"),
        date(2026, 4, 8): Decimal("40"),
        date(2026, 6, 30): Decimal("70"),
        date(2026, 7, 1): Decimal("1000"),
    }
    history: market.History = market.History(
        closes, {day: Decimal("2") for day in closes}, splits={date(2026, 5, 1)}
    )
    result: dict = summarize(
        history, date(2026, 4, 1), date(2026, 6, 30), parse_mapping({"data": [mapped_row()]})
    )
    assert result["status"] == "available"
    assert Decimal(result["average_close_usd"]) == 40
    assert Decimal(result["low_close_usd"]) == 10 and Decimal(result["high_close_usd"]) == 70
    assert result["session_count"] == 3
    assert result["first_session"] == "2026-04-01" and result["last_session"] == "2026-06-30"
    assert result["symbol"] == "SYNTH" and result["currency"] == "USD"
    assert len(result["source_urls"]) == 2


def test_summary_retains_decimal_precision_and_rejects_empty_or_invalid_sessions() -> None:
    """Large exact closes do not round to float or Decimal's default 28-digit context."""
    day: date = date(2026, 4, 1)
    mapping: Mapping = parse_mapping({"data": [mapped_row()]})
    value: Decimal = Decimal("123456789012345678901234567890.12")
    result: dict = summarize(market.History({day: value}, {}), day, day, mapping)
    assert result["average_close_usd"] == str(value)
    closes: dict[date, Decimal]
    for closes in [{}, {day: Decimal("NaN")}, {day: Decimal("0")}]:
        with pytest.raises(ValueError):
            summarize(market.History(closes, {}), day, day, mapping)


def seed_research(database: Engine) -> None:
    """Create ordinary-share membership and an excluded option without portfolio records."""
    with Session(database) as session:
        owner: ResearchManager = manager(session, "public", "1001")
        quarter(
            session,
            owner,
            "2026-03-31",
            [position("111111111", "10", "100"), position("222222222", "10", "100")],
        )
        quarter(
            session,
            owner,
            "2026-06-30",
            [
                position("111111111", "20", "200"),
                position("222222222", "20", "200"),
                position("333333333", "20", "200"),
                position("444444444", "20", "200", option="CALL"),
            ],
        )
        session.commit()


def test_endpoint_caches_positive_and_negative_mappings_and_preserves_quarter_stats(
    database: Engine, db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One price result and explicit identity failures remain stable through provider outages."""
    seed_research(database)

    def mapping_response(request: Request, timeout: int) -> io.BytesIO:
        """Return synthetic mapping results for the public mapping request contract."""
        jobs: list[dict] = json.loads(request.data)
        assert all(
            job["idType"] == "ID_CUSIP"
            and job["exchCode"] == "US"
            and job["currency"] == "USD"
            and job["marketSecDes"] == "Equity"
            for job in jobs
        )
        answers: dict[str, dict] = {
            "111111111": {"data": [mapped_row()]},
            "222222222": {"data": [mapped_row(), mapped_row(symbol="OTHER")]},
            "333333333": {"warning": "No identifier found"},
        }
        return io.BytesIO(json.dumps([answers[job["idValue"]] for job in jobs]).encode())

    def history(symbol: str, start: date, end: date, **options: str) -> market.History:
        """Provide deterministic observed sessions through the normal provider cache."""
        closes: dict[date, Decimal] = {
            date(2026, 4, 1): Decimal("10"),
            date(2026, 6, 30): Decimal("30"),
        }
        return market.History(closes, dict(closes), exchange="NMS")

    monkeypatch.setattr(research_market, "urlopen", mapping_response)
    monkeypatch.setattr(market, "history", history)
    endpoint: str = (
        "/api/research/activity/market-context?quarter=2026-06-30"
        "&cusips=111111111,222222222,333333333"
    )
    result: dict = db_client.get(endpoint).json()
    assert result["quarter"] == "2026-06-30"
    available: dict = result["prices"]["111111111"]
    assert available["status"] == "available" and available["average_close_usd"] == "20"
    assert available["low_close_usd"] == "10" and available["high_close_usd"] == "30"
    assert available["session_count"] == 2
    assert result["prices"]["222222222"]["status"] == "unavailable"
    assert "Ambiguous" in result["prices"]["222222222"]["reason"]
    assert result["prices"]["333333333"]["average_close_usd"] is None
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(MarketCache)) == 4

    def offline(*args: str, **kwargs: str) -> None:
        """Simulate providers going offline after valid cache records exist."""
        raise OSError("Synthetic provider outage")

    monkeypatch.setattr(research_market, "urlopen", offline)
    monkeypatch.setattr(market, "history", offline)
    assert db_client.get(endpoint).json() == result
    previous: dict = db_client.get(
        endpoint.replace("2026-06-30", "2026-03-31").replace(",222222222,333333333", "")
    ).json()
    assert previous["prices"]["111111111"]["status"] == "unavailable"
    assert previous["prices"]["111111111"]["session_count"] == 0


def test_endpoint_sanitizes_provider_failure_and_recovers_without_retry_loop(
    database: Engine, db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quota failures return unavailable without exposing bodies or caching the outage."""
    seed_research(database)

    def quota(request: Request, timeout: int) -> None:
        """Simulate a quota failure containing a private provider diagnostic."""
        raise HTTPError(request.full_url, 429, "private-provider-diagnostic", {}, None)

    monkeypatch.setattr(research_market, "urlopen", quota)
    endpoint: str = "/api/research/activity/market-context?quarter=2026-06-30&cusips=111111111"
    response: Response = db_client.get(endpoint)
    assert response.status_code == 200
    result: dict = response.json()["prices"]["111111111"]
    assert result["status"] == "unavailable" and result["symbol"] is None
    assert "private-provider-diagnostic" not in response.text
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(MarketCache)) == 0

    def unmapped(request: Request, timeout: int) -> io.BytesIO:
        """Return an authoritative no-match result after the provider recovers."""
        return io.BytesIO(b'[{"warning":"No identifier found"}]')

    monkeypatch.setattr(research_market, "urlopen", unmapped)
    assert "No exact" in db_client.get(endpoint).json()["prices"]["111111111"]["reason"]
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(MarketCache)) == 1


def test_endpoint_rejects_unowned_options_and_invalid_requests(
    database: Engine, db_client: TestClient
) -> None:
    """Workspace membership and request validation run before any public provider request."""
    seed_research(database)
    with Session(database) as session:
        owner_id: UUID = uuid4()
        workspace_id: UUID = uuid4()
        session.add(Owner(id=owner_id))
        session.flush()
        session.add(Workspace(id=workspace_id, owner_id=owner_id))
        session.flush()
        foreign: ResearchManager = manager(session, "foreign", "1002", workspace_id)
        quarter(session, foreign, "2026-06-30", [position("555555555", "10", "100")])
        session.commit()
    endpoint: str = "/api/research/activity/market-context?quarter=2026-06-30&cusips="
    assert db_client.get(endpoint + "555555555").status_code == 404
    assert db_client.get(endpoint + "444444444").status_code == 404
    assert (
        db_client.get(
            endpoint + "111111111", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        db_client.get(endpoint + "111111111", headers={"Host": "evil.example"}).status_code == 400
    )
    assert db_client.get(endpoint + "11111111/").status_code == 422
    assert db_client.get(endpoint + ",".join(["111111111"] * 21)).status_code == 422
    assert (
        db_client.get(endpoint.replace("2026-06-30", "2026-06-01") + "111111111").status_code == 422
    )
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(MarketCache)) == 0


@pytest.mark.parametrize(
    ("exchange", "currency", "ticker", "available"),
    [
        ("NASDAQ", "USD", "SYNTH", True),
        ("UNKNOWN", "USD", "SYNTH", False),
        ("NASDAQ", "EUR", "SYNTH", False),
        ("NASDAQ", "USD", "OTHER", False),
    ],
)
def test_configured_fallback_checks_ticker_currency_and_us_exchange(
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    exchange: str,
    currency: str,
    ticker: str,
    available: bool,
) -> None:
    """Fallback retains real close statistics only when public provider identity validates."""
    monkeypatch.setenv("TIINGO_API_KEY", "synthetic-test-token")

    def offline(symbol: str, start: date, end: date, **options: str) -> market.History:
        """Simulate the primary history provider being unavailable."""
        raise OSError("Synthetic primary-provider outage")

    def response(path: str, key: str) -> dict | list[dict]:
        """Provide a complete synthetic Tiingo response through its existing parser and cache."""
        if "/prices?" not in path:
            return {"ticker": ticker, "exchangeCode": exchange, "currency": currency}
        return [
            {
                "date": "2026-04-01T00:00:00Z",
                "close": "40",
                "adjClose": "2",
                "divCash": "0",
                "splitFactor": "1",
            }
        ]

    monkeypatch.setattr(market, "history", offline)
    monkeypatch.setattr(tiingo, "get", response)
    result: dict = research_market.price_context(
        database,
        LOCAL_WORKSPACE,
        parse_mapping({"data": [mapped_row()]}),
        date(2026, 4, 1),
        date(2026, 6, 30),
    )
    assert result["status"] == ("available" if available else "unavailable")
    assert result["average_close_usd"] == ("40" if available else None)
    assert "synthetic-test-token" not in str(result)
    if available:
        assert result["session_count"] == 1
        assert result["source_urls"][-1].startswith("https://api.tiingo.com/")


def test_twenty_security_request_respects_anonymous_mapping_batch_limit(
    database: Engine, db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full page can cache twenty no-match results under the ten-job provider contract."""
    cusips: list[str] = [f"{100000000 + number:09}" for number in range(20)]
    with Session(database) as session:
        owner: ResearchManager = manager(session, "page", "1001")
        quarter(
            session,
            owner,
            "2026-06-30",
            [position(cusip, "10", "100") for cusip in cusips],
        )
        session.commit()

    def provider(request: Request, timeout: int) -> io.BytesIO:
        """Emulate the anonymous provider's maximum payload size and no-match result."""
        jobs: list[dict] = json.loads(request.data)
        if len(jobs) > 10:
            raise HTTPError(request.full_url, 413, "Too many mapping jobs", {}, None)
        return io.BytesIO(json.dumps([{"warning": "No identifier found"} for job in jobs]).encode())

    monkeypatch.setattr(research_market, "urlopen", provider)
    result: dict = db_client.get(
        "/api/research/activity/market-context?quarter=2026-06-30&cusips=" + ",".join(cusips)
    ).json()
    assert set(result["prices"]) == set(cusips)
    assert all("No exact" in item["reason"] for item in result["prices"].values())
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(MarketCache)) == 20
