"""Tests for the morning-brief portfolio state, evidence pipeline, and wrapper."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from harness.commands import brief, portfolio
from harness.config import HarnessSettings
from harness.morning_brief import (
    _parse_ir_feed,
    _parse_ir_html,
    append_review_log,
    audit_evidence,
    collect_earnings,
    collect_filings,
    collect_ir,
    collect_macro,
    collect_macro_registry_events,
    collect_market,
    ensure_daily_run_layout,
    load_manifest,
    normalize_company_news_events,
    normalize_news_events,
    prepare_evidence,
)
from harness.portfolio_state import (
    add_adjacency_entry,
    enrich_portfolio,
    load_json,
    set_thesis_card_v2,
    sync_portfolio,
    write_json,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "morning_brief"
RUN_DATE = date(2026, 4, 8)
REPO_ROOT = Path(__file__).resolve().parents[2]


class MorningBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_portfolio_sync_and_curation_render_state(self) -> None:
        summary = sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
            watchlist_source=str(FIXTURE_DIR / "watchlist.json"),
        )
        adjacency = add_adjacency_entry(
            self.workspace,
            monitored="NVDA",
            adjacent="TSM",
            relationship_type="supply-chain",
            note="Packaging and foundry read-through",
            priority="high",
        )
        thesis = set_thesis_card_v2(
            self.workspace,
            card_id="nvda",
            ticker_symbols=["NVDA"],
            summary="AI demand remains the core portfolio driver.",
            core_thesis=["Blackwell ramps", "Networking attach stays elevated"],
            signals=["Cloud capex slows materially"],
        )

        self.assertEqual(summary["holdings_count"], 2)
        self.assertEqual(summary["watchlist_count"], 2)
        self.assertEqual(summary["universe_count"], 4)
        self.assertEqual(adjacency["adjacent"], "TSM")
        self.assertEqual(thesis["card_id"], "nvda")

        rendered = (self.workspace / "data" / "01-portfolio" / "current" / "rendered.md").read_text(encoding="utf-8")
        history = (self.workspace / "data" / "01-portfolio" / "history" / "rendered-history.md").read_text(encoding="utf-8")
        universe = load_json(self.workspace / "data" / "01-portfolio" / "current" / "universe.json", default=[])

        self.assertIn("## Holdings", rendered)
        self.assertIn("`NVDA` | NVIDIA Corp", rendered)
        self.assertIn("## Recent Metadata Changes", history)
        self.assertEqual({item["security_id"] for item in universe}, {"AMD", "MSFT", "NVDA", "SNOW"})

    def test_brief_pipeline_writes_manifest_outputs_and_review_log(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
            watchlist_source=str(FIXTURE_DIR / "watchlist.json"),
        )
        add_adjacency_entry(
            self.workspace,
            monitored="NVDA",
            adjacent="TSM",
            relationship_type="supply-chain",
            note="Packaging read-through",
            priority="high",
        )
        set_thesis_card_v2(
            self.workspace,
            card_id="nvda",
            ticker_symbols=["NVDA"],
            summary="AI demand remains the core portfolio driver.",
            core_thesis=["Blackwell ramps"],
            signals=["Cloud capex slows materially"],
        )

        ir_registry = self.workspace / "ir-registry.json"
        ir_registry.write_text(
            json.dumps(
                [
                    {
                        "security_id": "NVDA",
                        "ticker": "NVDA",
                        "feeds": [
                            {
                                "format": "xml",
                                "url": str(FIXTURE_DIR / "nvda-ir.xml"),
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )

        collect_filings(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "filings.json"))
        collect_earnings(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "market-data.json"))
        collect_macro(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "macro-events.json"))
        collect_ir(self.workspace, run_date=RUN_DATE, registry_path=ir_registry)
        collect_market(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "market-data.json"))
        prepare_evidence(self.workspace, run_date=RUN_DATE)
        audit_evidence(self.workspace, run_date=RUN_DATE)
        append_review_log(self.workspace, run_date=RUN_DATE, notes="fixture-backed validation")

        run_paths = ensure_daily_run_layout(self.workspace, RUN_DATE)
        manifest = load_manifest(run_paths)
        prepared = load_json(run_paths.structured_dir / "prepared-evidence.json", default={})
        review_entries = [
            json.loads(line)
            for line in run_paths.review_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        self.assertTrue(
            {"filings", "earnings", "macro", "ir", "market", "prep", "audit", "review-log"}.issubset(manifest["sources"])
        )
        self.assertTrue(manifest["outputs"]["notes"]["morning_brief_report"].endswith("notes/morning-brief-report.md"))
        self.assertTrue(manifest["outputs"]["raw"]["filings"].endswith("data/raw/filings.json"))
        self.assertTrue(
            manifest["outputs"]["structured"]["prepared_evidence"].endswith("data/structured/prepared-evidence.json")
        )
        self.assertTrue(manifest["outputs"]["rendered"]["grouped_events"].endswith("data/rendered/grouped-events.md"))
        self.assertTrue(Path(manifest["outputs"]["structured"]["prepared_evidence"]).exists())
        self.assertTrue(Path(manifest["outputs"]["rendered"]["audit"]).exists())
        self.assertTrue(Path(manifest["outputs"]["notes"]["slack_brief"]).exists())
        self.assertTrue(
            any(event["headline"] == "TSM reported stronger AI packaging demand" for event in prepared["grouped_events"]["read-through"])
        )
        self.assertTrue(any(event["headline"] == "CPI release" for event in prepared["grouped_events"]["macro-policy"]))
        self.assertTrue(any(event["source_name"] == "market" for event in prepared["grouped_events"]["market-context"]))
        self.assertEqual(review_entries[-1]["notes"], "fixture-backed validation")

    def test_brief_dispatch_allows_fixture_backed_filings_without_edgar(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
            watchlist_source=str(FIXTURE_DIR / "watchlist.json"),
        )
        settings = HarnessSettings(workspace_root=self.workspace)

        def _should_not_run(_: HarnessSettings) -> str | None:
            raise AssertionError("EDGAR identity should not be required when --source is provided")

        with patch("harness.commands.brief._configure_edgar", _should_not_run):
            result = brief.dispatch(
                ["filings", "--date", RUN_DATE.isoformat(), "--source", str(FIXTURE_DIR / "filings.json")],
                settings=settings,
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("event_count: 2", result.stdout.decode("utf-8"))

    def test_collect_market_keeps_non_material_index_quotes(self) -> None:
        quiet_market = self.workspace / "quiet-market.json"
        quiet_market.write_text(
            json.dumps(
                {
                    "indexes": [
                        {
                            "symbol": "SPY",
                            "change_pct": 0.42,
                            "headline": "S&P 500 was little changed",
                            "material": False,
                        }
                    ],
                    "rates": [
                        {
                            "name": "US10Y",
                            "change_pct": -0.05,
                            "headline": "US 10Y yield edged lower",
                            "material": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        summary = collect_market(self.workspace, run_date=RUN_DATE, source=str(quiet_market))
        payload = load_json(Path(summary["raw_path"]), default={})
        events = payload.get("events", [])

        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual([event["headline"] for event in events], ["S&P 500 was little changed", "US 10Y yield edged lower"])
        self.assertTrue(all(event["material"] is False for event in events))

    def test_parse_ir_html_filters_navigation_links(self) -> None:
        raw_html = """
        <html>
          <body>
            <nav>
              <a href="/home">Home</a>
              <a href="/contact">Contact</a>
              <a href="/buy">Buy Now</a>
              <a href="#main">Skip to main content</a>
            </nav>
            <main>
              <a href="/news/q1-2026-results">Acme Corp Announces First Quarter 2026 Financial Results</a>
              <a href="/newsroom">Newsroom</a>
            </main>
          </body>
        </html>
        """

        events = _parse_ir_html(raw_html, RUN_DATE, "ACME", "https://investors.example.com/releases")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], "Acme Corp Announces First Quarter 2026 Financial Results")
        self.assertEqual(events[0]["reference_url"], "https://investors.example.com/news/q1-2026-results")

    def test_parse_ir_feed_xml_falls_back_to_filtered_html(self) -> None:
        raw_html = """
        <html>
          <body>
            <a href="/home">Home</a>
            <a href="/news/april-2026-dividend">Acme Declares April 2026 Quarterly Dividend</a>
          </body>
        </html>
        """

        with patch("harness.morning_brief.read_text_source", return_value=(raw_html, None)):
            events = _parse_ir_feed("https://investors.example.com/feed.xml", "xml", RUN_DATE, "ACME", {})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], "Acme Declares April 2026 Quarterly Dividend")
        self.assertEqual(events[0]["reference_url"], "https://investors.example.com/news/april-2026-dividend")

    def test_macro_collect_builds_normalized_events_from_registry_sources(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
            watchlist_source=str(FIXTURE_DIR / "watchlist.json"),
        )
        bls_page = self.workspace / "bls.html"
        bls_page.write_text(
            """
            <html>
              <body>
                <table>
                  <tr><th>Date</th><th>Time</th><th>Release</th></tr>
                  <tr>
                    <td>April 8, 2026</td>
                    <td>8:30 AM ET</td>
                    <td><a href="https://www.bls.gov/schedule/cpi">Consumer Price Index</a></td>
                  </tr>
                  <tr>
                    <td>April 9, 2026</td>
                    <td>8:30 AM ET</td>
                    <td><a href="https://www.bls.gov/schedule/ppi">Producer Price Index</a></td>
                  </tr>
                </table>
              </body>
            </html>
            """,
            encoding="utf-8",
        )
        fed_page = self.workspace / "fed.html"
        fed_page.write_text(
            """
            <html>
              <body>
                <article>
                  <time datetime="2026-04-08">April 8, 2026</time>
                  <a href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260408a.htm">
                    FOMC Minutes Release
                  </a>
                </article>
              </body>
            </html>
            """,
            encoding="utf-8",
        )
        registry = self.workspace / "macro-registry.json"
        registry.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "BLS",
                            "category": "macro",
                            "importance": "high",
                            "parser": "bls_schedule",
                            "url": str(bls_page),
                        },
                        {
                            "name": "Federal Reserve",
                            "category": "policy",
                            "importance": "high",
                            "parser": "federal_reserve_events",
                            "url": str(fed_page),
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        summary = collect_macro_registry_events(
            self.workspace,
            run_date=RUN_DATE,
            registry_path=registry,
        )

        payload = load_json(Path(summary["output_path"]), default={})
        events = payload.get("events", [])
        events_by_source = {event["source_name"]: event for event in events}
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(sorted(event["event_name"] for event in events), ["Consumer Price Index", "FOMC Minutes Release"])
        self.assertEqual(events_by_source["BLS"]["release_time"], "8:30 AM ET")
        self.assertEqual(events_by_source["BLS"]["source_url"], "https://www.bls.gov/schedule/cpi")

    def test_macro_collect_output_can_feed_macro_brief_and_preserve_degraded_reasons(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
            watchlist_source=str(FIXTURE_DIR / "watchlist.json"),
        )
        registry = self.workspace / "macro-registry.json"
        registry.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "BLS",
                            "category": "macro",
                            "importance": "high",
                            "parser": "normalized_json",
                            "url": str(FIXTURE_DIR / "macro-events.json"),
                        },
                        {
                            "name": "Broken source",
                            "parser": "not-supported",
                            "url": str(FIXTURE_DIR / "macro-events.json"),
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        collect_summary = collect_macro_registry_events(self.workspace, run_date=RUN_DATE, registry_path=registry)
        macro_summary = collect_macro(
            self.workspace,
            run_date=RUN_DATE,
            source=str(collect_summary["output_path"]),
            registry_path=registry,
        )

        run_paths = ensure_daily_run_layout(self.workspace, RUN_DATE)
        macro_payload = load_json(run_paths.raw_dir / "macro.json", default={})

        self.assertEqual(macro_summary["status"], "degraded")
        self.assertEqual(macro_summary["event_count"], 1)
        self.assertTrue(any("Broken source" in reason for reason in macro_payload["degraded_reasons"]))

    def test_wrapper_orchestrates_command_sequence_with_optional_sources(self) -> None:
        """V2 script runs structured data + prep (news collection skipped via env)."""
        call_log = self.workspace / "calls.log"
        fake_minerva = self.workspace / "fake-minerva.sh"
        fake_minerva.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$MINERVA_CALL_LOG\"\n",
            encoding="utf-8",
        )
        fake_minerva.chmod(0o755)

        # Use a fake HOME so the v2 script's `source ~/.zshrc` is a no-op
        # and doesn't re-export real env vars over our test overrides.
        fake_home = self.workspace / "fakehome"
        fake_home.mkdir(exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(fake_home),
                "MINERVA_CALL_LOG": str(call_log),
                "MINERVA_RUNNER": str(fake_minerva),
                "MINERVA_SKIP_STATUS_CHECK": "1",
                "MINERVA_SKIP_NEWS": "1",
                "MINERVA_WORKSPACE_ROOT": str(self.workspace / "workspace"),
                "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": str(FIXTURE_DIR / "holdings.csv"),
                "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": str(FIXTURE_DIR / "transactions.csv"),
                "MINERVA_PORTFOLIO_WATCHLIST_SOURCE": str(FIXTURE_DIR / "watchlist.json"),
                "MINERVA_BRIEF_EARNINGS_SOURCE": str(FIXTURE_DIR / "market-data.json"),
                "MINERVA_BRIEF_MARKET_SOURCE": str(FIXTURE_DIR / "market-data.json"),
            }
        )

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "run_morning_brief.sh"), RUN_DATE.isoformat()],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        # V2 prints output paths relative to ROOT_DIR/hard-disk, not MINERVA_WORKSPACE_ROOT.
        self.assertIn("prepared_evidence:", result.stdout)
        self.assertIn("manifest:", result.stdout)
        # V2 creates dirs under ROOT_DIR/hard-disk.
        report_dir = REPO_ROOT / "hard-disk" / "reports" / "03-daily-news" / RUN_DATE.isoformat()
        self.assertTrue(report_dir.is_dir())
        self.assertEqual(
            call_log.read_text(encoding="utf-8").splitlines(),
            [
                f"portfolio sync --date {RUN_DATE.isoformat()} --holdings-source {FIXTURE_DIR / 'holdings.csv'} --transactions-source {FIXTURE_DIR / 'transactions.csv'} --watchlist-source {FIXTURE_DIR / 'watchlist.json'}",
                f"brief filings --date {RUN_DATE.isoformat()}",
                f"brief earnings --date {RUN_DATE.isoformat()} --provider finnhub --source {FIXTURE_DIR / 'market-data.json'}",
                f"brief market --date {RUN_DATE.isoformat()} --provider finnhub --source {FIXTURE_DIR / 'market-data.json'}",
                f"brief prep --date {RUN_DATE.isoformat()}",
            ],
        )

    def test_wrapper_skips_news_collection_when_env_set(self) -> None:
        """MINERVA_SKIP_NEWS=1 skips browser/openclaw news agents."""
        call_log = self.workspace / "calls.log"
        fake_minerva = self.workspace / "fake-minerva.sh"
        fake_minerva.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$MINERVA_CALL_LOG\"\n",
            encoding="utf-8",
        )
        fake_minerva.chmod(0o755)

        fake_home = self.workspace / "fakehome"
        fake_home.mkdir(exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(fake_home),
                "MINERVA_CALL_LOG": str(call_log),
                "MINERVA_RUNNER": str(fake_minerva),
                "MINERVA_SKIP_STATUS_CHECK": "1",
                "MINERVA_SKIP_NEWS": "1",
                "MINERVA_WORKSPACE_ROOT": str(self.workspace / "workspace"),
                "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": str(FIXTURE_DIR / "holdings.csv"),
                "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": str(FIXTURE_DIR / "transactions.csv"),
                "MINERVA_PORTFOLIO_WATCHLIST_SOURCE": str(FIXTURE_DIR / "watchlist.json"),
                "MINERVA_BRIEF_EARNINGS_SOURCE": str(FIXTURE_DIR / "market-data.json"),
                "MINERVA_BRIEF_MARKET_SOURCE": str(FIXTURE_DIR / "market-data.json"),
            }
        )

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "run_morning_brief.sh"), RUN_DATE.isoformat()],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("News collection (skipped)", result.stdout)
        # No openclaw agent or news-related minerva calls in the log.
        logged_commands = call_log.read_text(encoding="utf-8")
        self.assertNotIn("openclaw", logged_commands)
        self.assertNotIn("extract-files", logged_commands)


    def test_portfolio_enrich_uses_symbol_table_without_api_key(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
        )
        # Overwrite holdings with tickers from the symbol table
        holdings = [
            {"security_id": "GOOGL", "ticker": "GOOGL", "company_name": "Alphabet", "source_kind": "holding"},
            {"security_id": "KPG", "ticker": "KPG", "company_name": "Kelly Partners Group", "source_kind": "holding"},
            {"security_id": "TOI", "ticker": "TOI", "company_name": "Topicus.com", "source_kind": "holding"},
        ]
        paths = self.workspace / "data" / "01-portfolio" / "current"
        write_json(paths / "holdings.json", holdings)
        write_json(paths / "watchlist.json", [])
        write_json(paths / "universe.json", holdings)

        summary = enrich_portfolio(self.workspace, finnhub_api_key=None)

        enriched_holdings = load_json(paths / "holdings.json", default=[])
        googl = next(h for h in enriched_holdings if h["ticker"] == "GOOGL")
        kpg = next(h for h in enriched_holdings if h["ticker"] == "KPG")
        toi = next(h for h in enriched_holdings if h["ticker"] == "TOI")

        self.assertEqual(summary["enriched_count"], 3)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(googl["finnhub_symbol"], "GOOGL")
        self.assertEqual(googl["sec_registered"], True)
        self.assertEqual(googl["exchange"], "NASDAQ")
        self.assertEqual(kpg["finnhub_symbol"], "KPG.AX")
        self.assertEqual(kpg["sec_registered"], False)
        self.assertEqual(kpg["country"], "AU")
        self.assertEqual(toi["finnhub_symbol"], "TOI.V")
        self.assertEqual(toi["sec_registered"], False)

    def test_portfolio_enrich_command_dispatch(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
        )
        settings = HarnessSettings(workspace_root=self.workspace)
        result = portfolio.dispatch(["enrich"], settings=settings)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("enriched:", result.stdout.decode("utf-8"))

    def test_filings_collector_skips_non_sec_tickers(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
        )
        # Mark NVDA as non-SEC, MSFT as SEC-registered
        universe = [
            {"security_id": "NVDA", "ticker": "NVDA", "company_name": "NVIDIA", "sec_registered": False, "sources": ["holding"]},
            {"security_id": "MSFT", "ticker": "MSFT", "company_name": "Microsoft", "sec_registered": True, "sources": ["holding"]},
        ]
        write_json(self.workspace / "data" / "01-portfolio" / "current" / "universe.json", universe)

        # Use fixture so we don't need EDGAR identity
        summary = collect_filings(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "filings.json"))
        # With source file, all events come through (source bypass)
        self.assertEqual(summary["status"], "success")

    def test_expanded_market_quotes_fixture(self) -> None:
        expanded_market = self.workspace / "expanded-market.json"
        expanded_market.write_text(
            json.dumps(
                {
                    "indexes": [
                        {"symbol": "SPY", "change_pct": -1.4, "headline": "S&P 500 down", "material": True},
                        {"symbol": "VIXY", "change_pct": 5.2, "headline": "VIXY surged", "material": True},
                        {"symbol": "TLT", "change_pct": 0.3, "headline": "TLT flat", "material": False},
                        {"symbol": "GLD", "change_pct": 1.1, "headline": "Gold up", "material": True},
                        {"symbol": "XLK", "change_pct": -2.0, "headline": "Tech sold off", "material": True},
                    ],
                    "rates": [],
                }
            ),
            encoding="utf-8",
        )
        summary = collect_market(self.workspace, run_date=RUN_DATE, source=str(expanded_market))
        payload = load_json(Path(summary["raw_path"]), default={})
        events = payload.get("events", [])
        symbols = [e.get("security_id") for e in events]

        self.assertEqual(summary["event_count"], 5)
        self.assertIn("SPY", symbols)
        self.assertIn("VIXY", symbols)
        self.assertIn("GLD", symbols)
        self.assertIn("XLK", symbols)

    def test_normalize_news_events_filters_by_time(self) -> None:
        from datetime import datetime as _dt, timezone as _tz
        # Use timestamps relative to RUN_DATE so the 18h window works
        run_date_midnight = int(_dt.combine(RUN_DATE, _dt.min.time(), tzinfo=_tz.utc).timestamp())
        recent_ts = run_date_midnight + 6 * 3600  # 6 AM on run date
        old_ts = run_date_midnight - 24 * 3600  # 24 hours before run date (outside 18h window)

        news_items = [
            {"headline": "Recent headline", "datetime": recent_ts, "source": "Reuters", "url": "https://example.com/1"},
            {"headline": "Old headline", "datetime": old_ts, "source": "CNBC", "url": "https://example.com/2"},
            {"headline": "", "datetime": recent_ts, "source": "AP", "url": "https://example.com/3"},
        ]
        events = normalize_news_events(news_items, RUN_DATE)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], "Recent headline")
        self.assertEqual(events[0]["event_type"], "market-news")
        self.assertEqual(events[0]["news_source"], "Reuters")

    def test_normalize_company_news_events(self) -> None:
        from datetime import datetime as _dt, timezone as _tz
        run_date_midnight = int(_dt.combine(RUN_DATE, _dt.min.time(), tzinfo=_tz.utc).timestamp())
        recent_ts = run_date_midnight + 6 * 3600
        news_items = [
            {
                "headline": "GOOGL beats estimates",
                "datetime": recent_ts,
                "source": "SeekingAlpha",
                "url": "https://example.com/googl",
                "_security_id": "GOOGL",
                "_finnhub_symbol": "GOOGL",
            },
        ]
        events = normalize_company_news_events(news_items, RUN_DATE)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "company-news")
        self.assertEqual(events[0]["security_id"], "GOOGL")
        self.assertEqual(events[0]["relationship"], "monitored")

    def test_news_deduplication_in_prep(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
            watchlist_source=str(FIXTURE_DIR / "watchlist.json"),
        )
        # Create market data with duplicate news (same URL in both general and company news)
        market_data = {
            "indexes": [
                {"symbol": "SPY", "change_pct": -1.4, "headline": "SPY down", "material": True},
            ],
            "rates": [],
            "news": [
                {
                    "headline": "Duplicate article title",
                    "datetime": 9999999999,
                    "source": "Reuters",
                    "url": "https://example.com/dupe",
                    "summary": "Summary",
                },
            ],
            "company_news": [
                {
                    "headline": "Duplicate article title (company)",
                    "datetime": 9999999999,
                    "source": "Reuters",
                    "url": "https://example.com/dupe",
                    "_security_id": "NVDA",
                    "_finnhub_symbol": "NVDA",
                    "summary": "Summary",
                },
            ],
        }
        market_file = self.workspace / "market-with-news.json"
        market_file.write_text(json.dumps(market_data), encoding="utf-8")

        collect_filings(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "filings.json"))
        collect_earnings(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "market-data.json"))
        collect_macro(self.workspace, run_date=RUN_DATE, source=str(FIXTURE_DIR / "macro-events.json"))
        collect_ir(self.workspace, run_date=RUN_DATE, registry_path=self.workspace / "empty-ir.json")
        (self.workspace / "empty-ir.json").write_text("[]", encoding="utf-8")
        collect_market(self.workspace, run_date=RUN_DATE, source=str(market_file))

        summary = prepare_evidence(self.workspace, run_date=RUN_DATE)
        run_paths = ensure_daily_run_layout(self.workspace, RUN_DATE)
        prepared = load_json(run_paths.structured_dir / "prepared-evidence.json", default={})

        # The duplicate URL should be suppressed — only one news event with that URL
        all_news_urls = [
            e.get("reference_url")
            for e in prepared["events"]
            if e.get("event_type") in {"market-news", "company-news"} and e.get("reference_url")
        ]
        dupe_url_count = sum(1 for u in all_news_urls if u == "https://example.com/dupe")
        self.assertEqual(dupe_url_count, 1)

    def test_market_data_with_news_includes_news_events(self) -> None:
        import time as _time
        now_ts = int(_time.time())
        market_data = {
            "indexes": [
                {"symbol": "SPY", "change_pct": 0.5, "headline": "SPY flat", "material": False},
            ],
            "rates": [],
            "news": [
                {"headline": "Fed signals rate cuts", "datetime": now_ts, "source": "Reuters", "url": "https://example.com/fed"},
            ],
            "company_news": [
                {
                    "headline": "NVDA launches new chip",
                    "datetime": now_ts,
                    "source": "CNBC",
                    "url": "https://example.com/nvda",
                    "_security_id": "NVDA",
                    "_finnhub_symbol": "NVDA",
                },
            ],
        }
        market_file = self.workspace / "market-news.json"
        market_file.write_text(json.dumps(market_data), encoding="utf-8")

        summary = collect_market(self.workspace, run_date=RUN_DATE, source=str(market_file))
        payload = load_json(Path(summary["raw_path"]), default={})
        events = payload.get("events", [])

        event_types = {e["event_type"] for e in events}
        self.assertIn("market", event_types)
        self.assertIn("market-news", event_types)
        self.assertIn("company-news", event_types)
        self.assertEqual(summary["event_count"], 3)

    def test_normalize_security_row_passes_through_enrichment_fields(self) -> None:
        from harness.portfolio_state import _normalize_security_row
        row = {
            "ticker": "KPG",
            "company": "Kelly Partners Group",
            "exchange": "ASX",
            "country": "AU",
            "sec_registered": False,
            "finnhub_symbol": "KPG.AX",
        }
        result = _normalize_security_row(row, source_kind="holding")
        self.assertEqual(result["exchange"], "ASX")
        self.assertEqual(result["country"], "AU")
        self.assertEqual(result["sec_registered"], False)
        self.assertEqual(result["finnhub_symbol"], "KPG.AX")

    def test_normalize_security_row_omits_enrichment_when_absent(self) -> None:
        from harness.portfolio_state import _normalize_security_row
        row = {"ticker": "NVDA", "company": "NVIDIA Corp"}
        result = _normalize_security_row(row, source_kind="holding")
        self.assertNotIn("exchange", result)
        self.assertNotIn("country", result)
        self.assertNotIn("sec_registered", result)
        self.assertNotIn("finnhub_symbol", result)

    def test_enrich_preserves_already_enriched_records(self) -> None:
        sync_portfolio(
            self.workspace,
            as_of=RUN_DATE,
            holdings_source=str(FIXTURE_DIR / "holdings.csv"),
            transactions_source=str(FIXTURE_DIR / "transactions.csv"),
        )
        paths = self.workspace / "data" / "01-portfolio" / "current"
        holdings = [
            {
                "security_id": "GOOGL",
                "ticker": "GOOGL",
                "company_name": "Alphabet",
                "source_kind": "holding",
                "exchange": "NASDAQ",
                "country": "US",
                "sec_registered": True,
                "finnhub_symbol": "GOOGL",
            },
        ]
        write_json(paths / "holdings.json", holdings)
        write_json(paths / "watchlist.json", [])
        write_json(paths / "universe.json", holdings)

        summary = enrich_portfolio(self.workspace, finnhub_api_key=None)
        self.assertEqual(summary["skipped_count"], 1)
        self.assertEqual(summary["enriched_count"], 0)




if __name__ == "__main__":
    unittest.main()
