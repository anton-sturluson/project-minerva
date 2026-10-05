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
    view = db_client.get("/api/accounts").json()[0]
    assert view["reconstruction"]["imported_trades"] == 3
    assert "source_rows" not in view["reconstruction"]
    with pytest.raises(ValueError, match="already has an account"):
        changed, changed_report = reconstruct(CSV.replace(b"$80", b"$81"), LISTINGS)
        apply_import(database, "Synthetic import", changed, changed_report)


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


@pytest.mark.parametrize("google", [False, True])
def test_usd_total_import_preserves_reported_cash_and_basis(database, google):
    from investor_platform.accounting import replay

    columns = ["Date", "Type", "Symbol", "Shares", "Price (USD)", "Total (USD)"]
    values = [
        ["2024-01-02", "Buy", "AAA", 3, 33.33333333, 100.02],
        ["2024-01-03", "Sell", "AAA", 1, 40, 39.98],
    ]
    if google:
        payload = (
            "google.visualization.Query.setResponse("
            + json.dumps(
                {
                    "table": {
                        "cols": [{"label": col} for col in columns],
                        "rows": [{"c": [{"v": v, "f": "rounded"} for v in row]} for row in values],
                    }
                }
            )
            + ");"
        ).encode()
    else:
        payload = (
            ",".join(columns) + "\n" + "\n".join(",".join(map(str, row)) for row in values)
        ).encode()
    entries, report = reconstruct(payload, LISTINGS)
    assert report["transaction_layout"] == "usd-totals"
    assert report["imported_trades"] == 2 and not report["skipped"]
    assert entries[1].price == Decimal("33.33333333")
    assert Decimal(report["opening_cash"]) == Decimal("100.02")
    aid, created = apply_import(database, "Synthetic USD export", entries, report)
    assert created
    with Session(database) as session:
        records = entries_for(session, aid)
        balance, lots, realized = replay(records)
        assert balance == Decimal("39.98")
        assert records[1].amount == Decimal("100.02")
        assert records[2].amount == Decimal("39.98")
        assert records[1].fees == 0  # Never invent itemized fees from the cash difference.
        assert sum(lot.basis for sl in lots.values() for lot in sl) == Decimal("66.68")
        assert realized[records[2].id] == Decimal("6.64")
    assert apply_import(database, "Synthetic USD export", entries, report) == (aid, False)


def test_usd_totals_normalize_export_noise_and_require_explicit_cash():
    payload = b"""Date,Type,Symbol,Shares,Price (USD),Total (USD)
2024-01-02,Buy,AAA,1,10,10.010000000000001
2024-01-03,Buy,AAA,1,10,
2024-01-03,Buy,AAA,1,10,NaN
2024-01-03,Buy,AAA,1,10,-10
2024-01-03,Buy,AAA,1,10,0.0000000001
"""
    entries, report = reconstruct(payload, LISTINGS)
    assert entries[-1].reported_amount == Decimal("10.01")
    assert report["raw_source"] == payload.decode()
    assert report["imported_trades"] == 1
    assert [r["row"] for r in report["skipped"]] == [3, 4, 5, 6]


GROUPED = b"""Date,Type,Symbol,Shares,Price (USD),Total (USD),Portfolio
2024-01-02,Buy,AAA,2,10,20,Active
2024-01-02,Buy,AAA,3,10,30,Index
2024-01-03,Sell,AAA,1,12,12,Active
,,,,,,
"""


def test_grouped_import_requires_ownership_and_isolates_shared_tickers(database):
    from investor_platform.accounting import replay

    with pytest.raises(ValueError, match="Choose --portfolio"):
        reconstruct(GROUPED, LISTINGS)
    reports = []
    ids = []
    for name, expected_cash, expected_shares in [("Active", "12", "1"), ("Index", "0", "3")]:
        entries, report = reconstruct(GROUPED, LISTINGS, portfolio=name)
        aid, created = apply_import(database, name, entries, report)
        assert created and not report["skipped"]
        assert report["raw_source"] == GROUPED.decode()
        assert report["selected_portfolio"] == name
        assert apply_import(database, name, entries, report) == (aid, False)
        with Session(database) as session:
            cash, lots, _ = replay(entries_for(session, aid))
            assert cash == Decimal(expected_cash)
            assert sum(lot.quantity for sl in lots.values() for lot in sl) == Decimal(
                expected_shares
            )
        reports.append(report)
        ids.append(aid)
    assert ids[0] != ids[1]
    assert reports[0]["identity"] != reports[1]["identity"]
    assert reports[0]["other_portfolio_rows"] == [3]
    assert reports[1]["other_portfolio_rows"] == [2, 4]


@pytest.mark.parametrize(
    "payload,selection,message",
    [
        (GROUPED.replace(b",Index", b","), "Active", "Every populated row"),
        (GROUPED, "Missing", "absent"),
        (CSV, "Active", "no Portfolio column"),
    ],
)
def test_grouped_import_rejects_ambiguous_or_missing_ownership(payload, selection, message):
    with pytest.raises(ValueError, match=message):
        reconstruct(payload, LISTINGS, portfolio=selection)


def test_explicit_listing_alias_retains_source_and_changes_retry_identity():
    alias = {**LISTINGS, "AAA": {**LISTINGS["AAA"], "ticker": "NEW"}}
    entries, report = reconstruct(GROUPED, alias, portfolio="Active")
    _, original = reconstruct(GROUPED, LISTINGS, portfolio="Active")
    assert entries[-1].ticker == "NEW"
    assert report["source_rows"][0]["Symbol"] == "AAA"
    assert report["identity"] != original["identity"]
