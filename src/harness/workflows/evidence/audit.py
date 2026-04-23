"""V2 evidence audit workflow — assemble prompt, call LLM, write memo."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from harness.workflows.evidence.audit_prompt import AUDIT_PROMPT_TEMPLATE
from harness.workflows.evidence.constants import SEC_CATEGORIES
from harness.workflows.evidence.ledger import load_ledger
from harness.workflows.evidence.paths import CompanyPaths

DEFAULT_AUDIT_MODEL = "gpt-5.4"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_audit(
    paths: CompanyPaths,
    *,
    categories: list[str] | None,
    model: str,
    llm: Callable[..., str],
    company_name: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Assemble a prompt from the evidence ledger, call LLM, and write a memo.

    Parameters
    ----------
    paths:
        Company paths bundle.
    categories:
        If provided, only include ledger entries with a matching category.
        If None, include all categories.
    model:
        LLM model name, passed through to ``llm(model=...)``.
    llm:
        Callable with signature ``(*, prompt: str, model: str) -> str``.
    company_name:
        Human-readable company name. Defaults to ``ticker`` if not provided.
    ticker:
        Stock ticker. Inferred from the first ledger entry if not provided.

    Returns
    -------
    dict with at least ``memo_path`` (str) and ``prompt`` (str).
    """
    entries = load_ledger(paths)

    # Infer ticker from ledger if not provided.
    if ticker is None:
        ticker = entries[0]["ticker"] if entries else "UNKNOWN"

    if company_name is None:
        company_name = ticker

    # Filter by requested categories.
    if categories is not None:
        filtered = [e for e in entries if e.get("category") in categories]
    else:
        filtered = list(entries)

    # Partition into SEC vs external.
    sec_entries = [e for e in filtered if e.get("category") in SEC_CATEGORIES]
    ext_entries = [e for e in filtered if e.get("category") not in SEC_CATEGORIES]

    sec_metadata = _render_sec_metadata(sec_entries)
    external_source_contents = _render_external_contents(paths, ext_entries)

    prompt = AUDIT_PROMPT_TEMPLATE.format(
        ticker=ticker,
        company_name=company_name,
        sec_metadata=sec_metadata,
        external_source_contents=external_source_contents,
    )

    body = llm(prompt=prompt, model=model)

    memo_name = _memo_name(categories)
    paths.audits_dir.mkdir(parents=True, exist_ok=True)
    memo_path = paths.audits_dir / memo_name
    memo_path.write_text(_format_memo(ticker, model, body), encoding="utf-8")

    return {"memo_path": str(memo_path), "prompt": prompt}


# ---------------------------------------------------------------------------
# Default LLM factory
# ---------------------------------------------------------------------------


def default_audit_llm(api_key: str | None = None, *, prefer_openai: bool = True) -> Callable[..., str]:
    """Return a callable ``(*, prompt: str, model: str) -> str``.

    Tries OpenAI first (if ``prefer_openai=True``); falls back to Gemini via
    ``harness.commands.extract._generate_answer``.

    Note: OpenAI is not installed in this project (only used in jobwatch).
    The factory always falls through to the Gemini backend.
    """
    if prefer_openai:
        try:
            import openai as _openai_mod  # noqa: F401

            openai_key = api_key or _openai_mod.api_key
            if not openai_key:
                raise ImportError("OpenAI available but no API key configured")

            def _openai_llm(*, prompt: str, model: str) -> str:
                client = _openai_mod.OpenAI(api_key=openai_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("OpenAI returned an empty response")
                return str(content)

            return _openai_llm
        except (ImportError, ModuleNotFoundError):
            pass  # Fall through to Gemini

    # Gemini fallback via harness.commands.extract._generate_answer
    from harness.commands.extract import _generate_answer
    from harness.config import get_settings

    settings = get_settings()
    gemini_api_key = api_key or (settings.gemini_api_key if settings.gemini_api_key else None)

    def _gemini_llm(*, prompt: str, model: str) -> str:
        if not gemini_api_key:
            raise RuntimeError("No API key configured for Gemini audit LLM (set GEMINI_API_KEY)")
        return _generate_answer(
            question=prompt,
            document_text="",
            model=model,
            max_tokens=8192,
            api_key=gemini_api_key,
        )

    return _gemini_llm


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _memo_name(categories: list[str] | None) -> str:
    """Return ``audit-YYYY-MM-DD.md`` or ``audit-YYYY-MM-DD-<scope>.md``."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if not categories:
        return f"audit-{today}.md"
    scope = "_".join(sorted(categories))
    return f"audit-{today}-{scope}.md"


def _format_memo(ticker: str, model: str, body: str) -> str:
    """Render the standard memo header above the LLM body."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return (
        f"# Evidence Audit — {ticker}\n\n"
        f"- model: {model}\n"
        f"- date: {today}\n\n"
        f"{body}\n"
    )


def _render_sec_metadata(entries: list[dict[str, Any]]) -> str:
    """Render SEC entries as metadata-only lines (no file bodies)."""
    if not entries:
        return "(no SEC filings in scope)"
    lines: list[str] = []
    for e in entries:
        parts = [
            f"- **{e.get('title', '(untitled)')}**",
            f"  category: {e.get('category', '')}",
            f"  status: {e.get('status', '')}",
        ]
        if e.get("date"):
            parts.append(f"  date: {e['date']}")
        if e.get("notes"):
            parts.append(f"  notes: {e['notes']}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _render_external_contents(paths: CompanyPaths, entries: list[dict[str, Any]]) -> str:
    """Render external (non-SEC) sources: full text for downloaded entries."""
    if not entries:
        return "(no external sources in scope)"
    sections: list[str] = []
    for e in entries:
        title = e.get("title", "(untitled)")
        category = e.get("category", "")
        status = e.get("status", "")
        local_path = e.get("local_path")

        if status == "downloaded" and local_path:
            abs_path = paths.root / local_path
            text = _read_source_text(abs_path)
            sections.append(f"### {title}\n\ncategory: {category}\n\n{text}")
        else:
            sections.append(f"### {title}\n\ncategory: {category}\nstatus: {status} — content not available locally")
    return "\n\n---\n\n".join(sections)


def _read_source_text(source_path: Path) -> str:
    """Read text from a file or directory of markdown files."""
    if source_path.is_dir():
        md_files = sorted(p for p in source_path.glob("*.md") if p.name != "_sections.md")
        if not md_files:
            return "(directory exists but no markdown files found)"
        parts = [p.read_text(encoding="utf-8") for p in md_files]
        return "\n\n".join(parts)
    if source_path.exists():
        return source_path.read_text(encoding="utf-8")
    return f"(file not found: {source_path})"
