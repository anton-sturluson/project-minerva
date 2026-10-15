"""Exercise admitted history against real synthetic ledgers and bounded quote inputs."""

import hashlib
import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import cash, ledger, trade
from httpx import Response
from psycopg import Connection, connect, sql
from psycopg.errors import RaiseException
from psycopg.rows import dict_row
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform import financial_api
from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.financial import Json, Record, Row, check_schema, record, records
from investor_platform.financial_history import METRICS, VERSION, import_release, read_release
from investor_platform.financial_history_report import build_report
from investor_platform.ledger import LedgerView
from investor_platform.models import Owner, Workspace


def release_row(ticker: str = "AAA", *, currency: str = "USD", factor: str = "1") -> Record:
    """Declare five independently reviewed synthetic measures and matching prior LTM amounts."""
    current: Record = {}
    prior: Record = {}
    key: str
    for key in METRICS:
        current[key] = {
            "status": "available",
            "value": "0.4" if "margin" in key else "2",
            "method": "synthetic reviewed statement measure",
            "inputs": [],
        }
        prior[key] = {
            "status": "available",
            "value": "0.3" if "margin" in key else "1",
            "method": "synthetic reviewed statement measure",
            "inputs": [],
        }
    return {
        "ticker": ticker,
        "exchange": "NYSE",
        "year": 2025,
        "issuer_key": "example:" + ticker,
        "instrument_type": "company",
        "currency": currency,
        "shares_per_traded_unit": factor,
        "share_basis": "Synthetic common rights and common split basis reviewed for both periods",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
        "prior_period": {"start": "2024-01-01", "end": "2024-12-31"},
        "metrics": current,
        "prior_metrics": prior,
    }


def release_payload(rows: list[Record] | None = None) -> Record:
    """Pin a wholly synthetic source packet and independent review receipt as exact bytes."""
    packet: str = json.dumps({"observations": [{"id": "input", "value": "synthetic evidence"}]})
    sha: str = hashlib.sha256(packet.encode()).hexdigest()
    receipt: str = json.dumps({"status": "independent_source_review_passed", "packet_sha256": sha})
    selected: list[Record] = deepcopy(rows if rows is not None else [release_row()])
    row: Record
    for row in selected:
        group: str
        for group in ("metrics", "prior_metrics"):
            metric: Record
            for metric in (record(v) for v in record(row.get(group, {})).values()):
                metric["inputs"] = [{"packet_sha256": sha, "ids": ["input"]}]
    return {
        "schema_version": VERSION,
        "release_id": str(uuid4()),
        "review_receipts": [
            {"content": receipt, "sha256": hashlib.sha256(receipt.encode()).hexdigest()}
        ],
        "evidence": {"packets": {sha: packet}},
        "records": selected,
    }


def snapshot(*values: tuple[str, str | None]) -> Record:
    """Supply dated equity-only values independent of any account cash balance."""
    return {
        "holdings_date": "2025-12-31",
        "base_currency": "USD",
        "holdings": [
            {
                "ticker": ticker,
                "exchange": "NYSE",
                "market_value": value,
                "issuer_key": "example:" + ticker,
            }
            for ticker, value in values
        ],
    }


def weighted(report: Record, key: str = "gross_margin") -> Record:
    """Read a bounded aggregate without recreating its arithmetic."""
    return record(record(report["weighted_ratios"])[key])


def test_native_ratios_usd_share_conversion_and_fund_coverage() -> None:
    """Foreign common shares convert once while a fund stays in selected equity coverage."""
    company: Record = release_row(currency="EUR", factor="2")
    fund: Record = {
        "ticker": "FUND",
        "exchange": "NYSE",
        "year": 2025,
        "issuer_key": "example:FUND",
        "instrument_type": "fund",
        "currency": "USD",
    }
    result: Record = build_report(
        release_payload([company, fund]),
        snapshot(("AAA", "600"), ("FUND", "400")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1), "EUR": Decimal("1.5")},
    )
    assert Decimal(str(weighted(result)["value"])) == Decimal("0.4")
    assert Decimal(str(weighted(result)["coverage"])) == Decimal("0.6")
    per_share: Record = record(record(result["weighted_company_per_share"])["weighted_company_eps"])
    assert Decimal(str(per_share["value"])) == Decimal("6")
    assert Decimal(str(record(per_share["comparison"])["prior_value"])) == Decimal("3")
    measure: Record = record(
        record(records(result["companies"])[0]["per_share_metrics"])["basic_eps"]
    )
    assert measure["native_value"] == "2" and measure["currency"] == "EUR" and measure["inputs"]
    assert records(weighted(result)["exclusions"])[0]["reason"] == "Fund excluded"
    assert result["synthetic"] is False and result["api_status"] == "partial"


