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

from investor_platform import financial_api, market
from investor_platform.app import app
from investor_platform.db import Actor, get_actor
from investor_platform.financial import Json, Record, Row, check_schema, record, records
from investor_platform.financial_history import (
    METRICS,
    VERSION,
    import_release,
    read_release,
    validate_release,
)
from investor_platform.financial_history_report import (
    SHARES,
    add_portfolio_comparisons,
    build_report,
)
from investor_platform.ledger import LedgerView
from investor_platform.models import Owner, Workspace

FUND: Record = {
    "ticker": "FUND",
    "exchange": "NYSE",
    "year": 2025,
    "issuer_key": "example:FUND",
    "instrument_type": "fund",
    "currency": "USD",
}


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


@pytest.mark.parametrize("fund_value", ["400", None])
def test_native_ratios_usd_share_conversion_excludes_funds(fund_value: str | None) -> None:
    """Funds leave company weights, details and notes even without a market quote."""
    company: Record = release_row(currency="EUR", factor="2")
    result: Record = build_report(
        release_payload([company, FUND]),
        snapshot(("AAA", "600"), ("FUND", fund_value)),
        2025,
        "synthetic-account",
        {"USD": Decimal(1), "EUR": Decimal("1.5")},
    )
    assert Decimal(str(weighted(result)["value"])) == Decimal("0.4")
    assert Decimal(str(weighted(result)["coverage"])) == 1
    assert records(result["companies"])[0]["equity_weight"] == "1"
    assert [c["ticker"] for c in records(result["companies"])] == ["AAA"]
    assert [h["ticker"] for h in records(record(result["market_value_snapshot"])["holdings"])] == [
        "AAA"
    ]
    per_share: Record = record(record(result["weighted_company_per_share"])["weighted_company_eps"])
    assert Decimal(str(per_share["value"])) == Decimal("6")
    assert record(per_share["comparison"])["prior_value"] is None
    assert Decimal(
        str(
            record(record(records(result["companies"])[0]["per_share_comparisons"])["basic_eps"])[
                "prior_value"
            ]
        )
    ) == Decimal("3")
    measure: Record = record(
        record(records(result["companies"])[0]["per_share_metrics"])["basic_eps"]
    )
    assert measure["native_value"] == "2" and measure["currency"] == "EUR" and measure["inputs"]
    assert not weighted(result)["exclusions"]
    assert result["synthetic"] is False and result["api_status"] == "available"


