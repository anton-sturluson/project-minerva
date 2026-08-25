"""Contract coverage for the model-driven morning-brief stages."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = REPO_ROOT / "scripts" / "prompts"


def test_collector_uses_luna_with_xhigh_reasoning() -> None:
    runner = (REPO_ROOT / "scripts" / "run_morning_brief.sh").read_text()

    assert "--model openai/gpt-5.6-luna" in runner
    assert "--thinking xhigh" in runner
    assert "fireworks/accounts/fireworks/routers/glm-5p2-fast" not in runner


def test_terra_uses_high_reasoning_and_excludes_premium_sources() -> None:
    synthesis = (PROMPT_DIR / "morning_brief_synthesis.md").read_text()

    assert "--model gpt-5.6-terra" in synthesis
    assert "--thinking high" in synthesis
    assert "whose `source` is not exactly `wsj` or `economist`" in synthesis
    assert "Do not include those premium-source rows in Terra's batch inputs." in synthesis
    assert "auto-advanced-keys.jsonl" in synthesis
    assert "Union those keys" in synthesis
    assert "eligible for final main-agent review, not guaranteed publication" in synthesis


def test_final_sections_keep_political_macro_last_and_exclusive() -> None:
    synthesis = (PROMPT_DIR / "morning_brief_synthesis.md").read_text()

    portfolio = synthesis.index("_Portfolio / Watchlist Events_")
    worth = synthesis.index("_Worth Knowing Today_", portfolio)
    political_macro = synthesis.index("_Political / Macro_", worth)

    assert portfolio < worth < political_macro
    assert "must not also appear in `_Worth Knowing Today_`" in synthesis
    assert "Deduplicate developments and source URLs across both sections." in synthesis
    assert "No qualifying political or macro developments" in synthesis


def test_durable_shift_guidance_exists_at_all_editorial_gates() -> None:
    guidance = (
        "durable social, demographic, labor, cultural, institutional, and resource shifts"
    )
    for name in (
        "collect_news.md",
        "morning_brief_selection.md",
        "morning_brief_synthesis.md",
    ):
        assert guidance in (PROMPT_DIR / name).read_text()
