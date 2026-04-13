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

from harness.commands import brief
from harness.config import HarnessSettings
from harness.morning_brief import (
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
    prepare_evidence,
)
from harness.portfolio_state import (
    add_adjacency_entry,
    load_json,
    set_thesis_card,
    sync_portfolio,
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
        thesis = set_thesis_card(
            self.workspace,
            security="NVDA",
            summary="AI demand remains the core portfolio driver.",
            expectations=["Blackwell ramps", "Networking attach stays elevated"],
            disconfirming_signals=["Cloud capex slows materially"],
        )

        self.assertEqual(summary["holdings_count"], 2)
        self.assertEqual(summary["watchlist_count"], 2)
        self.assertEqual(summary["universe_count"], 4)
        self.assertEqual(adjacency["adjacent"], "TSM")
        self.assertEqual(thesis["security_id"], "NVDA")

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
        set_thesis_card(
            self.workspace,
            security="NVDA",
            summary="AI demand remains the core portfolio driver.",
            expectations=["Blackwell ramps"],
            disconfirming_signals=["Cloud capex slows materially"],
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
        workspace_root = self.workspace / "workspace"
        call_log = self.workspace / "calls.log"
        fake_minerva = self.workspace / "fake-minerva.sh"
        fake_minerva.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$MINERVA_CALL_LOG\"\n",
            encoding="utf-8",
        )
        fake_minerva.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "MINERVA_CALL_LOG": str(call_log),
                "MINERVA_RUNNER": str(fake_minerva),
                "MINERVA_SKIP_STATUS_CHECK": "1",
                "MINERVA_WITH_POST_WRITE": "1",
                "MINERVA_WORKSPACE_ROOT": str(workspace_root),
                "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": str(FIXTURE_DIR / "holdings.csv"),
                "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": str(FIXTURE_DIR / "transactions.csv"),
                "MINERVA_PORTFOLIO_WATCHLIST_SOURCE": str(FIXTURE_DIR / "watchlist.json"),
                "MINERVA_BRIEF_FILINGS_SOURCE": str(FIXTURE_DIR / "filings.json"),
                "MINERVA_BRIEF_EARNINGS_SOURCE": str(FIXTURE_DIR / "market-data.json"),
                "MINERVA_BRIEF_MACRO_SOURCE": str(FIXTURE_DIR / "macro-events.json"),
                "MINERVA_BRIEF_IR_REGISTRY": str(self.workspace / "ir-registry.json"),
                "MINERVA_BRIEF_MARKET_SOURCE": str(FIXTURE_DIR / "market-data.json"),
            }
        )
        Path(env["MINERVA_BRIEF_IR_REGISTRY"]).write_text("[]\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "run_morning_brief_v1.sh"), RUN_DATE.isoformat()],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"prepared_evidence: {workspace_root}/reports/03-daily-news/{RUN_DATE.isoformat()}/data/structured/prepared-evidence.json",
            result.stdout,
        )
        self.assertIn(
            f"manifest: {workspace_root}/reports/03-daily-news/{RUN_DATE.isoformat()}/data/raw/manifest.json",
            result.stdout,
        )
        self.assertTrue((workspace_root / "reports" / "03-daily-news" / RUN_DATE.isoformat()).is_dir())
        self.assertEqual(
            call_log.read_text(encoding="utf-8").splitlines(),
            [
                f"portfolio sync --date {RUN_DATE.isoformat()} --holdings-source {FIXTURE_DIR / 'holdings.csv'} --transactions-source {FIXTURE_DIR / 'transactions.csv'} --watchlist-source {FIXTURE_DIR / 'watchlist.json'}",
                f"brief filings --date {RUN_DATE.isoformat()} --source {FIXTURE_DIR / 'filings.json'}",
                f"brief earnings --date {RUN_DATE.isoformat()} --provider auto --source {FIXTURE_DIR / 'market-data.json'}",
                f"brief macro --date {RUN_DATE.isoformat()} --registry {workspace_root / 'data' / '01-portfolio' / 'current' / 'macro-registry.json'} --source {FIXTURE_DIR / 'macro-events.json'}",
                f"brief ir --date {RUN_DATE.isoformat()} --registry {self.workspace / 'ir-registry.json'}",
                f"brief market --date {RUN_DATE.isoformat()} --provider auto --source {FIXTURE_DIR / 'market-data.json'}",
                f"brief prep --date {RUN_DATE.isoformat()}",
                f"brief audit --date {RUN_DATE.isoformat()}",
                f"brief review-log --date {RUN_DATE.isoformat()}",
            ],
        )

    def test_wrapper_runs_macro_collect_when_no_macro_source_is_provided(self) -> None:
        workspace_root = self.workspace / "workspace"
        call_log = self.workspace / "calls.log"
        fake_minerva = self.workspace / "fake-minerva.sh"
        fake_minerva.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$MINERVA_CALL_LOG\"\n",
            encoding="utf-8",
        )
        fake_minerva.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "MINERVA_CALL_LOG": str(call_log),
                "MINERVA_RUNNER": str(fake_minerva),
                "MINERVA_SKIP_STATUS_CHECK": "1",
                "MINERVA_WORKSPACE_ROOT": str(workspace_root),
                "MINERVA_PORTFOLIO_HOLDINGS_SOURCE": str(FIXTURE_DIR / "holdings.csv"),
                "MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE": str(FIXTURE_DIR / "transactions.csv"),
                "MINERVA_PORTFOLIO_WATCHLIST_SOURCE": str(FIXTURE_DIR / "watchlist.json"),
                "MINERVA_BRIEF_FILINGS_SOURCE": str(FIXTURE_DIR / "filings.json"),
                "MINERVA_BRIEF_EARNINGS_SOURCE": str(FIXTURE_DIR / "market-data.json"),
                "MINERVA_BRIEF_MARKET_SOURCE": str(FIXTURE_DIR / "market-data.json"),
            }
        )

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "run_morning_brief_v1.sh"), RUN_DATE.isoformat()],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        generated_source = workspace_root / "reports" / "03-daily-news" / RUN_DATE.isoformat() / "data" / "raw" / "macro-events.json"
        self.assertIn(
            f"brief macro-collect --date {RUN_DATE.isoformat()} --registry {workspace_root / 'data' / '01-portfolio' / 'current' / 'macro-registry.json'} --output {generated_source}",
            call_log.read_text(encoding="utf-8"),
        )
        self.assertIn(
            f"brief macro --date {RUN_DATE.isoformat()} --registry {workspace_root / 'data' / '01-portfolio' / 'current' / 'macro-registry.json'} --source {generated_source}",
            call_log.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