def test_unknown_companies_remain_in_company_weights_and_omissions() -> None:
    """Absent company data is not an implicit fund classification."""
    result: Record = build_report(
        release_payload([release_row(), FUND]),
        snapshot(("AAA", "600"), ("UNKNOWN", "400"), ("FUND", "500")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    assert Decimal(str(weighted(result)["coverage"])) == Decimal("0.6")
    assert [c["ticker"] for c in records(result["companies"])] == ["AAA", "UNKNOWN"]
    assert records(result["companies"])[0]["equity_weight"] == "0.6"
    assert len(records(weighted(result)["exclusions"])) == 1
    assert result["api_status"] == "partial"


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


@pytest.mark.parametrize("prior_ticker", ["AAA", "SOLD"])
def test_portfolio_comparisons_use_independent_weights_fx_and_constituents(
    prior_ticker: str,
) -> None:
    """Prior headlines equal the prior snapshot, not current holdings or embedded comparators."""
    now: Record = release_row(currency="EUR")
    record(record(now["prior_metrics"])["basic_eps"])["value"] = "999"
    old: Record = release_row(prior_ticker, currency="EUR")
    old["year"] = 2024
    record(record(old["metrics"])["basic_eps"])["value"] = "8"
    old_other: Record = release_row("OLD")
    old_other["year"] = 2024
    release: Record = release_payload([now, old, old_other])
    current: Record = build_report(
        release,
        snapshot(("AAA", "100")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1), "EUR": Decimal(2)},
    )
    previous: Record = build_report(
        release,
        snapshot((prior_ticker, "20"), ("OLD", "80")),
        2024,
        "synthetic-account",
        {"USD": Decimal(1), "EUR": Decimal("1.5")},
    )
    add_portfolio_comparisons(current, previous, 2025)
    metric: Record = record(record(current["weighted_company_per_share"])["weighted_company_eps"])
    prior_metric: Record = record(
        record(previous["weighted_company_per_share"])["weighted_company_eps"]
    )
    compared: Record = record(metric["comparison"])
    assert Decimal(str(metric["value"])) == 4
    assert compared["prior_value"] == prior_metric["value"]
    assert Decimal(str(compared["prior_value"])) == 4
    assert compared["status"] == "calculated" and Decimal(str(compared["percent_change"])) == 0
    assert (
        record(current["comparison_inputs"])["market_value_snapshot"]
        == previous["market_value_snapshot"]
    )


def test_prior_price_failure_preserves_current_values_and_reports_reason() -> None:
    """An unavailable prior snapshot must not erase admitted current figures."""
    current: Record = build_report(
        release_payload(), snapshot(("AAA", "100")), 2025, "synthetic-account", {"USD": Decimal(1)}
    )
    add_portfolio_comparisons(
        current, None, 2025, reason="Prior portfolio market prices unavailable"
    )
    metric: Record = record(record(current["weighted_company_per_share"])["weighted_company_eps"])
    assert metric["value"] == "2" and current["api_status"] == "partial"
    assert record(metric["comparison"])["prior_value"] is None
    assert record(metric["comparison"])["reason"] == "Prior portfolio market prices unavailable"


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
    old: Record = release_row()
    old["year"] = 2024
    record(record(old["metrics"])["basic_eps"])["value"] = prior
    prior_report: Record = build_report(
        release_payload([old]),
        snapshot(("AAA", "600")),
        2024,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    add_portfolio_comparisons(result, prior_report, 2025)
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
    import_release(conn, schema, release_payload([release_row(), FUND]), reviewed=True)
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


def test_unpriced_fund_does_not_block_company_report(
    admitted_history: tuple[TestClient, Connection[Row], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fund provider outage cannot block the real company valuation path."""
    client: TestClient = admitted_history[0]
    account: str = client.post(
        "/api/accounts", json={"name": "Synthetic mixed account", "base_currency": "USD"}
    ).json()["id"]
    assert cash(client, account, "opening_cash", "1000", day="2025-01-02").status_code == 201
    ticker: str
    for ticker in ("AAA", "FUND"):
        assert (
            trade(
                client,
                account,
                quantity="1",
                price="100",
                ticker=ticker,
                exchange="NYSE",
                effective_date="2025-01-02",
            ).status_code
            == 201
        )
    before: Record = ledger(client, account)

    def prices(symbol: str, start: date, end: date) -> market.History:
        """Return a company close while the fund's provider is unavailable."""
        if symbol == "FUND":
            raise OSError("Fund quote unavailable")
        return market.History({end: Decimal(120)}, {end: Decimal(120)}, exchange="NYQ")

    monkeypatch.setattr(market, "history", prices)
    response: Response = client.get(f"/api/accounts/{account}/financials?year=2025")
    assert response.status_code == 200, response.text
    result: Record = response.json()
    assert result["api_status"] == "available"
    assert [c["ticker"] for c in records(result["companies"])] == ["AAA"]
    assert records(result["companies"])[0]["equity_weight"] == "1"
    assert not weighted(result)["exclusions"]
    assert ledger(client, account) == before


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


@pytest.mark.parametrize("prior_price_failure", [False, True])
def test_api_compares_actual_previous_portfolio_and_preserves_current_on_prior_failure(
    admitted_history: tuple[TestClient, Connection[Row], str],
    monkeypatch: pytest.MonkeyPatch,
    prior_price_failure: bool,
) -> None:
    """Turnover uses the prior standalone report; prior quote failure keeps current figures."""
    client: TestClient = admitted_history[0]
    old: Record = release_row()
    old["year"] = 2024
    record(record(old["metrics"])["basic_eps"])["value"] = "8"
    now: Record = release_row()
    record(record(now["prior_metrics"])["basic_eps"])["value"] = "999"
    replacement: Record = release_row("BBB")
    record(record(replacement["metrics"])["basic_eps"])["value"] = "10"
    ratio_key: str
    old_value: str
    current_value: str
    replacement_value: str
    for ratio_key, old_value, current_value, replacement_value in (
        ("gross_margin", "0.25", "0.4", "0.8"),
        ("operating_margin", "0.15", "0.3", "0.5"),
        ("fcf_margin_after_disclosed_capex", "0.05", "0.1", "0.2"),
    ):
        record(record(old["metrics"])[ratio_key])["value"] = old_value
        record(record(now["metrics"])[ratio_key])["value"] = current_value
        record(record(now["prior_metrics"])[ratio_key])["value"] = "999"
        record(record(replacement["metrics"])[ratio_key])["value"] = replacement_value
    import_release(
        admitted_history[1],
        admitted_history[2],
        release_payload([old, now, replacement, FUND]),
        reviewed=True,
    )
    account: str = client.post(
        "/api/accounts", json={"name": "Synthetic changing portfolio", "base_currency": "USD"}
    ).json()["id"]
    assert cash(client, account, "opening_cash", "10000", day="2024-01-02").status_code == 201
    assert (
        trade(
            client,
            account,
            quantity="6",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2024-01-03",
        ).status_code
        == 201
    )
    assert (
        trade(
            client,
            account,
            kind="sell",
            quantity="3",
            ticker="AAA",
            exchange="NYSE",
            effective_date="2025-01-03",
        ).status_code
        == 201
    )
    assert (
        trade(
            client,
            account,
            quantity="4",
            ticker="BBB",
            exchange="NYSE",
            effective_date="2025-01-03",
        ).status_code
        == 201
    )
    before: Record = ledger(client, account)

    def dated_quotes(view: LedgerView, currency: str, provisional: bool, **options: object) -> dict:
        """Price real replayed holdings with a bounded prior-year provider failure."""
        result: dict = quote_values(view, currency, provisional, **options)
        if prior_price_failure and options["end"] == date(2024, 12, 31):
            result["complete"] = False
        return result

    monkeypatch.setattr(financial_api, "value_records", dated_quotes)
    response: Response = client.get(f"/api/accounts/{account}/financials?year=2025")
    assert response.status_code == 200, response.text
    current: Record = response.json()
    shares: Record = record(current["weighted_company_per_share"])
    metric: Record = record(shares["weighted_company_eps"])
    compared: Record = record(metric["comparison"])
    assert abs(Decimal(str(metric["value"])) - Decimal(46) / Decimal(7)) < Decimal(
        "0.00000000000000000000000001"
    )
    if prior_price_failure:
        assert compared["prior_value"] is None and current["api_status"] == "partial"
        assert compared["reason"] == "Prior portfolio market prices unavailable"
        ratio: Json
        for ratio in record(current["weighted_ratios"]).values():
            assert record(ratio)["value"] is not None
            assert record(record(ratio)["comparison"])["prior_value"] is None
    else:
        previous: Record = client.get(f"/api/accounts/{account}/financials?year=2024").json()
        prior_shares: Record = record(previous["weighted_company_per_share"])
        key: str
        for key in SHARES.values():
            assert (
                record(record(shares[key])["comparison"])["prior_value"]
                == record(prior_shares[key])["value"]
            )
        ratio_key: str
        for ratio_key in METRICS[:3]:
            current_ratio: Record = weighted(current, ratio_key)
            prior_ratio: Record = weighted(previous, ratio_key)
            ratio_comparison: Record = record(current_ratio["comparison"])
            assert ratio_comparison["prior_value"] == prior_ratio["value"]
            assert ratio_comparison["coverage"] == prior_ratio["coverage"]
            expected_change: Decimal = (
                Decimal(str(current_ratio["value"])) / Decimal(str(prior_ratio["value"])) - 1
            )
            assert abs(
                Decimal(str(ratio_comparison["percent_change"])) - expected_change
            ) < Decimal("0.00000000000000000000000001")
        assert "weighted_ratios" in record(current["comparison_inputs"])
        assert compared["prior_value"] == "8"
        assert (
            records(
                record(record(current["comparison_inputs"])["market_value_snapshot"])["holdings"]
            )[0]["ticker"]
            == "AAA"
        )
    assert ledger(client, account) == before


def zero_revenue_release(revenue: str = "0", *, proof_end: str = "2025-12-31") -> Record:
    """Pin exact-period synthetic revenue proof for the explicit margin convention."""
    zero: Record = release_row("ZERO")
    key: str
    for key in METRICS[:3]:
        record(record(zero["metrics"])[key]).update(
            value="0",
            convention="zero_revenue_margin",
            method="Explicit user convention: zero margin for verified zero revenue",
        )
    release: Record = release_payload([release_row(), zero])
    packet: str = json.dumps(
        {
            "observations": [
                {"id": "input", "value": "synthetic evidence"},
                {
                    "id": "zero-revenue",
                    "metric": "revenue",
                    "value": revenue,
                    "period_start": "2025-01-01",
                    "period_end": proof_end,
                },
            ]
        }
    )
    sha: str = hashlib.sha256(packet.encode()).hexdigest()
    receipt: str = json.dumps({"packet_sha256": sha})
    release["review_receipts"] = [
        {"content": receipt, "sha256": hashlib.sha256(receipt.encode()).hexdigest()}
    ]
    release["evidence"] = {"packets": {sha: packet}}
    row: Record
    for row in records(release["records"]):
        group: str
        for group in ("metrics", "prior_metrics"):
            metric: Record
            for metric in (record(v) for v in record(row[group]).values()):
                metric["inputs"] = [
                    {
                        "packet_sha256": sha,
                        "ids": ["zero-revenue" if metric.get("convention") else "input"],
                    }
                ]
    return release


def test_verified_zero_revenue_margins_count_as_zero_in_weighted_company_metrics() -> None:
    """The explicit convention includes company weight and carries a distinct note."""
    release: Record = zero_revenue_release()
    validate_release(release)
    result: Record = build_report(
        release,
        snapshot(("AAA", "600"), ("ZERO", "400")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    key: str
    for key in METRICS[:3]:
        metric: Record = weighted(result, key)
        assert Decimal(str(metric["value"])) == Decimal("0.24")
        assert Decimal(str(metric["coverage"])) == 1 and not metric["exclusions"]
        assert records(metric["conventions"]) == [
            {
                "issuer_key": "example:ZERO",
                "ticker": "ZERO",
                "equity_weight": "0.4",
                "convention": "zero_revenue_margin",
            }
        ]
    assert (
        Decimal(
            str(
                record(record(result["weighted_company_per_share"])["weighted_company_eps"])[
                    "value"
                ]
            )
        )
        == 2
    )


@pytest.mark.parametrize(
    "revenue,proof_end",
    [
        ("1", "2025-12-31"),
        ("-1", "2025-12-31"),
        ("0", "2024-12-31"),
    ],
)
def test_zero_revenue_convention_rejects_nonzero_or_wrong_period_proof(
    revenue: str,
    proof_end: str,
) -> None:
    """Neither losses, a positive denominator nor a different period justify the convention."""
    with pytest.raises(ValueError, match="exact-period verified zero revenue"):
        validate_release(zero_revenue_release(revenue, proof_end=proof_end))


@pytest.mark.parametrize(
    "key,value,status",
    [
        ("basic_eps", "0", "available"),
        ("gross_margin", "0.1", "available"),
        ("gross_margin", None, "unavailable"),
    ],
)
def test_zero_revenue_convention_cannot_change_other_metrics_or_missing_data(
    key: str,
    value: str | None,
    status: str,
) -> None:
    """The marker is bounded to available zero margins and never becomes an imputation rule."""
    release: Record = zero_revenue_release()
    zero: Record = records(release["records"])[1]
    record(record(zero["metrics"])[key]).update(
        convention="zero_revenue_margin",
        value=value,
        status=status,
        reason="Synthetic missing data",
    )
    with pytest.raises(ValueError, match="only to available zero margins"):
        validate_release(release)


def test_verified_diluted_eps_retains_explicit_basis() -> None:
    """A verified diluted fallback is displayed as such without inventing basic EPS."""
    row: Record = release_row()
    record(record(row["metrics"])["basic_eps"])["eps_basis"] = "diluted"
    record(record(row["prior_metrics"])["basic_eps"])["eps_basis"] = "diluted"
    release: Record = release_payload([row])
    validate_release(release)
    result: Record = build_report(
        release, snapshot(("AAA", "100")), 2025, "synthetic-account", {"USD": Decimal(1)}
    )
    company: Record = records(result["companies"])[0]
    assert record(record(company["per_share_metrics"])["basic_eps"])["eps_basis"] == "diluted"
    compared: Record = record(record(company["per_share_comparisons"])["basic_eps"])
    assert compared["status"] == "calculated"
    assert compared["percent_change"] == "1"


@pytest.mark.parametrize(
    "key,basis", [("fcf_per_basic_share", "diluted"), ("basic_eps", "unknown")]
)
def test_eps_basis_does_not_change_cash_flow_denominators(key: str, basis: str) -> None:
    """A diluted EPS fallback cannot relabel the basic FCF/share denominator."""
    row: Record = release_row()
    record(record(row["metrics"])[key])["eps_basis"] = basis
    with pytest.raises(ValueError, match="EPS basis applies only"):
        validate_release(release_payload([row]))


def test_unreported_prior_eps_preserves_issuer_reason() -> None:
    """The issuer's non-reporting reason is distinct from an uncollected prior figure."""
    row: Record = release_row()
    reason: str = "EPS not reported: issuer does not present earnings per share"
    record(record(row["prior_metrics"])["basic_eps"]).update(
        status="unavailable", value=None, reason=reason
    )
    result: Record = build_report(
        release_payload([row]),
        snapshot(("AAA", "100")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    compared: Record = record(
        record(records(result["companies"])[0]["per_share_comparisons"])["basic_eps"]
    )
    assert compared["prior_value"] is None and compared["reason"] == reason


@pytest.mark.parametrize(
    "basis", ["basic_weighted_average", "diluted_weighted_average", "period_end"]
)
def test_verified_cash_share_denominator_metadata_is_preserved(basis: str) -> None:
    """A supported cash/share denominator stays explicit without altering the source amount."""
    row: Record = release_row()
    record(record(row["metrics"])["fcf_per_basic_share"])["share_denominator_basis"] = basis
    release: Record = release_payload([row])
    validate_release(release)
    result: Record = build_report(
        release, snapshot(("AAA", "100")), 2025, "synthetic-account", {"USD": Decimal(1)}
    )
    measure: Record = record(
        record(records(result["companies"])[0]["per_share_metrics"])["fcf_per_basic_share"]
    )
    assert measure["share_denominator_basis"] == basis and measure["value"] == "2"


@pytest.mark.parametrize(
    "key,basis", [("basic_eps", "period_end"), ("fcf_per_basic_share", "unknown")]
)
def test_invalid_cash_share_denominator_basis_is_rejected(key: str, basis: str) -> None:
    """A cash/share basis cannot relabel EPS or use an unsupported denominator."""
    row: Record = release_row()
    record(record(row["metrics"])[key])["share_denominator_basis"] = basis
    with pytest.raises(ValueError, match="Share denominator basis"):
        validate_release(release_payload([row]))


def test_gross_cost_basis_note_reaches_summary_without_changing_weighted_value() -> None:
    """An admitted issuer cost definition remains visible even without exclusions."""
    row: Record = release_row()
    note: str = "excludes separately reported depreciation and amortization"
    record(record(row["metrics"])["gross_margin"])["basis_note"] = note
    release: Record = release_payload([row])
    validate_release(release)
    result: Record = build_report(
        release, snapshot(("AAA", "100")), 2025, "synthetic-account", {"USD": Decimal(1)}
    )
    gross: Record = record(record(result["weighted_ratios"])["gross_margin"])
    assert gross["value"] == "0.4" and gross["exclusions"] == []
    assert gross["basis_notes"] == [{"ticker": "AAA", "note": note}]
    assert "basis_notes" not in record(record(result["weighted_ratios"])["operating_margin"])


@pytest.mark.parametrize(
    "key,status,note",
    [
        ("operating_margin", "available", "cost basis"),
        ("gross_margin", "unavailable", "cost basis"),
        ("gross_margin", "available", " "),
    ],
)
def test_invalid_gross_cost_basis_note_is_rejected(key: str, status: str, note: str) -> None:
    """Cost qualifications apply to a supported gross-margin amount only."""
    row: Record = release_row()
    record(record(row["metrics"])[key]).update(status=status, basis_note=note)
    with pytest.raises(ValueError, match="Gross-margin basis notes"):
        validate_release(release_payload([row]))


@pytest.mark.parametrize("prior_value", ["0", "-0.1", None])
def test_prior_margin_zero_loss_and_unavailable_preserve_current_ratios(
    prior_value: str | None,
) -> None:
    """All three margin cells retain real zero/loss baselines and withhold undefined changes."""
    current: Record = build_report(
        release_payload(), snapshot(("AAA", "100")), 2025, "synthetic-account", {"USD": Decimal(1)}
    )
    old: Record = release_row("SOLD")
    old["year"] = 2024
    key: str
    for key in METRICS[:3]:
        record(record(old["metrics"])[key]).update(
            value=prior_value,
            status="available" if prior_value is not None else "unavailable",
            reason="Synthetic unavailable",
        )
    previous: Record = build_report(
        release_payload([old]),
        snapshot(("SOLD", "100")),
        2024,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    add_portfolio_comparisons(current, previous, 2025)
    for key in METRICS[:3]:
        metric: Record = weighted(current, key)
        compared: Record = record(metric["comparison"])
        assert metric["value"] == "0.4" and compared["prior_value"] == prior_value
        assert compared["status"] == (
            "not_meaningful" if prior_value is not None else "unavailable"
        )
        assert compared["percent_change"] is None


def test_prior_margin_notes_and_exclusions_retain_previous_portfolio_identities() -> None:
    """Prior cost-basis and coverage disclosures refer to sold holdings, not current companies."""
    current: Record = build_report(
        release_payload(), snapshot(("AAA", "100")), 2025, "synthetic-account", {"USD": Decimal(1)}
    )
    old: Record = release_row("SOLD")
    old["year"] = 2024
    record(record(old["metrics"])["gross_margin"])["basis_note"] = "Synthetic cost basis"
    previous: Record = build_report(
        release_payload([old]),
        snapshot(("SOLD", "80"), ("UNKNOWN", "20")),
        2024,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    add_portfolio_comparisons(current, previous, 2025)
    compared: Record = record(weighted(current)["comparison"])
    assert compared["coverage"] == "0.8"
    assert compared["basis_notes"] == [{"ticker": "SOLD", "note": "Synthetic cost basis"}]
    assert records(compared["exclusions"])[0]["ticker"] == "UNKNOWN"


def test_missing_current_margin_keeps_available_actual_prior_value() -> None:
    """Current missing data must not erase a real previous portfolio margin."""
    row: Record = release_row()
    key: str
    for key in METRICS[:3]:
        record(record(row["metrics"])[key]).update(
            status="unavailable", value=None, reason="Synthetic missing current margin"
        )
    current: Record = build_report(
        release_payload([row]),
        snapshot(("AAA", "100")),
        2025,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    prior_row: Record = release_row("SOLD")
    prior_row["year"] = 2024
    previous: Record = build_report(
        release_payload([prior_row]),
        snapshot(("SOLD", "100")),
        2024,
        "synthetic-account",
        {"USD": Decimal(1)},
    )
    add_portfolio_comparisons(current, previous, 2025)
    for key in METRICS[:3]:
        compared: Record = record(weighted(current, key)["comparison"])
        assert compared["prior_value"] == "0.4" and compared["status"] == "unavailable"
        assert compared["percent_change"] is None
        assert compared["reason"] == "Current or prior financial data unavailable"
