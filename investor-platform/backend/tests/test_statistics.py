from decimal import Decimal as D
from uuid import uuid4

import pytest
from test_ledger import cash
from test_trades import trade


def test_closed_episode_scorecard_partial_exits_fees_unknown_and_breakeven(db_client):
    aid = db_client.post("/api/account", json={"name": "Scorecard", "base_currency": "USD"}).json()[
        "id"
    ]
    cash(db_client, aid, "opening_cash", "10000")
    # One winning episode, split into two exits. Net gain 196 after four dollars of fees.
    trade(db_client, aid, quantity="10", fees="2")
    trade(db_client, aid, "sell", "5", "120", fees="1")
    r = db_client.get(f"/api/accounts/{aid}/statistics").json()
    assert r["closed"] == 0 and r["open"] == 1 and r["payoff_ratio"] is None
    trade(db_client, aid, "sell", "5", "120", fees="1")
    trade(db_client, aid, quantity="10")
    trade(db_client, aid, "sell", "10", "90")
    trade(db_client, aid, quantity="1")
    trade(db_client, aid, "sell", "1", "100")
    trade(db_client, aid, "opening_position", "1", ticker="UNKNOWN")
    trade(db_client, aid, "sell", "1", "200", ticker="UNKNOWN")
    r = db_client.get(f"/api/accounts/{aid}/statistics").json()
    assert (r["wins"], r["losses"], r["breakeven"], r["unknown"], r["closed"]) == (1, 1, 1, 1, 4)
    assert D(r["payoff_ratio"]) == D("1.96")
    assert float(r["win_rate"]) == pytest.approx(1 / 3)
    assert D(r["realized_pnl"]) == 96
    assert db_client.get(f"/api/accounts/{uuid4()}/statistics").status_code == 404
