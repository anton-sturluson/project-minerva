"""Integration tests for portfolio thesis card v2 state."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.portfolio_state import (
    add_thesis_metric,
    get_thesis_by_ticker,
    load_json,
    set_thesis_card,
    write_json,
)


class ThesisCardV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_thesis_card_lifecycle(self) -> None:
        card = set_thesis_card(
            self.workspace,
            card_id="gtlb-devsecops",
            ticker_symbols=["gtlb"],
            summary="GitLab keeps consolidating DevSecOps workflows.",
            core_thesis=["Single application expands seats", "AI features support pricing"],
            signals=["NRR stabilizes", "FCF margin expands"],
        )

        cards_path = self.workspace / "data" / "01-portfolio" / "current" / "thesis-cards.json"
        rendered_path = self.workspace / "data" / "01-portfolio" / "current" / "thesis-cards.md"
        cards = load_json(cards_path, default=[])

        self.assertEqual(card["card_id"], "gtlb-devsecops")
        self.assertEqual(cards[0]["card_id"], "gtlb-devsecops")
        self.assertEqual(cards[0]["ticker_symbols"], ["GTLB"])
        self.assertEqual(cards[0]["summary"], "GitLab keeps consolidating DevSecOps workflows.")
        self.assertEqual(cards[0]["core_thesis"], ["Single application expands seats", "AI features support pricing"])
        self.assertEqual(cards[0]["signals"], ["NRR stabilizes", "FCF margin expands"])
        self.assertEqual(cards[0]["key_metrics"], [])

        set_thesis_card(
            self.workspace,
            card_id="gtlb-devsecops",
            ticker_symbols=["GTLB"],
            summary="GitLab remains a durable DevSecOps compounder.",
            core_thesis=["Platform consolidation wins budgets"],
            signals=["Enterprise seat growth"],
        )
        cards = load_json(cards_path, default=[])
        self.assertEqual(cards[0]["summary"], "GitLab remains a durable DevSecOps compounder.")
        self.assertEqual(cards[0]["core_thesis"], ["Platform consolidation wins budgets"])
        self.assertEqual(cards[0]["signals"], ["Enterprise seat growth"])
        self.assertEqual(cards[0]["key_metrics"], [])

        add_thesis_metric(
            self.workspace,
            card_id="gtlb-devsecops",
            name="NRR",
            unit="%",
            period="Q1 FY2027",
            value="116%",
            date="2026-06-02",
            source="earnings call",
        )
        add_thesis_metric(
            self.workspace,
            card_id="gtlb-devsecops",
            name="FCF margin",
            unit="%",
            period="FY2027",
            value="20-22%",
            date=None,
            source="company guidance",
        )
        cards = load_json(cards_path, default=[])
        metrics = {metric["name"]: metric for metric in cards[0]["key_metrics"]}
        self.assertEqual(metrics["NRR"]["observations"][0]["value"], "116%")
        self.assertEqual(metrics["FCF margin"]["observations"][0]["period"], "FY2027")

        set_thesis_card(
            self.workspace,
            card_id="gtlb-devsecops",
            ticker_symbols=["GTLB"],
            summary="Updated pitch while preserving evidence.",
            core_thesis=["Large installed base"],
            signals=["NRR above peer median"],
        )
        cards = load_json(cards_path, default=[])
        self.assertEqual(cards[0]["summary"], "Updated pitch while preserving evidence.")
        self.assertEqual(len(cards[0]["key_metrics"]), 2)
        self.assertEqual(cards[0]["key_metrics"][0]["observations"][0]["period"], "Q1 FY2027")

        rendered = rendered_path.read_text(encoding="utf-8")
        self.assertIn("## gtlb-devsecops", rendered)
        self.assertIn("### Metrics", rendered)
        self.assertIn("| Period | Date | Value | Source |", rendered)
        self.assertIn("| Q1 FY2027 | 2026-06-02 | 116% | earnings call |", rendered)

    def test_thesis_by_ticker_cross_card(self) -> None:
        set_thesis_card(
            self.workspace,
            card_id="gtlb",
            ticker_symbols=["GTLB"],
            summary="GitLab thesis",
            core_thesis=[],
            signals=[],
        )
        set_thesis_card(
            self.workspace,
            card_id="memory-hbm",
            ticker_symbols=["MU", "SK-HYNIX"],
            summary="HBM supply-demand stays tight",
            core_thesis=[],
            signals=[],
        )
        set_thesis_card(
            self.workspace,
            card_id="mu-specific",
            ticker_symbols=["MU"],
            summary="Micron execution improves",
            core_thesis=[],
            signals=[],
        )

        self.assertEqual({card["card_id"] for card in get_thesis_by_ticker(self.workspace, ticker="MU")}, {"memory-hbm", "mu-specific"})
        self.assertEqual([card["card_id"] for card in get_thesis_by_ticker(self.workspace, ticker="GTLB")], ["gtlb"])
        self.assertEqual(get_thesis_by_ticker(self.workspace, ticker="AAPL"), [])

    def test_thesis_metric_validation_and_caps(self) -> None:
        set_thesis_card(
            self.workspace,
            card_id="gtlb",
            ticker_symbols=["GTLB"],
            summary="GitLab thesis",
            core_thesis=[],
            signals=[],
        )

        add_thesis_metric(
            self.workspace,
            card_id="gtlb",
            name="NRR",
            unit="%",
            period="Q1 FY2027",
            value="116%",
            date=None,
            source=None,
        )
        with self.assertRaisesRegex(ValueError, r"FY2026.*Q1 FY2026"):
            add_thesis_metric(
                self.workspace,
                card_id="gtlb",
                name="NRR",
                unit="%",
                period="2026 Q1",
                value="116%",
                date=None,
                source=None,
            )

        for metric_name in ["Revenue", "RPO", "FCF margin", "Rule of 40"]:
            add_thesis_metric(
                self.workspace,
                card_id="gtlb",
                name=metric_name,
                unit=None,
                period="FY2027",
                value="not disclosed",
                date=None,
                source=None,
            )
        with self.assertRaisesRegex(ValueError, r"maximum of 5 key metrics"):
            add_thesis_metric(
                self.workspace,
                card_id="gtlb",
                name="Customers",
                unit=None,
                period="FY2027",
                value="10,000+",
                date=None,
                source=None,
            )

        add_thesis_metric(
            self.workspace,
            card_id="gtlb",
            name="NRR",
            unit="%",
            period="Q2 FY2027",
            value="117%",
            date="2026-09-01",
            source="earnings call",
        )
        cards = load_json(self.workspace / "data" / "01-portfolio" / "current" / "thesis-cards.json", default=[])
        nrr = next(metric for metric in cards[0]["key_metrics"] if metric["name"] == "NRR")
        self.assertEqual([observation["period"] for observation in nrr["observations"]], ["Q1 FY2027", "Q2 FY2027"])

    def test_thesis_set_preserves_metrics_and_backs_up_old_schema(self) -> None:
        current_dir = self.workspace / "data" / "01-portfolio" / "current"
        current_dir.mkdir(parents=True, exist_ok=True)
        old_cards = [
            {
                "security_id": "GTLB",
                "thesis_summary": "Old pitch",
                "key_expectations": ["Old expectation"],
                "disconfirming_signals": ["Old signal"],
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        write_json(current_dir / "thesis-cards.json", old_cards)

        card = set_thesis_card(
            self.workspace,
            card_id="gtlb",
            ticker_symbols=["GTLB"],
            summary="New pitch",
            core_thesis=["New thesis"],
            signals=["New signal"],
        )

        backups = sorted((self.workspace / "data" / "01-portfolio" / "backups").glob("thesis-cards-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(load_json(backups[0], default=[]), old_cards)
        self.assertEqual(card["card_id"], "gtlb")
        self.assertNotIn("security_id", card)
        self.assertEqual(card["ticker_symbols"], ["GTLB"])
        self.assertEqual(card["summary"], "New pitch")



if __name__ == "__main__":
    unittest.main()
