"""Synthetic ledger request builders shared by independent test modules."""

from datetime import date
from uuid import uuid4

DAYS = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]


def cash(client, account_id, kind="deposit", amount="100", day="2026-01-01", **extra):
    return client.post(
        f"/api/accounts/{account_id}/cash",
        json={
            "request_key": str(uuid4()),
            "kind": kind,
            "amount": amount,
            "effective_date": day,
            "currency": "USD",
            **extra,
        },
    )


def ledger(client, account_id):
    return client.get(f"/api/accounts/{account_id}/ledger").json()


def trade(client, account, kind="buy", quantity="10", price="100", **extra):
    data = {
        "kind": kind,
        "quantity": quantity,
        "price": price,
        "fees": "0",
        "ticker": "DEMO",
        "exchange": "TEST",
        "currency": "USD",
        "effective_date": "2026-01-02",
        "request_key": str(uuid4()),
        **extra,
    }
    if kind in {"opening_position", "transfer_in"}:
        data["price"] = None
    return client.post(f"/api/accounts/{account}/trades", json=data)


def dividend(client, aid, amount="10", pay="2026-01-06", ex="2026-01-05"):
    sid = ledger(client, aid)["holdings"][0]["security"]["id"]
    return cash(
        client,
        aid,
        "income",
        amount,
        day=pay,
        income_kind="dividend",
        income_security_id=sid,
        accrual_date=ex,
    )


def report(client, aid, start="2026-01-02", end="2026-01-06"):
    return client.post(f"/api/accounts/{aid}/performance", json={"start": start, "end": end})


def stock_report(client, aid, **extra):
    return client.post(
        f"/api/accounts/{aid}/performance",
        json={"start": "2026-01-02", "end": "2026-01-06", "scope": "stocks", **extra},
    )
