"""Extraction workflow over saved evidence sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import harness.commands.extract as extract_commands
from harness.config import HarnessSettings
from harness.workflows.evidence.inventory import run_inventory
from harness.workflows.evidence.paths import CompanyPaths
from harness.workflows.evidence.profiles import load_extract_profile
from harness.workflows.evidence.ledger import load_ledger, utc_now
from harness.workflows.evidence.render import refresh_indexes, render_extraction_run_markdown, write_json


def run_extraction(
    paths: CompanyPaths,
    *,
    profile_name: str,
    source_prefix: str | None,
    match: str | None,
    force: bool,
    model: str,
    settings: HarnessSettings,
) -> dict[str, Any]:
    """Extract structured outputs for matched local sources."""
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    profile = load_extract_profile(profile_name)
    categories = profile.get("categories", {})
    if not isinstance(categories, dict) or not categories:
        raise ValueError(f"extract profile `{profile_name}` has no categories")

    matches: list[dict[str, Any]] = []
    for entry in load_ledger(paths):
        if entry["status"] != "downloaded" or not entry.get("local_path"):
            continue
        if entry["category"] not in categories:
            continue
        if source_prefix and not str(entry["local_path"]).startswith(source_prefix):
            continue
        if match and match.lower() not in _match_text(entry).lower():
            continue
        if not _resolve_local_file(paths, entry["local_path"]).exists():
            continue
        matches.append(entry)

    if not matches:
        raise ValueError("no downloaded sources matched the requested extraction filters")

    artifacts: list[dict[str, Any]] = []
    processed_count = 0
    skipped_existing_count = 0
    for entry in matches:
        output_base = structured_output_base(paths, entry)
        json_path = output_base.with_suffix(".json")
        markdown_path = output_base.with_suffix(".md")
        if not force and json_path.exists() and markdown_path.exists():
            skipped_existing_count += 1
            artifacts.append(
                {
                    "source_id": entry["id"],
                    "status": "skipped-existing",
                    "structured_json": str(json_path.relative_to(paths.root)),
                    "structured_markdown": str(markdown_path.relative_to(paths.root)),
                }
            )
            continue

        file_text = _read_source_text(paths, entry["local_path"])
        qa_items = categories[entry["category"]].get("questions", [])
        if not qa_items:
            continue
        answers = _extract_answers(
            qa_items=qa_items,
            document_text=file_text,
            model=model,
            api_key=settings.gemini_api_key,
        )
        payload = {
            "profile": profile_name,
            "source": {
                "id": entry["id"],
                "title": entry["title"],
                "ticker": entry["ticker"],
                "category": entry["category"],
                "local_path": entry["local_path"],
                "url": entry.get("url"),
            },
            "questions": answers,
            "created_at": utc_now(),
            "model": model,
        }
        markdown_text = _render_extracted_markdown(payload)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(json_path, payload)
        markdown_path.write_text(markdown_text + "\n", encoding="utf-8")
        artifacts.append(
            {
                "source_id": entry["id"],
                "status": "processed",
                "structured_json": str(json_path.relative_to(paths.root)),
                "structured_markdown": str(markdown_path.relative_to(paths.root)),
            }
        )
        processed_count += 1

    run = {
        "profile": profile_name,
        "model": model,
        "matched_count": len(matches),
        "processed_count": processed_count,
        "skipped_existing_count": skipped_existing_count,
        "artifacts": artifacts,
        "created_at": utc_now(),
    }
    manifest_name = f"{run['created_at'].replace(':', '-').replace('+00:00', 'Z')}-{profile_name}"
    write_json(paths.extraction_runs_dir / f"{manifest_name}.json", run)
    (paths.extraction_runs_dir / f"{manifest_name}.md").write_text(render_extraction_run_markdown(run) + "\n", encoding="utf-8")
    run_inventory(paths)
    refresh_indexes(paths.root)
    return run


def structured_output_base(paths: CompanyPaths, entry: dict[str, Any]) -> Path:
    """Map a source registry entry to a deterministic structured output path."""
    local_path = str(entry.get("local_path") or "")
    relative_path = Path(local_path)
    source_prefix = paths.sources_dir.relative_to(paths.root).parts
    reference_prefix = paths.references_dir.relative_to(paths.root).parts
    if relative_path.parts[: len(source_prefix)] == source_prefix and len(relative_path.parts) > len(source_prefix):
        target_relative = Path(*relative_path.parts[len(source_prefix) :])
        return paths.structured_dir / target_relative.with_suffix("")
    if relative_path.parts[: len(reference_prefix)] == reference_prefix and len(relative_path.parts) > len(reference_prefix):
        target_relative = Path("references", *relative_path.parts[len(reference_prefix) :])
        return paths.structured_dir / target_relative.with_suffix("")
    return (paths.structured_dir / "registered" / entry["id"]).with_suffix("")


def _extract_answers(*, qa_items: list[dict[str, Any]], document_text: str, model: str, api_key: str) -> list[dict[str, str]]:
    combined_prompt = _combined_question_prompt(qa_items)
    raw_markdown = extract_commands._generate_answer(
        question=combined_prompt,
        document_text=document_text,
        model=model,
        max_tokens=4096,
        api_key=api_key,
    )
    sections = _split_markdown_sections(raw_markdown)
    results: list[dict[str, str]] = []
    for item in qa_items:
        section_key = item["id"].strip()
        answer = sections.get(section_key, "").strip()
        if not answer:
            answer = sections.get(item["question"].strip(), "").strip()
        if not answer:
            answer = raw_markdown.strip()
        results.append({"id": section_key, "question": item["question"], "answer": answer})
    return results


def _combined_question_prompt(qa_items: list[dict[str, Any]]) -> str:
    prompt_lines = [
        "Answer each question using this exact markdown pattern:",
        "## <id>",
        "<answer>",
        "",
        "Use concise evidence-backed summaries and keep section headings exact.",
        "",
        "Questions:",
    ]
    for item in qa_items:
        prompt_lines.append(f"- {item['id']}: {item['question']}")
    return "\n".join(prompt_lines)


def _split_markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(buffer).strip()
            current_key = line.removeprefix("## ").strip()
            buffer = []
            continue
        buffer.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(buffer).strip()
    return sections


def _render_extracted_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Extracted Evidence: {payload['source']['title']}",
        "",
        f"- profile: {payload['profile']}",
        f"- model: {payload['model']}",
        f"- source_id: {payload['source']['id']}",
        f"- category: {payload['source']['category']}",
        f"- local_path: {payload['source']['local_path']}",
        f"- created_at: {payload['created_at']}",
        "",
    ]
    for item in payload["questions"]:
        lines.extend([f"## {item['id']}", "", item["answer"].strip(), ""])
    return "\n".join(lines).rstrip()


def _match_text(entry: dict[str, Any]) -> str:
    return " ".join(str(entry.get(key) or "") for key in ["title", "category", "local_path", "notes"])


def _read_source_text(paths: CompanyPaths, local_path: str) -> str:
    """Read source text from a file or directory of section files."""
    path = _resolve_local_file(paths, local_path)
    if path.is_dir():
        parts: list[str] = []
        for item in sorted(path.glob("*.md")):
            if item.name == "_sections.md":
                continue
            parts.append(item.read_text(encoding="utf-8"))
        return "\n\n".join(parts)
    return path.read_text(encoding="utf-8")


def _resolve_local_file(paths: CompanyPaths, local_path: str) -> Path:
    candidate = Path(local_path)
    if candidate.is_absolute():
        return candidate
    return paths.root / candidate
