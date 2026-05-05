"""Tests for harness.cli chain parsing, dispatch, and help behavior."""

from pathlib import Path

from typer.testing import CliRunner

from harness.cli import app, dispatch_command, execute_chain, parse_chain
from harness.config import HarnessSettings

runner = CliRunner()


def test_parse_chain_respects_quoted_operators() -> None:
    parsed = parse_chain('sec 10k AAPL --items "1|1A" | extract "x && y" ; fileinfo ./tmp')
    assert [item.text for item in parsed] == ['sec 10k AAPL --items "1|1A"', 'extract "x && y"', "fileinfo ./tmp"]
    assert [item.operator for item in parsed] == ["|", ";", None]


def test_execute_chain_supports_semicolon_and_and_or(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\n", encoding="utf-8")

    result = execute_chain(f"fileinfo {sample} && fileinfo {sample}", settings)
    assert result.exit_code == 0
    assert "recommendation:" in result.stdout.decode("utf-8")

    fallback = execute_chain(f"fileinfo missing.txt || fileinfo {sample}", settings)
    assert fallback.exit_code == 0
    assert "type: file" in fallback.stdout.decode("utf-8")


def test_execute_chain_pipes_stdout_between_stages(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    monkeypatch.setattr(
        "harness.commands.sec.get_10k_items",
        lambda ticker, items: {"1A": "supply chain risk supply chain resilience risk"},
    )
    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda settings: None)

    result = execute_chain("sec 10k AAPL --items 1A | analyze ngrams --top 5 --min-count 1", settings)

    assert result.exit_code == 0
    output = result.stdout.decode("utf-8")
    assert "## Unigrams" in output
    assert "supply chain" in output


def test_dispatch_command_rejects_unknown_commands_without_subprocess(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)

    result = dispatch_command(["python3", "-c", "print('escape')"], settings=settings)

    assert result.exit_code == 1
    stderr = result.stderr.decode("utf-8")
    assert "unknown command `python3`" in stderr
    assert "Available alternatives:" in stderr


def test_direct_cli_missing_args_show_concise_error_for_valuation_dcf() -> None:
    result = runner.invoke(app, ["valuation", "dcf"])

    assert result.exit_code == 1
    assert "What went wrong:" in result.stdout
    assert "Usage:" not in result.stdout


def test_direct_cli_missing_args_show_full_help_for_research() -> None:
    """Bare 'minerva research' now shows clean help (exit 0, no error)."""
    result = runner.invoke(app, ["research"])

    assert result.exit_code == 0
    assert "What went wrong" not in result.stdout
    assert "Usage:" in result.stdout
    assert "Deep web research powered by Parallel.ai." in result.stdout
