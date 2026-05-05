"""Tests for extract and extract-files commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.commands import extract
from harness.config import HarnessSettings


# ---------------------------------------------------------------------------
# Phase 0 / 1 — `extract` core behavior
# ---------------------------------------------------------------------------


def test_extract_command_reads_file_and_calls_model(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("Revenue is $10M.", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "Revenue: $10M"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_command(question="What is revenue?", file_path=str(file_path), settings=settings)

    assert result.exit_code == 0
    assert result.stdout.decode("utf-8") == "Revenue: $10M"
    # The prompt sent to the model must contain the question.
    assert "What is revenue?" in captured["prompt"]
    assert "Revenue is $10M." in captured["prompt"]


def test_extract_command_reports_missing_input(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")

    result = extract.extract_command(question="What is revenue?", settings=settings)

    assert result.exit_code == 1
    assert b"no input" in result.stderr.lower() or b"input" in result.stderr.lower()


def test_extract_command_reports_missing_question(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")

    result = extract.extract_command(file_path=str(file_path), settings=settings)

    assert result.exit_code == 1
    assert b"question" in result.stderr.lower() or b"prompt" in result.stderr.lower()


def test_extract_command_does_not_read_stdin_when_file_provided(tmp_path: Path, monkeypatch) -> None:
    """When --file is provided, stdin must not contribute (or hang)."""
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("file content", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_command(
        question="Q",
        file_path=str(file_path),
        stdin=b"piped stdin",
        settings=settings,
    )

    assert result.exit_code == 0
    assert "file content" in captured["prompt"]
    assert "piped stdin" not in captured["prompt"]


def test_extract_command_passes_through_model_and_max_tokens(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    extract.extract_command(
        question="Q",
        file_path=str(file_path),
        model="gemini-2.5-pro",
        max_tokens=2048,
        settings=settings,
    )

    assert captured["model"] == "gemini-2.5-pro"
    assert captured["max_tokens"] == 2048


def test_extract_command_gpt55_uses_openai_key_without_gemini_key(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, openai_api_key="openai-test-key")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_command(
        question="Q",
        file_path=str(file_path),
        model="gpt-5.5",
        settings=settings,
    )

    assert result.exit_code == 0
    assert captured["api_key"] == "openai-test-key"
    assert captured["model"] == "gpt-5.5"


def test_extract_questions_file_preserves_markdown_formatting(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    questions_file = tmp_path / "questions.md"
    questions_file.write_text(
        "# Topics\n\n- Revenue by segment\n- Key risks\n\n## Notes\n\n1. Cite sections.\n2. Be concise.\n",
        encoding="utf-8",
    )
    file_path = tmp_path / "doc.md"
    file_path.write_text("Document body.", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_command(
        questions_file=str(questions_file),
        file_path=str(file_path),
        settings=settings,
    )

    assert result.exit_code == 0
    prompt = captured["prompt"]
    assert "# Topics" in prompt
    assert "- Revenue by segment" in prompt
    assert "- Key risks" in prompt
    assert "## Notes" in prompt
    assert "1. Cite sections." in prompt


def test_extract_combines_positional_and_questions_file_in_one_call(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    questions_file = tmp_path / "questions.md"
    questions_file.write_text("- Question A\n- Question B\n", encoding="utf-8")
    file_path = tmp_path / "doc.md"
    file_path.write_text("body", encoding="utf-8")
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_command(
        question="Inline question",
        questions_file=str(questions_file),
        file_path=str(file_path),
        settings=settings,
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    prompt = calls[0]["prompt"]
    assert "Inline question" in prompt
    assert "Question A" in prompt
    assert "Question B" in prompt


def test_extract_questions_file_empty_fails_cleanly(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    questions_file = tmp_path / "empty.md"
    questions_file.write_text("   \n\n", encoding="utf-8")
    file_path = tmp_path / "doc.md"
    file_path.write_text("body", encoding="utf-8")

    result = extract.extract_command(
        questions_file=str(questions_file),
        file_path=str(file_path),
        settings=settings,
    )

    assert result.exit_code == 1
    assert b"empty" in result.stderr.lower() or b"questions" in result.stderr.lower()


def test_extract_questions_file_missing_path_fails_cleanly(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.md"
    file_path.write_text("body", encoding="utf-8")

    result = extract.extract_command(
        questions_file=str(tmp_path / "does-not-exist.md"),
        file_path=str(file_path),
        settings=settings,
    )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Phase 2 — Thinking config helpers
# ---------------------------------------------------------------------------


def test_resolve_default_thinking_for_gemini_3_flash() -> None:
    assert extract._resolve_default_thinking("gemini-3-flash", None) == "minimal"
    assert extract._resolve_default_thinking("gemini-3-flash", "low") == "low"
    assert extract._resolve_default_thinking("gemini-3-pro", None) is None
    assert extract._resolve_default_thinking("gemini-2.5-pro", None) is None


def test_build_thinking_config_gemini_3_uses_thinking_level() -> None:
    cfg = extract._build_thinking_config("gemini-3-flash", "minimal")
    assert cfg is not None
    assert cfg.thinking_level == "MINIMAL"
    assert cfg.thinking_budget is None

    cfg_high = extract._build_thinking_config("gemini-3-pro", "high")
    assert cfg_high.thinking_level == "HIGH"
    assert cfg_high.thinking_budget is None


def test_build_thinking_config_gemini_3_rejects_off() -> None:
    with pytest.raises(ValueError):
        extract._build_thinking_config("gemini-3-flash", "off")


def test_build_thinking_config_gemini_25_uses_thinking_budget() -> None:
    cfg_off = extract._build_thinking_config("gemini-2.5-pro", "off")
    assert cfg_off.thinking_budget == 0
    assert cfg_off.thinking_level is None

    cfg_adaptive = extract._build_thinking_config("gemini-2.5-flash", "adaptive")
    assert cfg_adaptive.thinking_budget == -1
    assert cfg_adaptive.thinking_level is None


def test_build_thinking_config_gemini_25_rejects_levels() -> None:
    with pytest.raises(ValueError):
        extract._build_thinking_config("gemini-2.5-pro", "minimal")


def test_build_thinking_config_invalid_level_raises() -> None:
    with pytest.raises(ValueError):
        extract._build_thinking_config("gemini-3-flash", "nonsense")


def test_build_thinking_config_unknown_model_with_no_thinking_returns_none() -> None:
    assert extract._build_thinking_config("some-other-model", None) is None


def test_build_thinking_config_unknown_model_with_thinking_raises() -> None:
    with pytest.raises(ValueError):
        extract._build_thinking_config("some-other-model", "minimal")


def test_api_model_name_maps_user_facing_gemini_3_flash_alias() -> None:
    assert extract._api_model_name("gemini-3-flash") == "gemini-3-flash-preview"
    assert extract._api_model_name("gemini-3-flash-preview") == "gemini-3-flash-preview"


def test_api_model_name_maps_provider_qualified_openai_alias() -> None:
    assert extract._api_model_name("openai/gpt-5.5") == "gpt-5.5"
    assert extract._api_model_name("gpt-5.5") == "gpt-5.5"


def test_extract_command_default_thinking_for_gemini_3_flash(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.md"
    file_path.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    extract.extract_command(question="Q", file_path=str(file_path), settings=settings)

    assert captured["thinking"] == "minimal"


def test_extract_command_explicit_thinking_passes_through(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.md"
    file_path.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    extract.extract_command(
        question="Q",
        file_path=str(file_path),
        model="gemini-3-pro",
        thinking="high",
        settings=settings,
    )

    assert captured["thinking"] == "high"


def test_extract_command_invalid_thinking_returns_clean_error(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    file_path = tmp_path / "doc.md"
    file_path.write_text("body", encoding="utf-8")
    called = {"value": False}

    def fake_generate(**kwargs):
        called["value"] = True
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_command(
        question="Q",
        file_path=str(file_path),
        thinking="nonsense",
        settings=settings,
    )

    assert result.exit_code == 1
    assert called["value"] is False


# ---------------------------------------------------------------------------
# Phase 1/2 — `extract` run-chain dispatch
# ---------------------------------------------------------------------------


def test_dispatch_supports_questions_file_with_file(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    questions_file = tmp_path / "q.md"
    questions_file.write_text("- A\n- B\n", encoding="utf-8")
    source = tmp_path / "src.md"
    source.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch(
        ["--questions-file", str(questions_file), "--file", str(source)],
        settings=settings,
    )

    assert result.exit_code == 0
    assert "- A" in captured["prompt"]


def test_dispatch_supports_short_file_and_questions_flags(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    questions_file = tmp_path / "q.md"
    questions_file.write_text("Short question", encoding="utf-8")
    source = tmp_path / "src.md"
    source.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch(["-q", str(questions_file), "-f", str(source)], settings=settings)

    assert result.exit_code == 0
    assert "Short question" in captured["prompt"]


def test_dispatch_supports_flags_before_positional_question(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    source = tmp_path / "src.md"
    source.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch(
        ["--file", str(source), "--model", "gemini-3-flash", "What is X?"],
        settings=settings,
    )

    assert result.exit_code == 0
    assert "What is X?" in captured["prompt"]
    assert captured["model"] == "gemini-3-flash"


def test_dispatch_supports_thinking_flag(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    source = tmp_path / "src.md"
    source.write_text("body", encoding="utf-8")
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch(
        ["Q", "--file", str(source), "--model", "gemini-3-pro", "--thinking", "low"],
        settings=settings,
    )

    assert result.exit_code == 0
    assert captured["thinking"] == "low"


# ---------------------------------------------------------------------------
# Phase 4 — `extract-files`
# ---------------------------------------------------------------------------


def test_extract_files_requires_question_source(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    src = tmp_path / "src.md"
    src.write_text("body", encoding="utf-8")
    out = tmp_path / "out"

    result = extract.extract_files_command(
        files=[str(src)],
        out=str(out),
        settings=settings,
    )

    assert result.exit_code == 1
    assert b"question" in result.stderr.lower() or b"prompt" in result.stderr.lower()


def test_extract_files_requires_at_least_one_file(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    out = tmp_path / "out"

    result = extract.extract_files_command(
        question="Q",
        files=[],
        out=str(out),
        settings=settings,
    )

    assert result.exit_code == 1
    assert b"file" in result.stderr.lower()


def test_extract_files_glob_no_matches_fails(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    out = tmp_path / "out"

    result = extract.extract_files_command(
        question="Q",
        files=[str(tmp_path / "does-not-exist-*.md")],
        out=str(out),
        settings=settings,
    )

    assert result.exit_code == 1


def test_extract_files_one_call_per_file_writes_outputs(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "a.md").write_text("Alpha body.", encoding="utf-8")
    (sources / "b.md").write_text("Bravo body.", encoding="utf-8")
    out = tmp_path / "out"
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return f"answer for {kwargs['document_text'][:5]}"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_files_command(
        question="What is it?",
        files=[str(sources / "*.md")],
        out=str(out),
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code == 0, result.stderr.decode("utf-8")
    assert len(calls) == 2
    a_out = out / "a.md"
    b_out = out / "b.md"
    assert a_out.exists()
    assert b_out.exists()
    assert "answer for Alpha" in a_out.read_text(encoding="utf-8")
    assert "answer for Bravo" in b_out.read_text(encoding="utf-8")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 2
    assert all(entry["status"] == "ok" for entry in manifest["entries"])
    assert manifest["model"]
    assert manifest["api_model"]


def test_extract_files_questions_file_passes_pack(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    sources = tmp_path / "sources"
    sources.mkdir()
    src = sources / "doc.md"
    src.write_text("body", encoding="utf-8")
    qfile = tmp_path / "q.md"
    qfile.write_text("# Topics\n\n- Q1\n- Q2\n", encoding="utf-8")
    out = tmp_path / "out"
    captured: list[dict] = []

    def fake_generate(**kwargs):
        captured.append(kwargs)
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_files_command(
        questions_file=str(qfile),
        files=[str(src)],
        out=str(out),
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code == 0
    assert "# Topics" in captured[0]["prompt"]
    assert "- Q1" in captured[0]["prompt"]


def test_extract_files_force_required_to_overwrite(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    sources = tmp_path / "sources"
    sources.mkdir()
    src = sources / "a.md"
    src.write_text("body", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.md").write_text("preexisting", encoding="utf-8")

    monkeypatch.setattr("harness.commands.extract._generate_answer", lambda **kw: "answer")

    # Without --force: failure, output preserved
    result = extract.extract_files_command(
        question="Q",
        files=[str(src)],
        out=str(out),
        concurrency=1,
        settings=settings,
    )
    assert result.exit_code == 1
    assert (out / "a.md").read_text(encoding="utf-8") == "preexisting"

    # With --force: overwrite
    result_force = extract.extract_files_command(
        question="Q",
        files=[str(src)],
        out=str(out),
        concurrency=1,
        force=True,
        settings=settings,
    )
    assert result_force.exit_code == 0
    assert "answer" in (out / "a.md").read_text(encoding="utf-8")


def test_extract_files_partial_failure_writes_manifest_and_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "good.md").write_text("ok body", encoding="utf-8")
    (sources / "bad.md").write_text("bad body", encoding="utf-8")
    out = tmp_path / "out"

    def fake_generate(**kwargs):
        if "bad" in kwargs["document_text"]:
            raise RuntimeError("boom")
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_files_command(
        question="Q",
        files=[str(sources / "*.md")],
        out=str(out),
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code != 0
    assert (out / "good.md").exists()
    assert not (out / "bad.md").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    statuses = {entry["source"]: entry["status"] for entry in manifest["entries"]}
    assert any(status == "ok" for status in statuses.values())
    assert any(status == "error" for status in statuses.values())


def test_extract_files_passes_model_thinking_max_tokens(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "a.md").write_text("body", encoding="utf-8")
    out = tmp_path / "out"
    captured: list[dict] = []

    def fake_generate(**kwargs):
        captured.append(kwargs)
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    extract.extract_files_command(
        question="Q",
        files=[str(sources / "*.md")],
        out=str(out),
        model="gemini-3-pro",
        thinking="medium",
        max_tokens=1024,
        concurrency=1,
        settings=settings,
    )

    assert captured[0]["model"] == "gemini-3-pro"
    assert captured[0]["thinking"] == "medium"
    assert captured[0]["max_tokens"] == 1024


def test_extract_files_gpt55_uses_openai_key_without_gemini_key(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, openai_api_key="openai-test-key")
    src = tmp_path / "source.md"
    src.write_text("body", encoding="utf-8")
    out = tmp_path / "out"
    captured: list[dict] = []

    def fake_generate(**kwargs):
        captured.append(kwargs)
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_files_command(
        question="Q",
        files=[str(src)],
        out=str(out),
        model="gpt-5.5",
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code == 0, result.stderr.decode("utf-8")
    assert captured[0]["model"] == "gpt-5.5"
    assert captured[0]["api_key"] == "openai-test-key"
    assert captured[0]["thinking"] is None
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model"] == "gpt-5.5"
    assert manifest["api_model"] == "gpt-5.5"


def test_extract_files_gpt55_reports_missing_openai_key(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="gemini-test-key")
    src = tmp_path / "source.md"
    src.write_text("body", encoding="utf-8")

    result = extract.extract_files_command(
        question="Q",
        files=[str(src)],
        out=str(tmp_path / "out"),
        model="gpt-5.5",
        settings=settings,
    )

    assert result.exit_code == 1
    assert b"OPENAI_API_KEY" in result.stderr


def test_generate_openai_answer_uses_responses_api(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)

            class Response:
                output_text = "openai answer"

            return Response()

    class FakeClient:
        def __init__(self, *, api_key: str):
            captured["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeClient)

    answer = extract._generate_openai_answer(
        prompt="prompt",
        model="openai/gpt-5.5",
        max_tokens=123,
        api_key="key",
    )

    assert answer == "openai answer"
    assert captured["api_key"] == "key"
    assert captured["model"] == "gpt-5.5"
    assert captured["input"] == "prompt"
    assert captured["max_output_tokens"] == 123


def test_extract_files_mirrors_relative_paths(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    sources = tmp_path / "sources"
    (sources / "10-K").mkdir(parents=True)
    (sources / "10-K" / "item-1.md").write_text("a", encoding="utf-8")
    (sources / "10-Q").mkdir(parents=True)
    (sources / "10-Q" / "item-1.md").write_text("b", encoding="utf-8")
    out = tmp_path / "out"

    monkeypatch.setattr("harness.commands.extract._generate_answer", lambda **kw: "ans")

    result = extract.extract_files_command(
        question="Q",
        files=[str(sources / "**" / "*.md")],
        out=str(out),
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code == 0
    # Common parent is `sources/`; the two distinct subdirs are preserved so basenames don't collide.
    assert (out / "10-K" / "item-1.md").exists()
    assert (out / "10-Q" / "item-1.md").exists()


def test_extract_files_dispatch_supports_repeated_files(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("bravo", encoding="utf-8")
    out = tmp_path / "out"
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch_files(
        [
            "Q",
            "--files", str(a),
            "--files", str(b),
            "--out", str(out),
            "--concurrency", "1",
        ],
        settings=settings,
    )

    assert result.exit_code == 0
    assert len(calls) == 2


def test_extract_files_dispatch_supports_short_flags(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    qfile = tmp_path / "questions.md"
    qfile.write_text("Q", encoding="utf-8")
    out = tmp_path / "out"
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch_files(
        ["-q", str(qfile), "-f", str(a), "-o", str(out), "--concurrency", "1"],
        settings=settings,
    )

    assert result.exit_code == 0
    assert len(calls) == 1


def test_extract_files_dispatch_supports_short_files_from(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="test-key")
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    list_file = tmp_path / "files.txt"
    list_file.write_text("a.md\n", encoding="utf-8")
    out = tmp_path / "out"
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.dispatch_files(["Q", "-F", str(list_file), "-o", str(out), "--concurrency", "1"], settings=settings)

    assert result.exit_code == 0
    assert len(calls) == 1


def test_extract_files_supports_files_from_for_curated_scattered_files(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="***")
    root = tmp_path / "reports"
    oracle = root / "oracle" / "data"
    microsoft = root / "microsoft" / "filings"
    amazon = root / "amazon" / "sources"
    oracle.mkdir(parents=True)
    microsoft.mkdir(parents=True)
    amazon.mkdir(parents=True)
    (oracle / "file-a.md").write_text("oracle", encoding="utf-8")
    (microsoft / "file-b.md").write_text("microsoft", encoding="utf-8")
    (amazon / "file-c.md").write_text("amazon", encoding="utf-8")
    list_file = tmp_path / "files.txt"
    list_file.write_text(
        "# curated cross-company extraction\n"
        "reports/oracle/data/file-a.md\n"
        "reports/microsoft/filings/file-b.md\n"
        "reports/amazon/sources/file-c.md\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return f"answer: {kwargs['document_text']}"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_files_command(
        question="Q",
        files_from=str(list_file),
        out=str(out),
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code == 0, result.stderr.decode("utf-8")
    assert len(calls) == 3
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    sources = {Path(entry["source"]).name for entry in manifest["entries"]}
    assert sources == {"file-a.md", "file-b.md", "file-c.md"}


def test_extract_files_cli_accepts_files_from_without_files(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="***")
    src = tmp_path / "source.md"
    src.write_text("body", encoding="utf-8")
    qfile = tmp_path / "questions.md"
    qfile.write_text("Q", encoding="utf-8")
    list_file = tmp_path / "files.txt"
    list_file.write_text("source.md\n", encoding="utf-8")
    out = tmp_path / "out"
    captured: dict = {}

    def fake_command(**kwargs):
        captured.update(kwargs)
        return extract.CommandResult.from_text("ok")

    monkeypatch.setattr("harness.commands.extract.extract_files_command", fake_command)
    monkeypatch.setattr("harness.commands.extract.get_settings", lambda: settings)

    extract.extract_files_cli_command(
        ctx=None,  # only used for validation failures
        question=None,
        files=None,
        files_from=str(list_file),
        out=str(out),
        questions_file=str(qfile),
    )

    assert captured["files"] == []
    assert captured["files_from"] == str(list_file)


def test_extract_files_records_non_text_files_as_failures(tmp_path: Path, monkeypatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="***")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "good.md").write_text("ok body", encoding="utf-8")
    (sources / "report.pdf").write_bytes(b"%PDF-1.7 fake pdf")
    out = tmp_path / "out"
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return "answer"

    monkeypatch.setattr("harness.commands.extract._generate_answer", fake_generate)

    result = extract.extract_files_command(
        question="Q",
        files=[str(sources / "good.md"), str(sources / "report.pdf")],
        out=str(out),
        concurrency=1,
        settings=settings,
    )

    assert result.exit_code == 1
    assert len(calls) == 1
    assert (out / "good.md").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    pdf_entry = next(entry for entry in manifest["entries"] if entry["source"].endswith("report.pdf"))
    assert pdf_entry["status"] == "error"
    assert "unsupported non-text" in pdf_entry["error"]


# ---------------------------------------------------------------------------
# Phase 3 — legacy multi-question command removal
# ---------------------------------------------------------------------------


def test_extract_module_no_longer_exposes_extract_many() -> None:
    assert not hasattr(extract, "extract_many_command")
    assert not hasattr(extract, "extract_many_app")
    assert not hasattr(extract, "dispatch_many")
