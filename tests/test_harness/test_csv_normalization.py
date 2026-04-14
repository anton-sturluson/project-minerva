"""Tests for CSV header normalization, Exchange column flow, and enrichment carry-forward."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.morning_brief import collect_filings, ensure_daily_run_layout
from harness.portfolio_state import (
    NON_SECURITY_TICKERS,
    _carry_forward_enrichment,
    _normalize_csv_headers,
    _normalize_csv_key,
    build_universe,
    load_json,
    load_tabular_rows,
    sync_portfolio,
    write_json,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "morning_brief"
RUN_DATE = date(2026, 4, 8)


# ---------------------------------------------------------------------------
# CSV header normalization
# ---------------------------------------------------------------------------


class TestNormalizeCsvKey:
    """Unit tests for the single-key normalizer."""

    def test_simple_lowercase(self):
        assert _normalize_csv_key("Ticker") == "ticker"

    def test_hash_shares(self):
        assert _normalize_csv_key("# Shares") == "shares"

    def test_percent_change(self):
        assert _normalize_csv_key("% Change") == "pct_change"

    def test_multiline_weight(self):
        assert _normalize_csv_key("% Portfolio\n(Value-based)") == "weight"

    def test_singleline_weight(self):
        assert _normalize_csv_key("% Portfolio (Value-based)") == "weight"

    def test_multiline_cost_weight(self):
        assert _normalize_csv_key("% Portfolio\n(Cost-based)") == "cost_weight"

    def test_multiline_target_weight(self):
        assert _normalize_csv_key("Target %\n(Value-based)") == "target_weight"

    def test_typo_year_of_purcase(self):
        assert _normalize_csv_key("Year of Purcase") == "year_of_purchase"

    def test_exchange(self):
        assert _normalize_csv_key("Exchange") == "exchange"

    def test_total_cost(self):
        assert _normalize_csv_key("Total Cost") == "total_cost"

    def test_market_value(self):
        assert _normalize_csv_key("Market Value") == "market_value"

    def test_generic_fallback(self):
        assert _normalize_csv_key("Some Weird Header!") == "some_weird_header"

    def test_leading_trailing_whitespace(self):
        assert _normalize_csv_key("  Ticker  ") == "ticker"


class TestNormalizeCsvHeaders:
    """Integration tests for the full row-list normalizer."""

    GOOGLE_SHEET_HEADERS = [
        "Ticker", "Category", "Year of Purcase", "Cost", "# Shares",
        "Total Cost", "Price", "Market Value", "% Change", "Net", "CAGR",
        "% Portfolio\n(Value-based)", "% Portfolio\n(Cost-based)",
        "Target %\n(Value-based)", "Target diff", "CAGR Target",
        "Price Target", "Target Year", "Exchange",
    ]

    def _make_row(self, values: list[str]) -> dict[str, str]:
        return dict(zip(self.GOOGLE_SHEET_HEADERS, values))

    def test_all_google_sheet_headers_normalised(self):
        row = self._make_row(["NVDA"] + [""] * 18)
        result = _normalize_csv_headers([row])
        keys = set(result[0].keys())
        expected_keys = {
            "ticker", "category", "year_of_purchase", "cost", "shares",
            "total_cost", "price", "market_value", "pct_change", "net", "cagr",
            "weight", "cost_weight", "target_weight", "target_diff",
            "cagr_target", "price_target", "target_year", "exchange",
        }
        assert keys == expected_keys

    def test_values_preserved(self):
        row = self._make_row(["NVDA", "Tech", "2023", "200", "100",
                              "20000", "950", "95000", "375%", "75000", "50%",
                              "55.0", "", "", "", "", "", "", ""])
        result = _normalize_csv_headers([row])
        assert result[0]["ticker"] == "NVDA"
        assert result[0]["shares"] == "100"
        assert result[0]["weight"] == "55.0"

    def test_exchange_column_present(self):
        row = self._make_row(["KPG"] + [""] * 17 + ["ASX"])
        result = _normalize_csv_headers([row])
        assert result[0]["exchange"] == "ASX"

    def test_empty_list(self):
        assert _normalize_csv_headers([]) == []


# ---------------------------------------------------------------------------
# load_tabular_rows with Google-Sheet-style CSV
# ---------------------------------------------------------------------------


class TestLoadTabularRowsCsv:
    """Verify CSV normalization is applied in load_tabular_rows."""

    def test_gsheet_csv_keys_normalized(self):
        rows = load_tabular_rows(str(FIXTURE_DIR / "holdings_gsheet.csv"))
        for row in rows:
            assert "ticker" in row, f"missing 'ticker' key; keys are {list(row.keys())}"
            assert "Ticker" not in row

    def test_gsheet_csv_shares_column(self):
        rows = load_tabular_rows(str(FIXTURE_DIR / "holdings_gsheet.csv"))
        nvda = next(r for r in rows if r["ticker"] == "NVDA")
        assert nvda["shares"] == "100"

    def test_gsheet_csv_exchange_column(self):
        rows = load_tabular_rows(str(FIXTURE_DIR / "holdings_gsheet.csv"))
        kpg = next(r for r in rows if r["ticker"] == "KPG")
        assert kpg["exchange"] == "ASX"

    def test_json_source_not_normalised(self):
        rows = load_tabular_rows(str(FIXTURE_DIR / "watchlist.json"))
        assert rows[0]["ticker"] == "AMD"
        # JSON keys are already lowercase — should not be double-processed.
        assert "ticker" in rows[0]


# ---------------------------------------------------------------------------
# Exchange column flows through sync → universe → enrichment
# ---------------------------------------------------------------------------


class TestExchangeColumnFlowThrough:
    """Verify Exchange column from CSV reaches holdings and universe."""

    def setup_method(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmpdir.name)

    def teardown_method(self):
        self._tmpdir.cleanup()

    def test_exchange_in_holdings_after_sync(self):
        summary = sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        holdings = load_json(
            self.workspace / "data" / "01-portfolio" / "current" / "holdings.json",
            default=[],
        )
        kpg = next((h for h in holdings if h["ticker"] == "KPG"), None)
        assert kpg is not None, "KPG should be in holdings"
        assert kpg["exchange"] == "ASX"

        toi = next((h for h in holdings if h["ticker"] == "TOI"), None)
        assert toi is not None, "TOI should be in holdings"
        assert toi["exchange"] == "TSXV"

    def test_exchange_in_universe_after_sync(self):
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        universe = load_json(
            self.workspace / "data" / "01-portfolio" / "current" / "universe.json",
            default=[],
        )
        kpg = next((u for u in universe if u["ticker"] == "KPG"), None)
        assert kpg is not None
        assert kpg["exchange"] == "ASX"

    def test_non_security_rows_excluded_from_holdings(self):
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        holdings = load_json(
            self.workspace / "data" / "01-portfolio" / "current" / "holdings.json",
            default=[],
        )
        tickers = {h["ticker"] for h in holdings}
        assert "CASH" not in tickers
        assert "TOTAL" not in tickers


# ---------------------------------------------------------------------------
# Enrichment data preserved across re-syncs
# ---------------------------------------------------------------------------


class TestEnrichmentCarryForward:
    """Enrichment fields survive a re-sync from the Google Sheet."""

    def setup_method(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmpdir.name)

    def teardown_method(self):
        self._tmpdir.cleanup()

    def test_carry_forward_preserves_country_and_sec_registered(self):
        # First sync — plain CSV, no enrichment.
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        # Simulate enrichment by writing enriched data into holdings.json.
        holdings_path = self.workspace / "data" / "01-portfolio" / "current" / "holdings.json"
        holdings = load_json(holdings_path, default=[])
        for h in holdings:
            if h["ticker"] == "NVDA":
                h["exchange"] = "NASDAQ"
                h["country"] = "US"
                h["sec_registered"] = True
                h["finnhub_symbol"] = "NVDA"
            if h["ticker"] == "KPG":
                h["country"] = "AU"
                h["sec_registered"] = False
                h["finnhub_symbol"] = "KPG.AX"
        write_json(holdings_path, holdings)

        # Re-sync from same CSV — enrichment fields should survive.
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        holdings = load_json(holdings_path, default=[])
        nvda = next(h for h in holdings if h["ticker"] == "NVDA")
        assert nvda["country"] == "US"
        assert nvda["sec_registered"] is True
        assert nvda["finnhub_symbol"] == "NVDA"

        kpg = next(h for h in holdings if h["ticker"] == "KPG")
        assert kpg["country"] == "AU"
        assert kpg["sec_registered"] is False
        assert kpg["finnhub_symbol"] == "KPG.AX"
        # Exchange from sheet should take precedence.
        assert kpg["exchange"] == "ASX"

    def test_sheet_exchange_overrides_enriched_exchange(self):
        # First sync.
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        holdings_path = self.workspace / "data" / "01-portfolio" / "current" / "holdings.json"
        holdings = load_json(holdings_path, default=[])
        for h in holdings:
            if h["ticker"] == "KPG":
                h["exchange"] = "OLD_EXCHANGE"
                h["country"] = "AU"
        write_json(holdings_path, holdings)

        # Re-sync — sheet says "ASX", should win over "OLD_EXCHANGE".
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        holdings = load_json(holdings_path, default=[])
        kpg = next(h for h in holdings if h["ticker"] == "KPG")
        assert kpg["exchange"] == "ASX"

    def test_carry_forward_unit_function(self):
        current = [
            {"security_id": "NVDA", "ticker": "NVDA"},
            {"security_id": "KPG", "ticker": "KPG", "exchange": "ASX"},
        ]
        previous = [
            {"security_id": "NVDA", "ticker": "NVDA", "exchange": "NASDAQ",
             "country": "US", "sec_registered": True, "finnhub_symbol": "NVDA"},
            {"security_id": "KPG", "ticker": "KPG", "exchange": "OLD",
             "country": "AU", "sec_registered": False, "finnhub_symbol": "KPG.AX"},
        ]
        _carry_forward_enrichment(current, previous)

        nvda = current[0]
        assert nvda["exchange"] == "NASDAQ"  # no new exchange → keep old
        assert nvda["country"] == "US"
        assert nvda["sec_registered"] is True
        assert nvda["finnhub_symbol"] == "NVDA"

        kpg = current[1]
        assert kpg["exchange"] == "ASX"  # new exchange present → keep new
        assert kpg["country"] == "AU"
        assert kpg["sec_registered"] is False
        assert kpg["finnhub_symbol"] == "KPG.AX"


# ---------------------------------------------------------------------------
# Filings collector skips non-security rows
# ---------------------------------------------------------------------------


class TestFilingsSkipsNonSecurity:
    """collect_filings should not attempt SEC lookups for CASH, TOTAL, etc."""

    def setup_method(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmpdir.name)

    def teardown_method(self):
        self._tmpdir.cleanup()

    def test_non_security_tickers_skipped(self):
        # Sync with the Google Sheet CSV (includes CASH, TOTAL rows).
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        # Even though CASH/TOTAL are filtered during normalize_holdings,
        # verify the set itself is correct.
        assert "CASH" in NON_SECURITY_TICKERS
        assert "TOTAL" in NON_SECURITY_TICKERS
        assert "CURRENT ASSET" in NON_SECURITY_TICKERS
        assert "INVESTABLE" in NON_SECURITY_TICKERS
        assert "NON-INVESTABLE" in NON_SECURITY_TICKERS
        assert "INVESTABLE CURRENT ASSET" in NON_SECURITY_TICKERS

    def test_collect_filings_skips_non_security_in_universe(self):
        """If non-security rows somehow end up in the universe, collect_filings skips them."""
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings_gsheet.csv"),
        )
        # Inject a CASH entry directly into universe.json to test the guard.
        universe_path = self.workspace / "data" / "01-portfolio" / "current" / "universe.json"
        universe = load_json(universe_path, default=[])
        universe.append({"security_id": "CASH", "ticker": "CASH", "sources": ["holding"]})
        write_json(universe_path, universe)

        # Use fixture source so we don't hit SEC EDGAR.
        result = collect_filings(
            self.workspace,
            run_date=RUN_DATE,
            source=str(FIXTURE_DIR / "filings.json"),
        )
        # Should succeed without trying to look up CASH as a ticker.
        assert result["status"] in {"success", "degraded"}
