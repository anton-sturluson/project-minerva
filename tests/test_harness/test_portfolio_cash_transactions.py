"""Synthetic cash-event coverage for the modern seven-column transaction ledger."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import TextIO

import pytest
import yaml

from harness.portfolio_state import (
    NON_SECURITY_TICKERS,
    PortfolioPaths,
    _rows_from_gviz_response,
    load_tabular_rows,
    normalize_transactions,
    portfolio_paths,
    sync_portfolio,
)


type Cell = str | int | float | None

HEADERS: dict[str, str] = {
    "date": "Date",
    "type": "Type",
    "symbol": "Symbol",
    "shares": "Shares",
    "price_usd": "Price (USD)",
    "total_usd": "Total (USD)",
    "portfolio": "Portfolio",
}
CASH_CASES: list[tuple[str, str, float]] = [
    ("Dividend", "dividend", 12.345678),
    ("Dividend Tax", "dividend_tax", -1.234567),
    ("ADR Fee", "adr_fee", -0.123456),
]


def _cash_row(kind: str = "Dividend", total: Cell = 12.345678) -> dict[str, Cell]:
    """Return one synthetic seven-column row with loader-normalized headers."""
    return {
        "date": "04/08/2026",
        "type": kind,
        "symbol": "ALFA",
        "shares": "",
        "price_usd": "",
        "total_usd": total,
        "portfolio": "Main",
    }


@pytest.mark.parametrize(("kind", "action", "total"), CASH_CASES)
@pytest.mark.parametrize("shape", ["normalized", "raw", "canonical"])
def test_cash_shapes_and_canonical_round_trip(
    kind: str, action: str, total: float, shape: str,
) -> None:
    """All header shapes yield the same typed, signed, share-free record."""
    row: dict[str, Cell] = _cash_row(kind, total)
    expected: list[dict[str, Cell]] = [{
        "security_id": "ALFA",
        "ticker": "ALFA",
        "company_name": "",
        "trade_date": "2026-04-08",
        "action": action,
        "quantity": None,
        "price": None,
        "portfolio": "Main",
        "notes": "",
        "total_usd": total,
    }]
    if shape == "raw":
        row = {HEADERS[key]: value for key, value in row.items()}
    elif shape == "canonical":
        row = expected[0].copy()
    result: list[dict[str, Cell]] = normalize_transactions([row])
    assert result == expected
    assert normalize_transactions(result) == result
    assert normalize_transactions(json.loads(json.dumps(result, allow_nan=False))) == result


@pytest.mark.parametrize("suffix", [".csv", ".json", ".yaml"])
def test_local_loader_preserves_cash_records(tmp_path: Path, suffix: str) -> None:
    """Local source files use only synthetic rows and round-trip without loss."""
    rows: list[dict[str, Cell]] = [
        {HEADERS[key]: value for key, value in _cash_row(kind, total).items()}
        for kind, _, total in CASH_CASES
    ]
    source: Path = tmp_path / f"cash{suffix}"
    if suffix == ".csv":
        handle: TextIO
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer: csv.DictWriter = csv.DictWriter(handle, fieldnames=list(HEADERS.values()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        source.write_text(
            json.dumps(rows) if suffix == ".json" else yaml.safe_dump(rows), encoding="utf-8",
        )
    result: list[dict[str, Cell]] = normalize_transactions(load_tabular_rows(str(source)))
    assert [row["action"] for row in result] == [action for _, action, _ in CASH_CASES]
    assert [row["total_usd"] for row in result] == [total for _, _, total in CASH_CASES]
    assert all(row["quantity"] is None and row["price"] is None for row in result)


def test_gviz_null_cash_cells_use_unrounded_total() -> None:
    """Null share/price cells are valid and formatted values do not replace totals."""
    payload: str = json.dumps({
        "status": "ok",
        "table": {
            "cols": [{"label": label} for label in HEADERS.values()],
            "rows": [{"c": [
                {"v": "Date(2026,3,8)"}, {"v": "Dividend"}, {"v": "ALFA"},
                None, {"v": None}, {"v": 12.345678, "f": "$12.35"}, {"v": "Main"},
            ]}],
        },
    })
    assert normalize_transactions(_rows_from_gviz_response(payload)) == normalize_transactions([
        _cash_row(),
    ])


@pytest.mark.parametrize(("kind", "action", "total"), CASH_CASES)
@pytest.mark.parametrize("shape", ["normalized", "canonical"])
@pytest.mark.parametrize("bad_total", [
    None, "", " ", "NaN", "sNaN", "inf", "-Infinity",
    float("nan"), float("inf"), float("-inf"), "9" * 309 + ".5",
    True, "EUR 2", "€2", "2%", "not money",
])
def test_cash_requires_finite_numeric_usd(
    kind: str, action: str, total: float, bad_total: Cell, shape: str,
) -> None:
    """Missing, nonfinite, non-USD and non-monetary totals fail closed."""
    row: dict[str, Cell] = _cash_row(kind, total)
    if shape == "canonical":
        row = normalize_transactions([row])[0]
    row["total_usd"] = bad_total
    with pytest.raises(ValueError, match="total must be numeric"):
        normalize_transactions([row])


@pytest.mark.parametrize(("kind", "action", "total"), CASH_CASES)
@pytest.mark.parametrize("bad_sign", ["zero", "opposite", "underflow"])
def test_cash_requires_nonzero_action_sign(kind: str, action: str, total: float, bad_sign: str) -> None:
    """Taxes and fees cannot become positive income, including signed zero."""
    value: Cell = 0 if bad_sign == "zero" else -total
    if bad_sign == "underflow":
        value = "1e-999" if total > 0 else "-1e-999"
    with pytest.raises(ValueError, match="total must be (greater|less) than zero"):
        normalize_transactions([_cash_row(kind, value)])


@pytest.mark.parametrize("shape", ["normalized", "canonical"])
@pytest.mark.parametrize("field", ["shares", "quantity", "price_usd", "price"])
@pytest.mark.parametrize("value", [0, "0", 1, "NaN", float("inf"), False, "null"])
def test_cash_rejects_all_share_and_price_aliases(shape: str, field: str, value: Cell) -> None:
    """Even zero or invalid data in any trade field must not be ignored."""
    row: dict[str, Cell] = _cash_row()
    if shape == "canonical":
        row = normalize_transactions([row])[0]
    row[field] = value
    with pytest.raises(ValueError, match="cash events require blank shares and price"):
        normalize_transactions([row])


@pytest.mark.parametrize("blank", [None, "", " \t "])
def test_cash_accepts_only_blank_trade_cells(blank: Cell) -> None:
    """Blank cells become explicit nulls, never zero-share trades."""
    row: dict[str, Cell] = _cash_row()
    row.update(shares=blank, price_usd=blank)
    result: dict[str, Cell] = normalize_transactions([row])[0]
    assert result["quantity"] is None
    assert result["price"] is None


@pytest.mark.parametrize(("field", "value", "message"), [
    ("date", None, "date is required"),
    ("date", "", "date is required"),
    ("date", "2026-02-30", "invalid date"),
    ("date", "tomorrow", "invalid date"),
    ("symbol", "", "symbol is required"),
    ("symbol", None, "symbol is required"),
    ("symbol", "NaN", "symbol is required"),
    ("symbol", "ALFA BETA", "invalid symbol"),
    ("symbol", "???", "invalid symbol"),
    ("type", "", "action must be"),
    ("type", "Deposit", "action must be"),
    ("type", "Interest", "action must be"),
    ("type", "Dividends", "action must be"),
    ("currency", "EUR", "USD total conflicts with currency"),
])
def test_cash_rejects_invalid_identity_date_type_and_currency(field: str, value: Cell, message: str) -> None:
    """Cash events require the same dated Main USD identity as ledger trades."""
    row: dict[str, Cell] = _cash_row()
    row[field] = value
    with pytest.raises(ValueError, match=message):
        normalize_transactions([row])


@pytest.mark.parametrize(("field", "message"), [
    ("date", "date is required"),
    ("symbol", "symbol is required"),
    ("type", "action must be"),
    ("total_usd", "total must be numeric"),
    ("portfolio", "portfolio is required"),
])
def test_cash_rejects_missing_required_cells(field: str, message: str) -> None:
    """Missing keys must not fall back to inferred dates, amounts or groups."""
    row: dict[str, Cell] = _cash_row()
    del row[field]
    with pytest.raises(ValueError, match=message):
        normalize_transactions([row])


@pytest.mark.parametrize(("kind", "total", "expected"), [
    (" dividend ", "USD 1,234.5678", 1234.5678),
    ("DIVIDEND TAX", "($1.25)", -1.25),
    ("adr_fee", "US$ -0.25", -0.25),
])
def test_cash_accepts_formatted_usd_and_normalizes_labels(kind: str, total: str, expected: float) -> None:
    """Supported display labels and dollar formats retain their amount and sign."""
    row: dict[str, Cell] = _cash_row(kind, total)
    row.update(symbol=" alfa ", portfolio=" main ", currency=" usd ")
    result: dict[str, Cell] = normalize_transactions([row])[0]
    assert result["total_usd"] == expected
    assert result["ticker"] == "ALFA"
    assert result["portfolio"] == "Main"
    assert normalize_transactions([result]) == [result]


def test_cash_group_filter_and_section_exclusions_precede_validation() -> None:
    """Other groups, blanks and section labels stay excluded, even when malformed."""
    rows: list[dict[str, Cell]] = [_cash_row()]
    label: Cell
    for label in ("Satellite", "Other", "", None):
        rows.append({**_cash_row("Unknown", "NaN"), "portfolio": label})
    rows.append({key: value for key, value in _cash_row().items() if key != "portfolio"})
    rows.extend({**_cash_row(), "symbol": label} for label in NON_SECURITY_TICKERS)
    rows.append(dict.fromkeys(HEADERS))
    assert normalize_transactions(rows) == normalize_transactions([_cash_row()])
    assert normalize_transactions([
        {HEADERS[key]: value for key, value in row.items()} for row in rows
    ]) == normalize_transactions([_cash_row()])


def test_cash_events_and_drip_buy_preserve_count_order_and_holdings(tmp_path: Path) -> None:
    """Synthetic local sync keeps every event without deriving holdings or deposits."""
    holdings: Path = tmp_path / "holdings.csv"
    holdings.write_text("Ticker,# Shares,Total Cost,Portfolio\nALFA,10.5,210,Main\n", encoding="utf-8")
    source: Path = tmp_path / "transactions.json"
    rows: list[dict[str, Cell]] = [
        {**_cash_row("Buy", 200), "date": "04/01/2026", "shares": 10, "price_usd": 20},
        _cash_row("Dividend", 12.5),
        _cash_row("Dividend Tax", -2),
        _cash_row("ADR Fee", -0.5),
        {**_cash_row("Buy", 10), "shares": 0.5, "price_usd": 20},
        _cash_row("Dividend", 12.5),
        {**_cash_row("Sell", 20), "date": "04/09/2026", "shares": 1, "price_usd": 20},
    ]
    sync_portfolio(tmp_path, as_of=date(2026, 4, 9), holdings_source=str(holdings))
    paths: PortfolioPaths = portfolio_paths(tmp_path)
    before: bytes = paths.holdings.read_bytes()
    source.write_text(json.dumps(rows), encoding="utf-8")
    transaction_count: int = sync_portfolio(
        tmp_path, as_of=date(2026, 4, 9), transactions_source=str(source),
    )["transactions_count"]
    result: list[dict[str, Cell]] = json.loads(paths.transactions.read_text(encoding="utf-8"))
    assert transaction_count == len(rows) == len(result)
    assert [row["action"] for row in result] == [
        "sell", "dividend", "dividend_tax", "adr_fee", "buy", "dividend", "buy",
    ]
    assert result[4]["quantity"] == 0.5
    assert result[4]["price"] == 20
    assert result[4]["total_usd"] == 10
    assert result[1] == result[5]
    assert paths.holdings.read_bytes() == before
    assert "dividend | 12.5 USD" in paths.rendered.read_text(encoding="utf-8")
    assert "adr_fee | -0.5 USD" in paths.rendered.read_text(encoding="utf-8")
    before_transactions: bytes = paths.transactions.read_bytes()
    sync_portfolio(tmp_path, as_of=date(2026, 4, 9))
    assert paths.transactions.read_bytes() == before_transactions
    assert paths.holdings.read_bytes() == before
    assert json.loads(paths.sync_log.read_text(encoding="utf-8").splitlines()[-1])[
        "counts"
    ]["transactions"] == len(rows)


def test_invalid_cash_total_does_not_replace_synthetic_state(tmp_path: Path) -> None:
    """A validation failure leaves previously accepted local test state unchanged."""
    holdings: Path = tmp_path / "holdings.csv"
    holdings.write_text("Ticker,# Shares,Portfolio\nALFA,10,Main\n", encoding="utf-8")
    source: Path = tmp_path / "transactions.json"
    source.write_text(json.dumps([_cash_row()]), encoding="utf-8")
    sync_portfolio(
        tmp_path, as_of=date(2026, 4, 8), holdings_source=str(holdings), transactions_source=str(source),
    )
    paths: PortfolioPaths = portfolio_paths(tmp_path)
    before: bytes = paths.transactions.read_bytes()
    before_log: bytes = paths.sync_log.read_bytes()
    source.write_text(json.dumps([_cash_row("Dividend Tax", 2)]), encoding="utf-8")
    with pytest.raises(ValueError, match="total must be less than zero"):
        sync_portfolio(tmp_path, as_of=date(2026, 4, 9), transactions_source=str(source))
    assert paths.transactions.read_bytes() == before
    assert paths.sync_log.read_bytes() == before_log
