"""Tests for harness.output."""

from pathlib import Path

from harness.output import CommandResult, OutputEnvelope


def test_output_envelope_includes_footer(tmp_path: Path) -> None:
    result = CommandResult.from_text("hello", duration_ms=12)
    rendered: str = OutputEnvelope.from_result(result, workspace_root=tmp_path).render()
    assert "hello" in rendered
    assert "[exit:0 | 12ms]" in rendered


def test_output_envelope_attaches_stderr_on_failure(tmp_path: Path) -> None:
    result = CommandResult.from_text("", stderr="failed badly", exit_code=2, duration_ms=1)
    rendered: str = OutputEnvelope.from_result(result, workspace_root=tmp_path).render()
    assert "failed badly" in rendered
    assert "[exit:2 | 1ms]" in rendered


def test_output_envelope_handles_binary_stdout(tmp_path: Path) -> None:
    result = CommandResult(stdout=b"\x00\x01\x02", exit_code=0, duration_ms=3)
    rendered: str = OutputEnvelope.from_result(result, workspace_root=tmp_path).render()
    assert "Binary output detected" in rendered
    assert "[exit:0 | 3ms]" in rendered


def test_output_envelope_truncates_large_output_and_writes_temp_file(tmp_path: Path) -> None:
    text: str = "\n".join(f"line {index}" for index in range(250))
    result = CommandResult.from_text(text, duration_ms=8)
    envelope = OutputEnvelope.from_result(result, workspace_root=tmp_path)
    rendered: str = envelope.render()
    assert "[truncated] Full output saved to" in rendered
    assert envelope.full_output_path is not None
    assert envelope.full_output_path.exists()
