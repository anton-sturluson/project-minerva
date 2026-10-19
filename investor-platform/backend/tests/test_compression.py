"""Verify compressed economics responses through the private HTTP access boundary."""

import gzip
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform.app import create_app
from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import EconomicObservation


def test_economics_compression_preserves_json_and_private_access(
    database: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compress a real history response while retaining identity and origin checks."""
    origin: str = "https://test.tail123.ts.net:8444"
    login: str = "investor@example.com"
    monkeypatch.setenv("INVESTOR_MODE", "tailscale")
    monkeypatch.setenv("TAILSCALE_ORIGIN", origin)
    monkeypatch.setenv("TAILSCALE_USER_LOGIN", login)
    monkeypatch.delenv("INVESTOR_DAILY_PRICES", raising=False)
    monkeypatch.delenv("INVESTOR_ECONOMICS_REFRESH", raising=False)
    (tmp_path / "index.html").write_text("<h1>Synthetic private platform</h1>")
    day: date = date(2023, 1, 2)
    observed: datetime = datetime(2026, 10, 18, tzinfo=UTC)
    session: Session
    with Session(database) as session, session.begin():
        session.add_all(
            [
                EconomicObservation(
                    workspace_id=LOCAL_WORKSPACE,
                    series_key="treasury-10y",
                    observation_date=day + timedelta(days=index),
                    value=Decimal("3") + Decimal(index) / 1000,
                    missing=False,
                    collected_at=observed,
                    provenance={
                        "sha256": "a" * 64,
                        "source_url": "https://example.com/treasury-history.csv",
                        "footnotes": [],
                        "derived_from": [],
                    },
                )
                for index in range(730)
                if (day + timedelta(days=index)).weekday() < 5
            ]
        )
    application: FastAPI = create_app(web_dist=tmp_path)
    application.state.engine = database
    client: TestClient
    with TestClient(application, base_url=origin, client=("127.0.0.1", 12345)) as client:
        path: str = "/api/research/economics/series/treasury-10y"
        plain: httpx.Response = client.get(
            path, headers={"Tailscale-User-Login": login, "Accept-Encoding": "identity"}
        )
        assert plain.status_code == 200 and "content-encoding" not in plain.headers
        assert len(plain.json()["observations"]) > 500
        compressed: httpx.Response
        with client.stream(
            "GET", path, headers={"Tailscale-User-Login": login, "Accept-Encoding": "gzip"}
        ) as compressed:
            wire_body: bytes = b"".join(compressed.iter_raw())
            assert compressed.status_code == 200
            assert compressed.headers["content-encoding"] == "gzip"
            assert "accept-encoding" in compressed.headers["vary"].lower()
            assert compressed.headers["cache-control"] == "no-store"
            assert gzip.decompress(wire_body) == plain.content
            assert len(wire_body) < len(plain.content) / 10
        denied: httpx.Response = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert denied.status_code == 403
        assert denied.json() == {"detail": "Access requires the allowed Tailscale user"}
        assert denied.headers["cache-control"] == "no-store"
        assert (
            client.get(
                path,
                headers={
                    "Tailscale-User-Login": login,
                    "Accept-Encoding": "gzip",
                    "Origin": "https://example.com",
                },
            ).status_code
            == 403
        )
