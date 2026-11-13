"""Focused Main-only portfolio sync and Google GViz regression tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
import requests
from urllib3.exceptions import ReadTimeoutError

from harness.portfolio_state import (
    _google_sheets_gviz_url,
    _rows_from_gviz_response,
    load_json,
    load_tabular_rows,
    normalize_holdings,
    normalize_transactions,
    sync_portfolio,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "morning_brief"
RUN_DATE = date(2026, 4, 8)


def _fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_exact_seven_column_csv_is_main_only_precise_and_stably_sorted() -> None:
    rows = load_tabular_rows(str(FIXTURE_DIR / "transactions_main.csv"))
    transactions = normalize_transactions(rows)

    assert [item["security_id"] for item in transactions] == ["ALFA", "BETA", "GONE"]
    assert [item["trade_date"] for item in transactions] == ["2026-04-08", "2026-04-08", "2026-03-31"]
    assert transactions[0] == {
        "security_id": "ALFA",
        "ticker": "ALFA",
        "company_name": "",
        "trade_date": "2026-04-08",
        "action": "buy",
        "quantity": 0.123456789,
        "price": 100.1234,
        "portfolio": "Main",
        "notes": "",
        "total_usd": 12.345678,
    }
    assert normalize_transactions(transactions) == transactions


def test_legacy_transactions_default_to_main_but_present_blank_labels_do_not() -> None:
    legacy = normalize_transactions(
        [{"date": "04/08/26", "action": "Buy", "symbol": "ALFA", "shares": "1", "price": "$2.50"}]
    )
    assert legacy[0]["portfolio"] == "Main"

    labeled = normalize_transactions(
        [
            {"date": "04/08/26", "type": "Buy", "symbol": "ALFA", "shares": 1, "price_usd": 2.5, "portfolio": ""},
            {"date": "04/08/26", "type": "Buy", "symbol": "BETA", "shares": 1, "price_usd": 3, "portfolio": "Satellite"},
        ]
    )
    assert labeled == []


def test_legacy_transactions_remain_permissive_without_inferring_usd_cash() -> None:
    transactions = normalize_transactions([
        {
            "security_id": "PRIVATE-EXAMPLE",
            "ticker": "",
            "company_name": "Private Example",
            "action": "dividend",
            "quantity": "0",
            "amount": "$10.00",
        }
    ])
    assert transactions == [{
        "security_id": "PRIVATE-EXAMPLE",
        "ticker": "",
        "company_name": "Private Example",
        "trade_date": "",
        "action": "dividend",
        "quantity": 0,
        "price": None,
        "portfolio": "Main",
        "notes": "",
    }]
    assert normalize_transactions(transactions) == transactions


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("shares", "", "shares must be numeric"),
        ("shares", "0", "shares must be greater than zero"),
        ("shares", "NaN", "shares must be numeric"),
        ("price_usd", "-1", "price must be greater than zero"),
        ("total_usd", "Infinity", "total must be numeric"),
        ("date", "", "date is required"),
        ("date", "04/31/2026", "invalid date"),
        ("type", "Interest", "action must be buy, sell, dividend, dividend_tax or adr_fee"),
    ],
)
def test_invalid_main_trade_fields_are_rejected(field: str, value: str, message: str) -> None:
    row = {
        "date": "04/08/2026",
        "type": "Buy",
        "symbol": "ALFA",
        "shares": "1",
        "price_usd": "$2.50",
        "total_usd": "$2.50",
        "portfolio": "Main",
    }
    row[field] = value
    with pytest.raises(ValueError, match=message):
        normalize_transactions([row])


def test_modern_source_requires_usd_price_field_and_symbol() -> None:
    row = {
        "date": "04/08/2026",
        "type": "Buy",
        "symbol": "ALFA",
        "shares": "1",
        "total_usd": "$2.50",
        "portfolio": "Main",
        "price": "$2.50",
    }
    with pytest.raises(ValueError, match="price must be numeric"):
        normalize_transactions([row])

    row["price_usd"] = row.pop("price")
    row["company_name"] = "Alpha Example"
    row["symbol"] = ""
    with pytest.raises(ValueError, match="symbol is required"):
        normalize_transactions([row])

    row["symbol"] = "ALFA"
    row.pop("portfolio")
    with pytest.raises(ValueError, match="portfolio is required"):
        normalize_transactions([row])


def test_gviz_uses_underlying_values_dates_and_percentage_point_weights() -> None:
    holdings_rows = _rows_from_gviz_response(_fixture_text("portfolio_main.gviz"))
    holdings = normalize_holdings(holdings_rows)
    assert [item["ticker"] for item in holdings] == ["ALFA", "BETA"]
    assert holdings[0]["shares"] == 12.3456789
    assert holdings[0]["weight"] == 55
    assert all(item["portfolio"] == "Main" for item in holdings)

    transaction_rows = _rows_from_gviz_response(_fixture_text("transactions_main.gviz"))
    transactions = normalize_transactions(transaction_rows)
    assert [item["security_id"] for item in transactions] == ["ALFA", "BETA", "GONE"]
    assert transactions[0]["quantity"] == 0.123456789
    assert transactions[0]["total_usd"] == 12.345678
    assert transactions[1]["quantity"] == 2.0000001
    assert transactions[2]["trade_date"] == "2026-03-31"


def test_weight_convention_preserves_generic_json_and_normalizes_csv_percent() -> None:
    assert normalize_holdings([{"ticker": "ALFA", "weight": 0.55}])[0]["weight"] == 0.55
    assert normalize_holdings([{"ticker": "ALFA", "weight": "55%"}])[0]["weight"] == 55


def test_google_export_url_upgrade_requires_and_preserves_selection() -> None:
    source = (
        "https://docs.google.com/spreadsheets/d/example-sheet-id/export"
        "?format=csv&gid=12345&range=A1%3AG20&tq=select+A%2CB&headers=1"
    )
    upgraded = _google_sheets_gviz_url(source)
    parsed = urlparse(upgraded)
    query = parse_qs(parsed.query)
    assert parsed.path == "/spreadsheets/d/example-sheet-id/gviz/tq"
    assert query == {
        "gid": ["12345"],
        "range": ["A1:G20"],
        "tq": ["select A,B"],
        "headers": ["1"],
        "tqx": ["out:json"],
    }

    with pytest.raises(ValueError, match="recognized Google Sheets"):
        _google_sheets_gviz_url(
            "http://docs.google.com/spreadsheets/d/example-sheet-id/export?format=csv&gid=12345"
        )
    with pytest.raises(ValueError, match="explicit numeric query gid"):
        _google_sheets_gviz_url(
            "https://docs.google.com/spreadsheets/d/example-sheet-id/export?format=csv"
        )


def test_google_url_loader_fetches_gviz_not_rounded_csv() -> None:
    source = "https://docs.google.com/spreadsheets/d/example-sheet-id/export?format=csv&gid=12345"
    with patch(
        "harness.portfolio_state.read_text_source",
        return_value=(_fixture_text("transactions_main.gviz"), ".json"),
    ) as read_source:
        rows = load_tabular_rows(source)
    requested_url = read_source.call_args.args[0]
    assert "/gviz/tq" in requested_url
    assert "gid=12345" in requested_url
    assert rows[0]["shares"] == 0.123456789


def _http_response(status: int, body: str = "") -> requests.Response:
    """Build a synthetic response from the Sheets service."""
    response = requests.Response()
    response.status_code = status
    response.url = "https://docs.google.com/spreadsheets/d/example/gviz/tq"
    response._content = body.encode("utf-8")
    return response


@pytest.mark.parametrize("failure", [_http_response(429), _http_response(500), _http_response(502), requests.Timeout("timed out")])
def test_sync_retries_transient_sheet_failure_and_imports_exact_values(tmp_path: Path, failure: object) -> None:
    with patch("harness.portfolio_state._http_session") as session, patch("harness.portfolio_state.time.sleep"):
        session.return_value.get.side_effect = [failure, _http_response(200, _fixture_text("portfolio_main.gviz"))]
        sync_portfolio(tmp_path, as_of=RUN_DATE, sheet_id="example", holdings_gid="12345")

    holdings = load_json(tmp_path / "data" / "01-portfolio" / "current" / "holdings.json", default=[])
    assert [(row["ticker"], row["shares"], row["weight"]) for row in holdings] == [
        ("ALFA", 12.3456789, 55), ("BETA", 8.7654321, 45),
    ]


@pytest.mark.parametrize("timeouts", [1, 2])
def test_sheet_body_timeout_retries_at_most_once(timeouts: int) -> None:
    class TimedOutBody:
        """Simulate a timeout while Requests consumes a response body."""

        def stream(self, *args: object, **kwargs: object) -> object:
            """Raise the underlying urllib3 read timeout."""
            raise ReadTimeoutError(None, "/gviz/tq", "response body timed out")

    class SheetAdapter(requests.adapters.BaseAdapter):
        """Return real Requests responses with controlled body reads."""

        def __init__(self) -> None:
            """Start the request count."""
            self.attempts = 0

        def send(self, request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
            """Return a timed-out or successful response."""
            self.attempts += 1
            response = requests.Response()
            response.status_code = 200
            response.url = request.url
            response.request = request
            if self.attempts <= timeouts:
                response.raw = TimedOutBody()
            else:
                response._content = _fixture_text("portfolio_main.gviz").encode("utf-8")
            return response

        def close(self) -> None:
            """Close this adapter, which owns no resources."""

    adapter = SheetAdapter()
    session = requests.Session()
    session.mount("https://docs.google.com/", adapter)
    source = "https://docs.google.com/spreadsheets/d/example/export?format=csv&gid=12345"
    with patch("harness.portfolio_state._http_session", return_value=session), patch("harness.portfolio_state.time.sleep"):
        if timeouts == 1:
            rows = load_tabular_rows(source)
            assert rows[0]["shares"] == 12.3456789
        else:
            with pytest.raises(requests.ConnectionError):
                load_tabular_rows(source)
    assert adapter.attempts == 2


def test_sheet_unrelated_connection_error_is_not_retried() -> None:
    source = "https://docs.google.com/spreadsheets/d/example/export?format=csv&gid=12345"
    with patch("harness.portfolio_state._http_session") as session, patch("harness.portfolio_state.time.sleep"):
        session.return_value.get.side_effect = requests.ConnectionError("connection failed")
        with pytest.raises(requests.ConnectionError):
            load_tabular_rows(source)
    assert session.return_value.get.call_count == 1


def test_sheet_rate_limit_honors_bounded_retry_after() -> None:
    response = _http_response(429)
    response.headers["Retry-After"] = "20"
    source = "https://docs.google.com/spreadsheets/d/example/export?format=csv&gid=12345"
    with patch("harness.portfolio_state._http_session") as session, patch("harness.portfolio_state.time.sleep") as sleep:
        session.return_value.get.side_effect = [response, _http_response(200, _fixture_text("portfolio_main.gviz"))]
        rows = load_tabular_rows(source)
    assert rows[0]["shares"] == 12.3456789
    sleep.assert_called_once_with(10)


@pytest.mark.parametrize(
    ("failures", "error"),
    [
        ([_http_response(503), _http_response(502)], requests.HTTPError),
        ([requests.Timeout("first"), requests.Timeout("second")], requests.Timeout),
        ([_http_response(404)], requests.HTTPError),
    ],
)
def test_sheet_fetch_failure_preserves_current_portfolio(
    tmp_path: Path, failures: list[object], error: type[Exception],
) -> None:
    sync_portfolio(
        tmp_path, as_of=RUN_DATE,
        holdings_source=str(FIXTURE_DIR / "holdings.csv"),
        transactions_source=str(FIXTURE_DIR / "transactions_main.csv"),
    )
    portfolio = tmp_path / "data" / "01-portfolio"
    before = {path: path.read_bytes() for path in portfolio.rglob("*") if path.is_file()}
    with patch("harness.portfolio_state._http_session") as session, patch("harness.portfolio_state.time.sleep"):
        session.return_value.get.side_effect = [_http_response(200, _fixture_text("portfolio_main.gviz")), *failures]
        with pytest.raises(error):
            sync_portfolio(
                tmp_path, as_of=RUN_DATE, sheet_id="example", holdings_gid="12345", transactions_gid="67890",
            )
    assert {path: path.read_bytes() for path in portfolio.rglob("*") if path.is_file()} == before
    assert session.return_value.get.call_count == 1 + len(failures)


def test_gviz_rejects_non_ok_malformed_and_executable_wrappers() -> None:
    with pytest.raises(ValueError, match="query failed.*not found"):
        _rows_from_gviz_response(
            '{"status":"error","errors":[{"reason":"not_found","message":"sheet not found"}]}'
        )
    with pytest.raises(ValueError, match="no table"):
        _rows_from_gviz_response('{"status":"ok"}')
    with pytest.raises(ValueError, match="invalid Google Visualization"):
        _rows_from_gviz_response(
            'alert("not executed"); google.visualization.Query.setResponse({"status":"ok","table":{"cols":[],"rows":[]}});'
        )


def test_standard_google_comment_prefix_preserves_underlying_values() -> None:
    text = _fixture_text("portfolio_main.gviz").removeprefix("/*O_o*/").lstrip()
    assert _rows_from_gviz_response("/*O_o*/\n" + text) == _rows_from_gviz_response(text)


@pytest.mark.parametrize("missing", [True, False])
def test_modern_usd_price_requires_reported_cash_total(missing: bool) -> None:
    row = {"date": "04/08/26", "type": "Buy", "symbol": "ALFA", "shares": 1,
           "price_usd": 2.5, "portfolio": "Main"}
    if not missing:
        row["total_usd"] = ""
    with pytest.raises(ValueError, match="total must be numeric"):
        normalize_transactions([row])


def test_reported_usd_cash_cannot_be_relabeled_as_another_currency() -> None:
    row = {"date": "04/08/26", "type": "Buy", "symbol": "ALFA", "shares": 1,
           "price_usd": 2.5, "total_usd": 2.5, "portfolio": "Main", "currency": "EUR"}
    with pytest.raises(ValueError, match="USD total conflicts with currency"):
        normalize_transactions([row])


def test_canonical_company_identity_and_names_survive_resync() -> None:
    canonical = normalize_transactions([
        {"ticker": "ALFA", "company_name": "Alpha Example", "date": "04/08/26",
         "action": "buy", "quantity": 1, "price": 2},
        {"ticker": "", "security_id": "PRIVATE-EXAMPLE", "company_name": "Private Example",
         "trade_date": "2026-04-08", "action": "buy", "quantity": 1, "price": 3},
    ])
    assert canonical[0]["company_name"] == "Alpha Example"
    assert canonical[1]["ticker"] == ""
    assert canonical[1]["security_id"] == "PRIVATE-EXAMPLE"
    assert normalize_transactions(canonical) == canonical


def test_sheet_id_sync_can_update_either_side_and_retain_local_state(tmp_path: Path) -> None:
    sync_portfolio(
        tmp_path,
        as_of=RUN_DATE,
        holdings_source=str(FIXTURE_DIR / "holdings.csv"),
        transactions_source=str(FIXTURE_DIR / "transactions_main.csv"),
    )
    root = tmp_path / "data" / "01-portfolio"
    holdings_path = root / "current" / "holdings.json"
    transactions_path = root / "transactions.json"

    holdings_rows = load_tabular_rows(str(FIXTURE_DIR / "holdings_gsheet.csv"))
    transactions_before = transactions_path.read_bytes()
    with patch("harness.portfolio_state.load_tabular_rows", return_value=holdings_rows) as loader:
        sync_portfolio(tmp_path, as_of=RUN_DATE, sheet_id="example-sheet-id", holdings_gid="12345")
    assert loader.call_args.args[0].endswith("?format=csv&gid=12345")
    assert transactions_path.read_bytes() == transactions_before

    transaction_rows = load_tabular_rows(str(FIXTURE_DIR / "transactions_main.csv"))
    holdings_before = holdings_path.read_bytes()
    with patch("harness.portfolio_state.load_tabular_rows", return_value=transaction_rows) as loader:
        sync_portfolio(tmp_path, as_of=RUN_DATE, sheet_id="example-sheet-id", transactions_gid="67890")
    assert loader.call_args.args[0].endswith("?format=csv&gid=67890")
    assert holdings_path.read_bytes() == holdings_before


def test_sync_stages_both_sources_and_does_not_replace_good_state_on_failure(tmp_path: Path) -> None:
    sync_portfolio(
        tmp_path,
        as_of=RUN_DATE,
        holdings_source=str(FIXTURE_DIR / "holdings.csv"),
        transactions_source=str(FIXTURE_DIR / "transactions_main.csv"),
    )
    holdings_path = tmp_path / "data" / "01-portfolio" / "current" / "holdings.json"
    transactions_path = tmp_path / "data" / "01-portfolio" / "transactions.json"
    before = (holdings_path.read_bytes(), transactions_path.read_bytes())

    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        "Date,Type,Symbol,Shares,Price (USD),Total (USD),Portfolio\n"
        "04/09/2026,Buy,ALFA,,10,10,Main\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="shares must be numeric"):
        sync_portfolio(
            tmp_path,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
            transactions_source=str(malformed),
        )
    assert (holdings_path.read_bytes(), transactions_path.read_bytes()) == before

    with pytest.raises(FileNotFoundError):
        sync_portfolio(
            tmp_path,
            as_of=RUN_DATE,
            holdings_source=str(tmp_path / "missing.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions_main.csv"),
        )
    assert (holdings_path.read_bytes(), transactions_path.read_bytes()) == before

    sync_log = tmp_path / "data" / "01-portfolio" / "history" / "sync-log.jsonl"
    sync_log.write_text("{malformed}\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        sync_portfolio(
            tmp_path,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions_main.csv"),
        )
    assert (holdings_path.read_bytes(), transactions_path.read_bytes()) == before


def test_watchlist_portfolio_labels_cannot_expand_daily_news_universe(tmp_path: Path) -> None:
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text(
        "Ticker,Company,Portfolio\n"
        "GAMM,Gamma Example Corp,Main\n"
        "SATL,Satellite Example Corp,Satellite\n"
        "BLNK,Blank Example Corp,\n",
        encoding="utf-8",
    )
    sync_portfolio(
        tmp_path,
        as_of=RUN_DATE,
        holdings_source=str(FIXTURE_DIR / "holdings.csv"),
        watchlist_source=str(watchlist),
    )
    universe = load_json(tmp_path / "data" / "01-portfolio" / "current" / "universe.json", default=[])
    security_ids = {item["security_id"] for item in universe}
    assert security_ids == {"NVDA", "MSFT", "GAMM"}
    assert "SATL" not in security_ids
    assert "BLNK" not in security_ids


def test_zero_valid_main_holdings_fails_closed_without_replacing_state(tmp_path: Path) -> None:
    sync_portfolio(tmp_path, as_of=RUN_DATE, holdings_source=str(FIXTURE_DIR / "holdings.csv"))
    holdings_path = tmp_path / "data" / "01-portfolio" / "current" / "holdings.json"
    before = load_json(holdings_path, default=[])
    satellite = tmp_path / "satellite.csv"
    satellite.write_text("Ticker,# Shares,Portfolio\nSATL,2,Satellite\nBLNK,1,\n", encoding="utf-8")

    with pytest.raises(ValueError, match="zero valid Main"):
        sync_portfolio(tmp_path, as_of=RUN_DATE, holdings_source=str(satellite))
    assert load_json(holdings_path, default=[]) == before
