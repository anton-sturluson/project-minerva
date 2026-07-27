"""Focused behavior for direct Finnhub news downloads."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness import news
from harness.cli import app
from harness.commands import news as news_commands
from harness.config import HarnessSettings
from harness.finnhub import FinnhubNewsPayload

runner = CliRunner()


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def _realistic_item(
    *, published: str, url: str = "https://example.test/nvda"
) -> dict[str, object]:
    return {
        "category": "company",
        "datetime": _timestamp(published),
        "headline": "Nvidia unveils its next AI platform",
        "id": 129876543,
        "image": "https://example.test/image.jpg",
        "related": "NVDA",
        "source": "Reuters",
        "summary": "The company introduced a new platform for AI workloads.",
        "url": url,
    }


def _settings(tmp_path: Path, *, api_key: str | None = "test-key") -> HarnessSettings:
    return HarnessSettings(
        workspace_root=tmp_path / "workspace", finnhub_api_key=api_key
    )


def test_download_finnhub_uses_current_universe_filters_new_york_day_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    universe_path = (
        settings.resolved_workspace_root
        / "data"
        / "01-portfolio"
        / "current"
        / "universe.json"
    )
    universe_path.parent.mkdir(parents=True)
    universe_path.write_text(
        json.dumps(
            [
                {
                    "security_id": "KPG",
                    "ticker": "KPG",
                    "finnhub_symbol": "KPG.AX",
                    "sec_registered": False,
                    "source_kind": "holding",
                },
                {
                    "security_id": "SNOW",
                    "ticker": "SNOW",
                    "source_kind": "watchlist",
                },
                {"security_id": "CASH", "ticker": "CASH"},
            ]
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, date, dict[str, str]]] = []
    on_date = _realistic_item(published="2026-07-19T00:15:00-04:00")
    duplicate = dict(on_date, related="KPG.AX")
    prior_et_day = _realistic_item(
        published="2026-07-18T23:59:00-04:00",
        url="https://example.test/old",
    )

    def fake_fetch(
        *, api_key: str, publication_date: date, symbols: dict[str, str]
    ) -> FinnhubNewsPayload:
        calls.append((api_key, publication_date, symbols))
        return FinnhubNewsPayload(
            general=[on_date, prior_et_day],
            company=[duplicate],
            errors=0,
        )

    monkeypatch.setattr(news_commands, "get_settings", lambda: settings)
    monkeypatch.setattr(news, "fetch_finnhub_news", fake_fetch)
    db_path = tmp_path / "invest.db"
    args = [
        "news",
        "download-finnhub",
        "--date",
        "2026-07-19",
        "--db",
        str(db_path),
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout) == {
        "date": "2026-07-19",
        "db_total": 1,
        "duplicates": 1,
        "eligible": 2,
        "errors": 0,
        "fetched": 3,
        "inserted": 1,
        "skipped": 1,
        "symbols": 2,
        "timezone": "America/New_York",
    }
    assert json.loads(second.stdout) == {
        **json.loads(first.stdout),
        "duplicates": 2,
        "inserted": 0,
    }
    assert calls == [
        ("test-key", date(2026, 7, 19), {"KPG.AX": "KPG", "SNOW": "SNOW"}),
        ("test-key", date(2026, 7, 19), {"KPG.AX": "KPG", "SNOW": "SNOW"}),
    ]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT published_at, published_at_raw, title, content, summary, "
            "source, url, section FROM news"
        ).fetchone()
    assert row == (
        _timestamp("2026-07-19T00:15:00-04:00"),
        "2026-07-19T00:15:00-04:00",
        "Nvidia unveils its next AI platform",
        "The company introduced a new platform for AI workloads.",
        None,
        "reuters",
        "https://example.test/nvda",
        "finnhub-general",
    )


def test_download_finnhub_symbol_override_preserves_richer_existing_article(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    db_path = tmp_path / "invest.db"
    item = _realistic_item(published="2026-07-19T12:00:00-04:00")
    key = news.article_key("reuters", "2026-07-19", str(item["headline"]))
    with sqlite3.connect(db_path) as conn:
        news.ensure_schema(conn)
        conn.execute(
            "INSERT INTO news VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                item["datetime"],
                "2026-07-19T12:00:00-04:00",
                item["headline"],
                "Full crawler article body with substantially richer reporting.",
                "Existing analyst summary.",
                "reuters",
                item["url"],
                "markets",
                "2026-07-19T17:00:00Z",
            ),
        )

    captured_symbols: list[dict[str, str]] = []

    def fake_fetch(
        *, api_key: str, publication_date: date, symbols: dict[str, str]
    ) -> FinnhubNewsPayload:
        captured_symbols.append(symbols)
        return FinnhubNewsPayload(general=[], company=[item], errors=0)

    monkeypatch.setattr(news_commands, "get_settings", lambda: settings)
    monkeypatch.setattr(news, "fetch_finnhub_news", fake_fetch)

    result = runner.invoke(
        app,
        [
            "news",
            "download-finnhub",
            "--date",
            "2026-07-19",
            "--db",
            str(db_path),
            "--symbol",
            "nvda",
            "--symbol",
            "NVDA",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["duplicates"] == 1
    assert json.loads(result.stdout)["inserted"] == 0
    assert captured_symbols == [{"NVDA": "NVDA"}]
    with sqlite3.connect(db_path) as conn:
        stored = conn.execute(
            "SELECT content, summary, section, COUNT(*) FROM news"
        ).fetchone()
    assert stored == (
        "Full crawler article body with substantially richer reporting.",
        "Existing analyst summary.",
        "markets",
        1,
    )


def test_download_finnhub_requires_configured_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, api_key=None)
    monkeypatch.setattr(news_commands, "get_settings", lambda: settings)
    db_path = tmp_path / "invest.db"

    result = runner.invoke(
        app,
        [
            "news",
            "download-finnhub",
            "--date",
            "2026-07-19",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "FINNHUB_API_KEY is not configured" in result.stderr
    assert not db_path.exists()
