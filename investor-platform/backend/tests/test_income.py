from decimal import Decimal
from uuid import uuid4

from test_ledger import cash, ledger


def test_income_persists_once_as_earnings_and_requires_positive_amount(db_client):
    aid = db_client.post(
        "/api/account", json={"name": "Income fixture", "base_currency": "USD"}
    ).json()["id"]
    assert cash(db_client, aid, "opening_cash", "100").status_code == 201
    key = str(uuid4())
    for _ in range(2):
        assert cash(db_client, aid, "income", "2.50", request_key=key).status_code == 201
    result = ledger(db_client, aid)
    assert Decimal(result["balance"]) == Decimal("102.50")
    assert [e["kind"] for e in result["entries"]] == ["opening_cash", "income"]
    assert cash(db_client, aid, "income", "0").status_code == 422
    assert cash(db_client, aid, "income", "3", request_key=key).status_code == 409
    assert ledger(db_client, aid) == result
