import json
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investor_platform.import_transactions import apply_import, reconstruct
from investor_platform.ledger import entries_for
from investor_platform.models import Account, LedgerEntry, Security

CSV = b"""Date,Type,Symbol,Shares,Cost,Total Cost,Price,Market Value,Net
7/22/24,Sell,AAA,5,$10,$50,$12,$60,$10
7/21/24,Buy,AAA,2,$10,$21,,,
7/23/24,Buy,BBB,4,$20,$80,,,
7/23/24,Buy,FOREIGN,1,$50,$50,,,
"""
LISTINGS = {
    "AAA": {"exchange": "NASDAQ", "currency": "USD"},
    "BBB": {"exchange": "NYSE", "currency": "USD"},
}


def test_reconstruction_orders_dates_retains_evidence_and_marks_assumptions():
    entries, report = reconstruct(CSV, LISTINGS)
    assert report["imported_trades"] == 3
    assert {k: Decimal(v) for k, v in report["opening_positions"].items()} == {
        "AAA · NASDAQ": Decimal(3)
    }
    assert Decimal(report["opening_cash"]) == Decimal("41")
    assert {k: Decimal(v) for k, v in report["holdings"].items()} == {"BBB · NYSE": Decimal(4)}
    assert report["price_discrepancies"] == [3]
    assert report["skipped"][0]["row"] == 5
    assert len(report["source_rows"]) == 4
    assert entries[1].cost_basis is None
    assert entries[2].price == Decimal("10.5")
    again, _ = reconstruct(CSV, LISTINGS)
    assert [e.request_key for e in entries] == [e.request_key for e in again]


def test_import_is_atomic_idempotent_and_preserves_existing_account(database, db_client):
    entries, report = reconstruct(CSV, LISTINGS)
    # Force a replay failure after inserts: the whole account must roll back.
    entries[0].amount = Decimal(0)
    with pytest.raises(HTTPException):
        apply_import(database, "Synthetic import", entries, report)
    with Session(database) as session:
        for model in (Account, LedgerEntry, Security):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    entries, report = reconstruct(CSV, LISTINGS)
    account_id, created = apply_import(database, "Synthetic import", entries, report)
    assert created
    assert apply_import(database, "Synthetic import", entries, report) == (account_id, False)
    with Session(database) as session:
        records = entries_for(session, account_id)
        assert len(records) == len(entries)
        assert (
            session.get(Account, account_id).reconstruction["source_rows"] == report["source_rows"]
        )
    view = db_client.get("/api/account").json()
    assert view["reconstruction"]["imported_trades"] == 3
    assert "source_rows" not in view["reconstruction"]
    with pytest.raises(ValueError, match="already has an account"):
        changed, changed_report = reconstruct(CSV.replace(b"$80", b"$81"), LISTINGS)
        apply_import(database, "Changed import", changed, changed_report)


def test_bad_rows_are_reported_without_dropping_valid_rows():
    bad = CSV + (
        b"1/1/2099,Buy,AAA,1,$1,$1,,,\n7/20/24,Hold,AAA,1,$1,$1,,,\n"
        b"7/20/24,Buy,AAA,0.0000000001,$1,$1,,,\n"
    )
    _, report = reconstruct(bad, LISTINGS)
    assert [r["row"] for r in report["skipped"]] == [5, 6, 7, 8]
    with pytest.raises(ValueError, match="No importable"):
        reconstruct(CSV, {})
    with pytest.raises(ValueError, match="CSV needs"):
        reconstruct(b"ticker,date\nAAA,2024-01-01\n", LISTINGS)


def test_unformatted_export_preserves_fractional_shares_and_precise_prices():
    values = ["Date(2024,6,22)", "Buy", "AAA", 0.461379, 693.2, 319.8279228, None, None, None]
    columns = "Date,Type,Symbol,Shares,Cost,Total Cost,Price,Market Value,Net".split(",")
    cells = [{"v": v, "f": "0" if i == 3 else "rounded display"} for i, v in enumerate(values)]
    raw = (
        "/*O_o*/\ngoogle.visualization.Query.setResponse("
        + json.dumps({"table": {"cols": [{"label": c} for c in columns], "rows": [{"c": cells}]}})
        + ");"
    ).encode()
    entries, report = reconstruct(raw, LISTINGS)
    assert entries[-1].quantity == Decimal("0.461379")
    assert entries[-1].price == Decimal("693.2")
    assert str(entries[-1].effective_date) == "2024-07-22"
    assert report["raw_source"] == raw.decode()
    assert Decimal(report["opening_cash"]) >= entries[-1].price * entries[-1].quantity
