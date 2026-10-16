"""Check cached Post-mortem results against real ledger, ownership and price changes."""

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from helpers import DAYS, ledger, stock_report, trade
from httpx import Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_corrections import correction, replacement

from investor_platform import market, post_mortem_cache
from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.financial import Record
from investor_platform.market import History
from investor_platform.models import Account, MarketCache, Owner, Workspace


def warm_report(client: TestClient, account: str) -> Response:
    """Populate provider inputs, then calculate under their settled revision."""
    assert stock_report(client, account).status_code == 200
    result: Response = stock_report(client, account)
    assert result.status_code == 200, result.text
    return result


def test_repeated_report_preserves_bytes_no_store_and_ownership(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    database: Engine,
) -> None:
    """A reused private report still requires ownership and valid request dates."""
    account: str = portfolio[0]
    before: Record = ledger(db_client, account)
    original: Response = warm_report(db_client, account)
    repeated: Response = stock_report(db_client, account)
    assert repeated.content == original.content
    assert repeated.headers["cache-control"] == "no-store"
    assert stock_report(db_client, account, end="2099-01-01").status_code == 422
    assert ledger(db_client, account) == before
    owner: UUID = uuid4()
    workspace: UUID = uuid4()
    with Session(database) as session:
        session.add(Owner(id=owner))
        session.flush()
        session.add(Workspace(id=workspace, owner_id=owner))
        session.commit()

    def outsider() -> Actor:
        """Exercise a different owner's access to an already cached account."""
        return Actor(owner, workspace)

    app.dependency_overrides[get_actor] = outsider
    try:
        assert stock_report(db_client, account).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_new_trade_correction_and_cancellation_change_cached_attribution(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
) -> None:
    """Active ledger changes replace stale stock gains without clearing caches by hand."""
    account: str = portfolio[0]
    original: Record = warm_report(db_client, account).json()
    sale: Response = trade(
        db_client,
        account,
        kind="sell",
        quantity="5",
        price="110",
        ticker="AAA",
        exchange="NYSE",
        effective_date="2026-01-05",
    )
    assert sale.status_code == 201
    sold: Record = stock_report(db_client, account).json()
    assert Decimal(sold["attribution"][0]["gain"]) == 155
    url: str
    body: dict
    preview: Response
    url, body, preview = correction(
        db_client, account, sale.json(), replacement(sale.json(), price="120")
    )
    body["expected_revision"] = preview.json()["revision"]
    corrected: Response = db_client.post(url, json=body)
    assert corrected.status_code == 200
    changed: Record = stock_report(db_client, account).json()
    assert Decimal(changed["attribution"][0]["gain"]) == 205
    entry: Record = next(e for e in ledger(db_client, account)["entries"] if e["kind"] == "sell")
    url, body, preview = correction(db_client, account, entry, None)
    body["expected_revision"] = preview.json()["revision"]
    assert db_client.post(url, json=body).status_code == 200
    cancelled: Record = stock_report(db_client, account).json()
    assert cancelled["attribution"] == original["attribution"]


def test_price_revision_and_expiry_refresh_cached_report(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    expire_prices: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider refresh and the bounded lifetime each force a fresh result."""
    account: str = portfolio[0]
    clock: list[float] = [100.0]
    monkeypatch.setattr(post_mortem_cache, "monotonic", lambda: clock[0])
    original: Record = warm_report(db_client, account).json()
    portfolio[1]["AAA"].close[DAYS[-1]] = Decimal(130)
    portfolio[1]["AAA"].adjusted[DAYS[-1]] = Decimal(130)
    expire_prices()
    refreshed: Response = stock_report(db_client, account)
    assert refreshed.status_code == 200, refreshed.text
    assert Decimal(refreshed.json()["attribution"][0]["gain"]) == 300
    assert refreshed.json()["attribution"] != original["attribution"]
    settled: Response = warm_report(db_client, account)
    assert stock_report(db_client, account).content == settled.content
    clock[0] += post_mortem_cache.TTL_SECONDS + 1
    expired: Response = stock_report(db_client, account)
    assert expired.json()["attribution"] == settled.json()["attribution"]
    assert expired.json()["fetched_at"] != settled.json()["fetched_at"]


def test_market_failure_is_not_remembered(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same request can recover immediately after a failed provider attempt."""
    account: str = portfolio[0]
    healthy: Callable[[str, date, date], History] = market.history

    def offline(symbol: str, start: date, end: date) -> History:
        """Represent an actual provider outage before any prices can be cached."""
        raise OSError("Synthetic provider unavailable")

    monkeypatch.setattr(market, "history", offline)
    assert stock_report(db_client, account).status_code == 503
    monkeypatch.setattr(market, "history", healthy)
    recovered: Response = stock_report(db_client, account)
    assert recovered.status_code == 200, recovered.text
    assert Decimal(recovered.json()["attribution"][0]["gain"]) == 210


def test_capacity_evicts_old_reports_without_mixing_request_periods(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded cache evicts an old period while preserving a recently used report."""
    account: str = portfolio[0]
    monkeypatch.setattr(post_mortem_cache, "MAX_REPORTS", 2)
    original: Response = warm_report(db_client, account)
    shorter: Response = stock_report(db_client, account, end="2026-01-05")
    later: Response = stock_report(db_client, account, start="2026-01-05")
    assert shorter.status_code == later.status_code == 200
    assert stock_report(db_client, account, end="2026-01-05").content == shorter.content
    recomputed: Response = stock_report(db_client, account)
    assert recomputed.json()["attribution"] == original.json()["attribution"]
    assert recomputed.json()["fetched_at"] != original.json()["fetched_at"]


def test_changed_account_funding_policy_is_validated_before_cached_response(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    database: Engine,
) -> None:
    """A cached valid result must not bypass changed account-policy safeguards."""
    account: str = portfolio[0]
    warm_report(db_client, account)
    with Session(database) as session:
        model: Account = session.get(Account, UUID(account))
        model.reconstruction = {"cash_method": "purchase_shortfall", "funding_status": "inferred"}
        session.commit()
    rejected: Response = stock_report(db_client, account)
    assert rejected.status_code == 422
    assert "opening placeholder" in rejected.json()["detail"]


def test_nonmax_provider_revision_invalidates_cached_report(
    db_client: TestClient,
    portfolio: tuple[str, dict[str, History]],
    database: Engine,
) -> None:
    """A slower price refresh invalidates results even after a newer other-symbol refresh."""
    account: str = portfolio[0]
    warm_report(db_client, account)
    base: datetime = datetime.now(UTC) - timedelta(seconds=30)
    with Session(database) as session:
        rows: list[MarketCache] = list(session.scalars(select(MarketCache)))
        row: MarketCache
        for row in rows:
            row.fetched_at = base if row.symbol.startswith("AAA:") else base + timedelta(seconds=20)
        session.commit()
    original: Record = warm_report(db_client, account).json()
    with Session(database) as session:
        rows = list(session.scalars(select(MarketCache)))
        price: MarketCache = next(row for row in rows if row.symbol.startswith("AAA:"))
        payload: dict = deepcopy(price.payload)
        payload["close"]["2026-01-06"] = "130"
        payload["adjusted"]["2026-01-06"] = "130"
        price.payload = payload
        price.fetched_at = base + timedelta(seconds=10)
        session.commit()
        assert max(row.fetched_at for row in rows) == base + timedelta(seconds=20)
    refreshed: Response = stock_report(db_client, account)
    assert refreshed.status_code == 200, refreshed.text
    assert Decimal(original["attribution"][0]["gain"]) == 210
    assert Decimal(refreshed.json()["attribution"][0]["gain"]) == 300
