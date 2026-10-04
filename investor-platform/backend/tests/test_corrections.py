from decimal import Decimal as D
from uuid import uuid4

from helpers import cash, ledger, trade
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investor_platform.models import LedgerCorrection, LedgerEntry, Security


def setup(client):
    aid = client.post(
        "/api/accounts", json={"name": "Correction fixture", "base_currency": "USD"}
    ).json()["id"]
    opening = cash(client, aid, "opening_cash", "1000", day="2026-01-02").json()
    buy = trade(client, aid, quantity="10", price="100", ticker="AAA", exchange="NYSE").json()
    sale = trade(client, aid, "sell", "5", "110", ticker="AAA", exchange="NYSE").json()
    return aid, opening, buy, sale


def replacement(entry, **changes):
    result = {k: entry[k] for k in ("kind", "effective_date", "currency", "note")}
    result["request_key"] = str(uuid4())
    if entry["security"]:
        result.update({k: entry[k] for k in ("quantity", "price", "fees", "cost_basis")})
        result.update({k: entry["security"][k] for k in ("ticker", "exchange")})
    else:
        result["amount"] = entry["amount"]
    return {**result, **changes}


def correction(client, aid, entry, value, **extra):
    body = {
        "request_key": str(uuid4()),
        "reason": "Broker statement correction",
        "replacement": value,
        **extra,
    }
    url = f"/api/accounts/{aid}/entries/{entry['id']}/correction"
    preview = client.post(url + "?preview=true", json=body)
    return url, body, preview


def test_preview_replace_chain_preserves_original_order_and_audit(db_client, database):
    aid, opening, buy, sale = setup(db_client)
    before = ledger(db_client, aid)
    url, body, preview = correction(db_client, aid, buy, replacement(buy, price="90"))
    assert preview.status_code == 200, preview.text
    assert isinstance(preview.json()["balance"], str)
    assert D(preview.json()["balance"]) == 650
    assert ledger(db_client, aid) == before
    body["expected_revision"] = preview.json()["revision"]
    saved = db_client.post(url, json=body)
    assert saved.status_code == 200, saved.text
    assert db_client.post(url, json=body).json() == saved.json()
    assert db_client.post(url, json={**body, "reason": "different"}).status_code == 409
    current = ledger(db_client, aid)
    corrected = current["entries"][1]
    assert [e["kind"] for e in current["entries"]] == ["opening_cash", "buy", "sell"]
    assert D(current["entries"][2]["realized_pnl"]) == 100
    assert current["corrections"][0]["original"]["price"] == buy["price"]
    url2, body2, preview2 = correction(
        db_client, aid, corrected, replacement(corrected, price="80")
    )
    body2["expected_revision"] = preview2.json()["revision"]
    assert db_client.post(url2, json=body2).status_code == 200
    current = ledger(db_client, aid)
    assert D(current["entries"][2]["realized_pnl"]) == 150
    assert len(current["corrections"]) == 2
    with Session(database) as session:
        assert session.get(LedgerEntry, buy["id"]).price == 100
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 5
        assert session.scalar(select(func.count()).select_from(LedgerCorrection)) == 2
    url3, body3, preview3 = correction(db_client, aid, opening, replacement(opening, amount="1500"))
    assert preview3.status_code == 200
    body3["expected_revision"] = preview3.json()["revision"]
    assert db_client.post(url3, json=body3).status_code == 200
    assert ledger(db_client, aid)["entries"][0]["kind"] == "opening_cash"


def test_void_invalid_history_and_stale_preview(db_client, database):
    aid, opening, buy, sale = setup(db_client)
    before = ledger(db_client, aid)
    for entry, value in [
        (buy, None),
        (opening, replacement(opening, amount="1")),
        (buy, replacement(buy, ticker="NEW")),
        (buy, replacement(buy, effective_date="2026-01-05")),
    ]:
        _, _, result = correction(db_client, aid, entry, value)
        assert result.status_code == 409, result.text
        assert ledger(db_client, aid) == before
    with Session(database) as session:
        assert session.scalar(select(Security).where(Security.ticker == "NEW")) is None
    url, body, preview = correction(db_client, aid, sale, None)
    assert preview.status_code == 200
    assert D(preview.json()["balance"]) == 0
    assert D(preview.json()["holdings"][0]["quantity"]) == 10
    body["expected_revision"] = preview.json()["revision"]
    assert cash(db_client, aid, amount="1", day="2026-01-02").status_code == 201
    assert db_client.post(url, json=body).status_code == 409
    fresh = db_client.post(url + "?preview=true", json=body).json()
    body["expected_revision"] = fresh["revision"]
    assert db_client.post(url, json=body).status_code == 200
    assert D(ledger(db_client, aid)["balance"]) == 1
    assert ledger(db_client, aid)["corrections"][0]["replacement"] is None
    url, body, _ = correction(db_client, aid, sale, None)
    assert db_client.post(url, json=body).status_code == 409
    url, body, _ = correction(db_client, aid, buy, replacement(buy))
    assert db_client.post(url, json=body).status_code == 409
    assert db_client.post(url + "?preview=true", json={**body, "reason": " "}).status_code == 422
    assert (
        db_client.post(url.replace(aid, str(uuid4())) + "?preview=true", json=body).status_code
        == 404
    )


def test_opening_basis_correction_updates_fifo_without_changing_shares(db_client):
    aid = db_client.post(
        "/api/accounts", json={"name": "Basis fixture", "base_currency": "USD"}
    ).json()["id"]
    cash(db_client, aid, "opening_cash", "0", day="2026-01-02")
    opening = trade(db_client, aid, "opening_position", "10", ticker="AAA", exchange="NYSE").json()
    trade(db_client, aid, "sell", "5", "20", ticker="AAA", exchange="NYSE")
    assert ledger(db_client, aid)["entries"][-1]["realized_pnl"] is None
    url, body, preview = correction(db_client, aid, opening, replacement(opening, cost_basis="100"))
    assert preview.status_code == 200, preview.text
    body["expected_revision"] = preview.json()["revision"]
    assert db_client.post(url, json=body).status_code == 200
    result = ledger(db_client, aid)
    assert D(result["entries"][-1]["realized_pnl"]) == 50
    assert D(result["holdings"][0]["cost_basis"]) == 50
    assert D(result["holdings"][0]["quantity"]) == 5


def test_concurrent_corrections_only_replace_original_once(db_client):
    from concurrent.futures import ThreadPoolExecutor

    aid, _, buy, _ = setup(db_client)
    attempts = []
    for price in ("90", "80"):
        url, body, preview = correction(db_client, aid, buy, replacement(buy, price=price))
        body["expected_revision"] = preview.json()["revision"]
        attempts.append((url, body))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda attempt: db_client.post(attempt[0], json=attempt[1]), attempts)
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    result = ledger(db_client, aid)
    assert len(result["corrections"]) == 1
    assert len(result["entries"]) == 3