def test_missing_fx_does_not_withhold_native_currency_ratios() -> None:
    """A missing USD rate excludes only per-share amounts rather than inventing FX."""
    result: Record = build_report(
        release_payload([release_row(currency="EUR")]),
        snapshot(("AAA", "600")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    assert weighted(result)["value"] is not None
    assert (
        record(record(result["weighted_company_per_share"])["weighted_company_eps"])["value"]
        is None
    )


def test_incomplete_quotes_withhold_all_weighted_results_and_weights() -> None:
    """An unpriced holding cannot vanish from the selected-equity denominator."""
    result: Record = build_report(
        release_payload(),
        snapshot(("AAA", "600"), ("UNKNOWN", None)),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
        pricing_complete=False,
    )
    assert result["api_status"] == "unavailable"
    assert all(c["equity_weight"] is None for c in records(result["companies"]))
    group: str
    for group in ("weighted_ratios", "weighted_company_per_share"):
        metric: Json
        for metric in record(result[group]).values():
            assert record(metric)["value"] is None and record(metric)["coverage"] is None


@pytest.mark.parametrize("missing_side", [None, "metrics", "prior_metrics"])
def test_comparisons_use_exact_current_contributors(missing_side: str | None) -> None:
    """Prior-only data is ignored; missing prior data for a current contributor blocks growth."""
    other: Record = release_row("BBB")
    record(record(other["metrics"])["basic_eps"])["value"] = "10"
    record(record(other["prior_metrics"])["basic_eps"])["value"] = "8"
    if missing_side:
        record(record(other[missing_side])["basic_eps"]).update(
            status="unavailable", value=None, reason="Not collected"
        )
    result: Record = build_report(
        release_payload([release_row(), other]),
        snapshot(("AAA", "600"), ("BBB", "400")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    aggregate: Record = record(record(result["weighted_company_per_share"])["weighted_company_eps"])
    compared: Record = record(aggregate["comparison"])
    if missing_side == "prior_metrics":
        assert compared["prior_value"] is None and compared["status"] == "unavailable"
        assert compared["percent_change"] is None
    elif missing_side == "metrics":
        assert Decimal(str(aggregate["coverage"])) == Decimal("0.6")
        assert Decimal(str(aggregate["value"])) == 2
        assert Decimal(str(compared["prior_value"])) == 1
        assert Decimal(str(compared["percent_change"])) == 1
    else:
        assert Decimal(str(aggregate["coverage"])) == 1
        assert Decimal(str(aggregate["value"])) == Decimal("5.2")
        assert Decimal(str(compared["prior_value"])) == Decimal("3.8")
        assert Decimal(str(compared["percent_change"])) > 0


@pytest.mark.parametrize("prior", ["0", "-1"])
def test_nonpositive_prior_amount_is_not_meaningful(prior: str) -> None:
    """Zero and loss baselines preserve raw prior figures without misleading percentages."""
    row: Record = release_row()
    record(record(row["prior_metrics"])["basic_eps"])["value"] = prior
    result: Record = build_report(
        release_payload([row]),
        snapshot(("AAA", "600")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    compared: Record = record(
        record(record(result["weighted_company_per_share"])["weighted_company_eps"])["comparison"]
    )
    assert Decimal(str(compared["prior_value"])) == Decimal(prior)
    assert compared["status"] == "not_meaningful" and compared["percent_change"] is None


@pytest.fixture
def admitted_history(
    database: Engine, db_client: TestClient
) -> Iterator[tuple[TestClient, Connection[Row], str]]:
    """Import one synthetic reviewed release into a disposable financial namespace."""
    schema: str = "investor_financial_test_" + uuid4().hex
    previous: str | None = app.state.financial_schema
    app.state.financial_schema = schema
    conn: Connection[Row] = connect(
        database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg", "postgresql"
        ),
        row_factory=dict_row,
    )
    check_schema(conn, schema, create=True)
    conn.commit()
    import_release(conn, schema, release_payload(), reviewed=True)
    try:
        yield db_client, conn, schema
    finally:
        app.state.financial_schema = previous
        conn.rollback()
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def test_release_replay_conflict_immutability_and_no_evidence_drift(
    admitted_history: tuple[TestClient, Connection[Row], str],
) -> None:
    """Reviewed release bytes replay once and cannot change through UUID reuse or SQL update."""
    client: TestClient
    conn: Connection[Row]
    schema: str
    client, conn, schema = admitted_history
    payload: Record = read_release(conn, schema)
    conn.commit()
    assert import_release(conn, schema, payload, reviewed=True)["created"] is False
    changed: Record = deepcopy(payload)
    record(record(records(changed["records"])[0]["metrics"])["basic_eps"])["value"] = "99"
    with pytest.raises(ValueError, match="UUID"):
        import_release(conn, schema, changed, reviewed=True)
    with pytest.raises(RaiseException):
        with conn.transaction():
            conn.execute(
                sql.SQL("UPDATE {}.history_releases SET payload='{}'::jsonb").format(
                    sql.Identifier(schema), sql.SQL("{}")
                )
            )
    assert read_release(conn, schema) == payload


def quote_values(
    view: LedgerView, base_currency: str, provisional: bool, **options: Engine | UUID | date
) -> dict[str, bool | list[dict[str, str | Decimal | date]]]:
    """Supply deterministic price-boundary values while real ledger replay determines holdings."""
    end: date = options["end"] if isinstance(options.get("end"), date) else date(2025, 12, 31)
    return {
        "holdings": [
            {
                "ticker": h.security.ticker,
                "exchange": h.security.exchange,
                "value": h.quantity * Decimal(100),
                "quote_date": end,
            }
            for h in view.holdings
        ],
        "complete": True,
    }


def test_account_api_uses_yearend_positions_excludes_cash_and_preserves_ledger(
    admitted_history: tuple[TestClient, Connection[Row], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read selected year-end holdings without changing synthetic cash or trades."""
    client: TestClient = admitted_history[0]
    account: str = client.post(
        "/api/accounts", json={"name": "Synthetic financial account", "base_currency": "USD"}
    ).json()["id"]
    assert cash(client, account, "opening_cash", "10000", day="2025-01-02").status_code == 201
    assert (
        trade(
            client,
            account,
            quantity="6",
            price="100",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2025-01-02",
        ).status_code
        == 201
    )
    assert (
        trade(
            client,
            account,
            quantity="4",
            price="100",
            ticker="LATER",
            exchange="NYSE",
            effective_date="2026-01-02",
        ).status_code
        == 201
    )
    before: Record = ledger(client, account)
    monkeypatch.setattr(financial_api, "value_records", quote_values)
    response: Response = client.get(f"/api/accounts/{account}/financials?year=2025")
    assert response.status_code == 200, response.text
    result: Record = response.json()
    assert result["account_id"] == account and result["synthetic"] is False
    assert [c["ticker"] for c in records(result["companies"])] == ["AAA"]
    assert records(result["companies"])[0]["equity_weight"] == "1"
    assert Decimal(str(weighted(result)["value"])) == Decimal("0.4")
    assert ledger(client, account) == before
    assert response.headers["cache-control"] == "no-store"


def test_unknown_account_no_history_and_auth_boundaries(
    admitted_history: tuple[TestClient, Connection[Row], str],
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown or unowned accounts never receive a global pilot fallback."""
    client: TestClient = admitted_history[0]
    assert client.get(f"/api/accounts/{uuid4()}/financials?year=2025").status_code == 404
    account: str = client.post(
        "/api/accounts", json={"name": "Synthetic no-history account", "base_currency": "USD"}
    ).json()["id"]
    monkeypatch.setattr(financial_api, "value_records", quote_values)
    assert cash(client, account, "opening_cash", "1000", day="2025-01-02").status_code == 201
    assert (
        trade(
            client,
            account,
            quantity="1",
            ticker="UNKNOWN",
            exchange="NYSE",
            effective_date="2025-01-02",
        ).status_code
        == 201
    )
    missing: Record = client.get(f"/api/accounts/{account}/financials?year=2025").json()
    assert missing["api_status"] == "unavailable"
    assert not any(c["ticker"] == "AAA" for c in records(missing["companies"]))
    assert client.get(f"/api/accounts/{account}/financials?year=1899").status_code == 422
    owner: UUID = uuid4()
    workspace: UUID = uuid4()
    session: Session
    with Session(database) as session:
        session.add(Owner(id=owner))
        session.flush()
        session.add(Workspace(id=workspace, owner_id=owner))
        session.commit()

    def outsider() -> Actor:
        """Use another owned workspace to exercise the real account ownership predicate."""
        return Actor(owner, workspace)

    app.dependency_overrides[get_actor] = outsider
    try:
        assert client.get(f"/api/accounts/{account}/financials?year=2025").status_code == 404
    finally:
        app.dependency_overrides.clear()
    isolated: FastAPI = FastAPI()
    isolated.state.engine = database
    isolated.include_router(financial_api.router)
    with TestClient(isolated) as unauthenticated:
        assert (
            unauthenticated.get(f"/api/accounts/{account}/financials?year=2025").status_code == 403
        )


def test_zero_and_tiny_converted_per_share_values_remain_plain_decimals() -> None:
    """Zero and tiny native amounts survive FX conversion and later decimal parsing."""
    row: Record = release_row(currency="TWD", factor="5")
    record(record(row["metrics"])["basic_eps"])["value"] = "0.00"
    record(record(row["metrics"])["fcf_per_basic_share"])["value"] = "0.00000001"
    result: Record = build_report(
        release_payload([row]),
        snapshot(("AAA", "100")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1), "TWD": Decimal("0.03065")},
    )
    shares: Record = record(result["weighted_company_per_share"])
    eps: Record = record(shares["weighted_company_eps"])
    fcf: Record = record(shares["weighted_company_fcf_per_share"])
    assert Decimal(str(eps["value"])) == 0
    assert fcf["value"] == "0.0000000015325"
    assert "E" not in str(eps["value"])
    assert "E" not in str(fcf["value"])
