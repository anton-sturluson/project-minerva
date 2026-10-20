"""Contract coverage for the model-driven morning-brief stages."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = REPO_ROOT / "scripts" / "prompts"


def _read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def test_final_writer_does_not_restart_collection() -> None:
    synthesis = _read_prompt("morning_brief_synthesis.md")
    assert "Do not run `scripts/run_morning_brief.sh` or `portfolio sync`" in synthesis
    assert "the collection script wrote it before starting this agent" in synthesis


def test_collector_uses_luna_with_high_reasoning() -> None:
    runner = (REPO_ROOT / "scripts" / "run_morning_brief.sh").read_text(
        encoding="utf-8"
    )

    assert "--model openai/gpt-5.6-luna" in runner
    assert "--thinking high" in runner
    assert "fireworks/accounts/fireworks/routers/glm-5p2-fast" not in runner


def test_selection_uses_sol61_and_keeps_premium_sources_separate() -> None:
    synthesis = _read_prompt("morning_brief_synthesis.md")
    selection = synthesis.split("## 3.", 1)[1].split("## 4.", 1)[0]

    assert "--model gpt-6.1-sol" in selection
    assert "--thinking high" in selection
    assert "Terra" not in synthesis and "gpt-5.6-terra" not in synthesis
    assert "summarize --model gpt-5.6-luna --thinking medium" in synthesis
    assert "whose `source` is not exactly `wsj` or `economist`" in selection
    assert "whose `source` is exactly `wsj` or `economist`" in selection
    assert "Do not include those premium-source rows in the selection model's batch inputs." in selection
    assert "eligible for final main-agent review, not guaranteed publication" in selection


def test_worth_knowing_contract_covers_approved_long_term_developments() -> None:
    synthesis = _read_prompt("morning_brief_synthesis.md")

    assert "up to 10 distinct, evidence-backed non-portfolio developments" in synthesis
    assert "useful to a long-term investor" in synthesis
    for shift in (
        "business",
        "technological",
        "social",
        "demographic",
        "labor",
        "institutional",
        "resource",
    ):
        assert shift in synthesis
    for effect in ("demand", "productivity", "costs", "incentives", "risk"):
        assert effect in synthesis
    assert "Exclude Political / Macro events" in synthesis
    assert "never add filler" in synthesis


def test_political_macro_contract_is_last_limited_and_event_driven() -> None:
    synthesis = _read_prompt("morning_brief_synthesis.md")
    output_contract = synthesis.split("```text\n", 1)[1].split("\n```", 1)[0]
    section_lines = [
        line for line in output_contract.splitlines() if line.startswith("_")
    ]

    assert section_lines[-1] == "_Political / Macro_"
    assert "up to five distinct, evidence-backed event-driven developments" in synthesis
    for outlook in (
        "growth",
        "inflation",
        "rates",
        "trade",
        "regulation",
        "resource supply",
        "geopolitical tail risk",
    ):
        assert outlook in synthesis
    assert "Exclude routine political activity" in synthesis
    assert "do not duplicate any development from `_Worth Knowing Today_`" in synthesis


def test_synthesis_deduplicates_coverage_by_evidence_quality() -> None:
    synthesis = _read_prompt("morning_brief_synthesis.md")

    assert "Deduplicate overlapping coverage" in synthesis
    assert "strongest original evidence or incremental insight" in synthesis


def test_evidence_backed_durable_shift_guidance_reaches_each_editorial_gate() -> None:
    for name in (
        "collect_news.md",
        "morning_brief_selection.md",
        "morning_brief_synthesis.md",
    ):
        prompt = _read_prompt(name)
        assert "evidence-backed" in prompt
        assert "business, technological, social, demographic, labor, institutional" in prompt
        assert "resource shifts" in prompt
        assert "materially reshape demand, productivity, costs, incentives, or risk" in prompt
