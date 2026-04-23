# Minerva Evidence V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the V1 evidence workflow (`register` / `inventory` / `coverage` / `extract`) with a V2 workflow built around an `evidence.jsonl` ledger, per-section SEC filing downloads, and an LLM-driven `audit` command.

**Architecture:** Add a new `ledger.py` module (JSONL read/upsert) and a `constants.py` module (recognized categories, extraction questions, context bundle definitions). Rewire `collect_sec_sources` to download per-section files via edgartools structured access and emit one ledger entry per logical filing. Add three new Typer commands under `evidence`: `add-source`, `audit`, `migrate`. Remove V1 `register`/`coverage`. Keep `init`, `collect sec`, `extract`, `inventory` (rewired). Add a one-shot migration script converting `source-registry.json` → `evidence.jsonl`. Downstream `analysis.context` and `analysis.status` read category/ledger fields instead of bucket/registry.

**Tech Stack:** Python 3.12, `uv`, Typer, pytest, `google-genai` (Gemini) for extract, OpenAI or Gemini for audit (`gpt-5.4` default per spec). `edgartools` for SEC. Existing `harness` + `minerva` packages.

**Design decisions:**
- No backward compatibility — clean break from V1.
- No `profiles/` directory — all config constants live in Python modules under `src/harness`.
- No regex-based section splitter — use edgartools' structured `filing.obj()["Item X"]` access for per-section downloads.
- Stale function/folder cleanup is out of scope for this work.

---

## File Structure

**New files**

- `src/harness/workflows/evidence/ledger.py` — JSONL ledger read/write/upsert + deterministic ID.
- `src/harness/workflows/evidence/constants.py` — Recognized categories, extraction questions by category, context bundle definitions.
- `src/harness/workflows/evidence/audit.py` — LLM-driven audit workflow (prompt assembly, LLM call, memo writer).
- `src/harness/workflows/evidence/audit_prompt.py` — The audit prompt template (string constant, kept separate for readability).
- `src/harness/workflows/evidence/migration.py` — One-shot V1 → V2 migration.
- `tests/test_harness/test_evidence_ledger.py` — Ledger unit tests.
- `tests/test_harness/test_evidence_audit.py` — Audit unit tests.
- `tests/test_harness/test_evidence_migration.py` — Migration unit tests.
- `tests/test_harness/test_evidence_v2_cli.py` — CLI wiring tests for `add-source`, `audit`, `migrate`.

**Modified files**

- `src/harness/workflows/evidence/paths.py` — Add `evidence_jsonl`, `evidence_md`, `audits_dir`, `plans_dir`, and top-level `ledger_md` property.
- `src/harness/workflows/evidence/registry.py` — `ensure_company_tree` learns the new folders.
- `src/harness/workflows/evidence/collector.py` — Download per-section files via edgartools; emit one ledger entry per filing.
- `src/harness/workflows/evidence/inventory.py` — Read from ledger, drop registry reads.
- `src/harness/workflows/evidence/extraction.py` — Read ledger; key questions by `category` from `constants.py`; target per-section files.
- `src/harness/workflows/evidence/profiles.py` — Update `load_extract_profile` and `load_context_profile` to read from `constants.py` instead of YAML.
- `src/harness/workflows/evidence/render.py` — Add `render_evidence_ledger_markdown`.
- `src/harness/workflows/analysis/context.py` — Read ledger; filter by `category` using bundle definitions from `constants.py`.
- `src/harness/workflows/analysis/status.py` — Read ledger; read audit markdown for readiness.
- `src/harness/commands/evidence.py` — Remove `register`/`coverage`; add `add-source`/`audit`/`migrate`; keep `init`, `inventory`, `extract`, `collect`.
- `src/harness/commands/sec.py` — Add `_download_filing_sections()` helper using `filing.obj()["Item X"]`.

**Deleted files (post-migration)**

- `profiles/evidence/extract/default.yaml` — Replaced by `constants.py`.
- `profiles/evidence/coverage/default.yaml` — Coverage is gone.
- `profiles/evidence/coverage/test-minimal.yaml` — Coverage is gone.
- `profiles/analysis/context/default.yaml` — Replaced by `constants.py`.

---

## Dependencies Between Phases

```
Phase 1 (ledger + constants) ─┬─► Phase 2 (collector rewire: sec.py + collector.py)
                               ├─► Phase 3 (inventory rewire)
                               ├─► Phase 4 (extract rewire: full V1→V2 field migration)
                               ├─► Phase 6 (audit command)
                               ├─► Phase 7 (CLI wiring)
                               ├─► Phase 8 (migration)
                               └─► Phase 9 (downstream: context + status full rewrite)

Phase 2 has three tasks: 2.1 (helper) → 2.2 (wire into _bulk_download_one) → 2.3 (collector registration)
Phase 5 (audit prompt)         ─► Phase 6 (audit command)
Phase 7 ─► Phase 8 (migration needs CLI for smoke test)
```

Phase 1 and Phase 5 are independent and can run in parallel. Phase 10 (docs) runs last.

---

## Risks and Unknowns

1. **Edgartools structured access reliability.** `filing.obj()["Item X"]` works well for standard 10-K/10-Q filings but may fail on atypical formatting or older filings. Mitigation: collector falls back to single-file download when structured access raises an exception. Log the failure in `data/meta/section-download-failures.jsonl`.
2. **Audit LLM model availability.** Spec names `gpt-5.4` — confirm the OpenAI client is already wired in the repo. If not, plan to use Gemini via existing `google-genai`. **Action in Task 5 below: check `harness.commands.extract` and `harness.config` for an OpenAI-compatible client; if absent, route audit through Gemini and note the deviation.**
3. **Ledger concurrency.** Two `add-source` calls in quick succession could race on the file. Mitigation: atomic `write(tempfile)` + `rename`. Not strictly needed for interactive use, but required for parallel collectors.
4. **Migration idempotence.** Re-running the migration script on a mixed workspace (partial V1 + partial V2) must not corrupt the ledger. Mitigation: migration reads existing `evidence.jsonl` and upserts by deterministic ID.
5. **Non-US filings.** 20-F has analogous sections to 10-K but edgartools may not expose structured access. 6-K varies too much. Mitigation: default to single-file download for anything other than 10-K/10-Q.
6. **V1 field names baked into downstream modules.** `extraction.py`, `context.py`, `status.py`, and `render.py` all hard-code V1 dict keys (`bucket`, `source_kind`, `coverage_json`). Every consumer of evidence entries must be updated to use `category` — not just the selection/filtering logic, but also payload construction, markdown rendering, sort keys, match text, and milestone definitions.

---

## Phase 1: Ledger module + constants (foundational)

### Task 1.1: Add ledger path properties

**Files:**
- Modify: `src/harness/workflows/evidence/paths.py`
- Test: `tests/test_harness/test_evidence.py`

- [ ] **Step 1: Add failing test for new path properties**

Append to `tests/test_harness/test_evidence.py`:

```python
def test_company_paths_exposes_v2_paths(tmp_path: Path) -> None:
    from harness.workflows.evidence.paths import resolve_company_root

    paths = resolve_company_root(tmp_path / "reports" / "00-companies" / "12-robinhood")

    assert paths.evidence_jsonl == paths.data_dir / "evidence.jsonl"
    assert paths.evidence_md == paths.data_dir / "evidence.md"
    assert paths.audits_dir == paths.root / "audits"
    assert paths.plans_dir == paths.root / "plans"
    assert paths.ledger_md == paths.root / "LEDGER.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_company_paths_exposes_v2_paths -v`
Expected: FAIL with `AttributeError: ... has no attribute 'evidence_jsonl'`.

- [ ] **Step 3: Add properties to `CompanyPaths`**

Edit `src/harness/workflows/evidence/paths.py` — inside the `CompanyPaths` dataclass block, after `sec_collection_summary_md`:

```python
    @property
    def evidence_jsonl(self) -> Path:
        return self.data_dir / "evidence.jsonl"

    @property
    def evidence_md(self) -> Path:
        return self.data_dir / "evidence.md"

    @property
    def audits_dir(self) -> Path:
        return self.root / "audits"

    @property
    def plans_dir(self) -> Path:
        return self.root / "plans"

    @property
    def ledger_md(self) -> Path:
        return self.root / "LEDGER.md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_company_paths_exposes_v2_paths -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/evidence/paths.py tests/test_harness/test_evidence.py
git commit -m "feat(evidence): add V2 ledger + audit path properties"
```

### Task 1.2: Create ledger module — deterministic ID and read

**Files:**
- Create: `src/harness/workflows/evidence/ledger.py`
- Create: `tests/test_harness/test_evidence_ledger.py`

- [ ] **Step 1: Write failing test for `make_evidence_id`**

Create `tests/test_harness/test_evidence_ledger.py`:

```python
"""Tests for the V2 evidence ledger."""

from pathlib import Path

from harness.workflows.evidence.ledger import (
    load_ledger,
    make_evidence_id,
    upsert_evidence,
)
from harness.workflows.evidence.paths import resolve_company_root


def test_make_evidence_id_is_deterministic_12_char_hex() -> None:
    a = make_evidence_id(ticker="HOOD", category="sec-annual", title="HOOD 10-K FY2025", local_path="data/sources/10-K/2025-02-18", url="https://sec.gov/x")
    b = make_evidence_id(ticker="HOOD", category="sec-annual", title="HOOD 10-K FY2025", local_path="data/sources/10-K/2025-02-18", url="https://sec.gov/x")
    c = make_evidence_id(ticker="HOOD", category="sec-annual", title="HOOD 10-K FY2024", local_path="data/sources/10-K/2024-02-18", url="https://sec.gov/y")

    assert a == b
    assert len(a) == 12
    assert all(ch in "0123456789abcdef" for ch in a)
    assert a != c


def test_load_ledger_returns_empty_list_when_missing(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    assert load_ledger(paths) == []
```

- [ ] **Step 2: Run test to verify import failure**

Run: `uv run pytest tests/test_harness/test_evidence_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: ...ledger`.

- [ ] **Step 3: Create the module skeleton**

Create `src/harness/workflows/evidence/ledger.py`:

```python
"""V2 JSONL evidence ledger — one logical source per line."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.workflows.evidence.paths import CompanyPaths

LEDGER_VERSION = 2
EVIDENCE_STATUSES: frozenset[str] = frozenset({"downloaded", "discovered", "blocked"})


def make_evidence_id(
    *,
    ticker: str,
    category: str,
    title: str,
    local_path: str | None,
    url: str | None,
) -> str:
    """Deterministic 12-char hex: sha1(ticker|category|title|local_path|url)[:12]."""
    payload = "|".join([ticker.upper(), category, title, local_path or "", url or ""])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_ledger(paths: CompanyPaths) -> list[dict[str, Any]]:
    """Return the ledger as a list of dicts. Empty list when missing."""
    path = paths.evidence_jsonl
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        entries.append(json.loads(stripped))
    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_harness/test_evidence_ledger.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/evidence/ledger.py tests/test_harness/test_evidence_ledger.py
git commit -m "feat(evidence): add V2 ledger read + deterministic id"
```

### Task 1.3: Ledger upsert + atomic write + markdown render

**Files:**
- Modify: `src/harness/workflows/evidence/ledger.py`
- Modify: `src/harness/workflows/evidence/render.py`
- Modify: `tests/test_harness/test_evidence_ledger.py`

- [ ] **Step 1: Add failing tests for upsert**

Append to `tests/test_harness/test_evidence_ledger.py`:

```python
import json


def test_upsert_evidence_creates_then_updates(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)

    created = upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url="https://sec.gov/x",
        date="2025-02-18",
        notes="9 sections",
        collector="sec",
    )

    assert created["id"] == make_evidence_id(
        ticker="HOOD",
        category="sec-annual",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url="https://sec.gov/x",
    )
    assert created["version"] == 2
    assert created["status"] == "downloaded"
    assert created["created_at"] == created["updated_at"]

    updated = upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url="https://sec.gov/x",
        date="2025-02-18",
        notes="updated",
        collector="sec",
    )

    ledger = load_ledger(paths)
    assert len(ledger) == 1
    assert ledger[0]["notes"] == "updated"
    assert updated["updated_at"] >= created["updated_at"]


def test_upsert_evidence_rejects_unknown_status(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        upsert_evidence(
            paths,
            ticker="HOOD",
            category="sec-annual",
            status="weird",
            title="x",
            local_path=None,
            url=None,
            date=None,
            notes=None,
            collector=None,
        )
    except ValueError as exc:
        assert "status" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_upsert_evidence_writes_jsonl_and_markdown(tmp_path: Path) -> None:
    paths = resolve_company_root(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)

    upsert_evidence(
        paths,
        ticker="HOOD",
        category="sec-annual",
        status="downloaded",
        title="HOOD 10-K FY2025",
        local_path="data/sources/10-K/2025-02-18",
        url=None,
        date="2025-02-18",
        notes=None,
        collector="sec",
    )

    jsonl_lines = [json.loads(line) for line in paths.evidence_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(jsonl_lines) == 1
    md_text = paths.evidence_md.read_text(encoding="utf-8")
    assert "HOOD 10-K FY2025" in md_text
    assert "sec-annual" in md_text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_harness/test_evidence_ledger.py -v`
Expected: FAIL with `ImportError: cannot import name 'upsert_evidence'`.

- [ ] **Step 3: Implement upsert, atomic write, and markdown render**

Append to `src/harness/workflows/evidence/ledger.py`:

```python
def upsert_evidence(
    paths: CompanyPaths,
    *,
    ticker: str,
    category: str,
    status: str,
    title: str,
    local_path: str | None,
    url: str | None,
    date: str | None,
    notes: str | None,
    collector: str | None,
) -> dict[str, Any]:
    """Insert-or-update an evidence record. Writes JSONL atomically + evidence.md."""
    if status not in EVIDENCE_STATUSES:
        raise ValueError(f"unsupported evidence status: {status}")
    if status == "downloaded" and not local_path:
        raise ValueError("status=downloaded requires local_path")

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    entries = load_ledger(paths)
    entry_id = make_evidence_id(
        ticker=ticker,
        category=category,
        title=title,
        local_path=local_path,
        url=url,
    )
    now = utc_now()
    existing = next((item for item in entries if item["id"] == entry_id), None)
    if existing is None:
        entry = {
            "id": entry_id,
            "version": LEDGER_VERSION,
            "title": title,
            "ticker": ticker.upper(),
            "category": category,
            "status": status,
            "local_path": local_path,
            "url": url,
            "date": date,
            "notes": notes,
            "collector": collector,
            "created_at": now,
            "updated_at": now,
        }
        entries.append(entry)
    else:
        existing.update(
            {
                "title": title,
                "ticker": ticker.upper(),
                "category": category,
                "status": status,
                "local_path": local_path,
                "url": url,
                "date": date,
                "notes": notes,
                "collector": collector,
                "updated_at": now,
            }
        )
        entry = existing

    _write_ledger_atomic(paths, entries)
    from harness.workflows.evidence.render import render_evidence_ledger_markdown

    paths.evidence_md.write_text(render_evidence_ledger_markdown(entries) + "\n", encoding="utf-8")
    return entry


def _write_ledger_atomic(paths: CompanyPaths, entries: list[dict[str, Any]]) -> None:
    paths.evidence_jsonl.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(
        json.dumps(entry, sort_keys=True, ensure_ascii=False) for entry in sorted(entries, key=lambda item: item["id"])
    )
    fd, tmp_name = tempfile.mkstemp(prefix="evidence-", suffix=".jsonl", dir=str(paths.evidence_jsonl.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            if serialized:
                handle.write("\n")
        os.replace(tmp_name, paths.evidence_jsonl)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
```

- [ ] **Step 4: Add renderer in `render.py`**

Add to `src/harness/workflows/evidence/render.py`:

```python
def render_evidence_ledger_markdown(entries: list[dict[str, Any]]) -> str:
    """Render the V2 ledger as a compact markdown summary."""
    rows: list[list[str]] = []
    for entry in sorted(entries, key=lambda item: (item.get("category") or "", item.get("date") or "", item["id"])):
        rows.append(
            [
                entry["id"],
                entry.get("status", ""),
                entry.get("category", ""),
                entry.get("title", ""),
                entry.get("date") or "",
                entry.get("local_path") or "",
                entry.get("url") or "",
            ]
        )
    table = build_markdown_table(
        ["id", "status", "category", "title", "date", "local_path", "url"],
        rows or [["(none)", "", "", "", "", "", ""]],
        alignment=["l", "l", "l", "l", "l", "l", "l"],
    )
    return "\n".join(
        [
            "# Evidence Ledger (V2)",
            "",
            f"- source_count: {len(entries)}",
            "",
            table,
        ]
    )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_ledger.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/workflows/evidence/ledger.py src/harness/workflows/evidence/render.py tests/test_harness/test_evidence_ledger.py
git commit -m "feat(evidence): ledger upsert + atomic write + md render"
```

### Task 1.4: Extend `ensure_company_tree` to create V2 dirs

**Files:**
- Modify: `src/harness/workflows/evidence/registry.py`
- Modify: `tests/test_harness/test_evidence.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_harness/test_evidence.py`:

```python
def test_evidence_init_creates_v2_dirs(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    assert (root / "audits").exists()
    assert (root / "plans").exists()
    assert (root / "research").exists()
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_evidence_init_creates_v2_dirs -v`
Expected: FAIL (`audits` and `plans` missing).

- [ ] **Step 3: Update `ensure_company_tree`**

Edit `src/harness/workflows/evidence/registry.py` — add `paths.audits_dir` and `paths.plans_dir` to the directory list in `ensure_company_tree`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence.py -v`
Expected: PASS including existing init tests.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/evidence/registry.py tests/test_harness/test_evidence.py
git commit -m "feat(evidence): init creates audits/ and plans/ dirs"
```

### Task 1.5: Create constants module

**Files:**
- Create: `src/harness/workflows/evidence/constants.py`

- [ ] **Step 1: Create the module**

Create `src/harness/workflows/evidence/constants.py`:

```python
"""V2 evidence constants — categories, extraction questions, context bundles.

These replace the YAML profile files under profiles/. All evidence
and analysis config is defined here as Python constants.
"""

from __future__ import annotations

# --- Recognized categories ---

RECOGNIZED_CATEGORIES: frozenset[str] = frozenset({
    # SEC
    "sec-annual",
    "sec-quarterly",
    "sec-earnings",
    "sec-financials",
    "sec-proxy",
    "sec-other",
    # External
    "industry-report",
    "competitor-data",
    "customer-evidence",
    "expert-input",
    "news",
    "company-ir",
    "regulatory",
    "other",
})

SEC_CATEGORIES: frozenset[str] = frozenset({
    "sec-annual",
    "sec-quarterly",
    "sec-earnings",
    "sec-financials",
    "sec-proxy",
    "sec-other",
})

# --- Extraction questions by category ---
# Each key maps to a list of {"id": ..., "question": ...} dicts.

EXTRACTION_QUESTIONS: dict[str, list[dict[str, str]]] = {
    "sec-annual": [
        {"id": "business-overview", "question": "Summarize the business model, operating segments, and primary revenue drivers."},
        {"id": "financial-highlights", "question": "Extract the key financial metrics as a markdown table with columns: Metric, Current Period, Prior Period, YoY Change. Include revenue, operating income, net income, EPS, and any segment-level breakdowns."},
        {"id": "growth-drivers", "question": "What is actually driving growth or decline? Identify the specific products, segments, geographies, or initiatives management credits for changes in revenue and profitability. Include numbers."},
        {"id": "competition", "question": "Summarize the competitive positioning, moats, and management's framing of competition."},
        {"id": "management", "question": "Summarize management priorities, strategic initiatives, and capital allocation signals."},
        {"id": "risks", "question": "Summarize the most important business and operating risks."},
    ],
    "sec-quarterly": [
        {"id": "recent-update", "question": "Summarize the most important quarter-to-date operating changes and management commentary."},
        {"id": "financial-update", "question": "Extract the key quarter financial metrics as a markdown table: Metric, Current Quarter, Prior Year Quarter, YoY Change. Include revenue, operating income, net income, and EPS."},
        {"id": "risks", "question": "Summarize the most important new or changed risks mentioned in the filing."},
    ],
    "sec-earnings": [
        {"id": "earnings-takeaways", "question": "Summarize the most important earnings takeaways, KPIs, and guidance changes."},
        {"id": "kpi-summary", "question": "Extract the key reported KPIs as a markdown table: KPI, Value, Prior Period Value, Change. Include user/customer metrics, engagement metrics, and unit economics."},
        {"id": "guidance", "question": "Extract any forward guidance, targets, or outlook statements. Quote management directly where possible. If no guidance was provided, state that explicitly."},
        {"id": "management", "question": "Summarize management's near-term priorities and tone from the earnings material."},
    ],
    "sec-financials": [
        {"id": "statement-summary", "question": "Summarize the key trends and material year-over-year changes."},
    ],
    "industry-report": [
        {"id": "external-evidence", "question": "Summarize the most important third-party evidence and how it changes the business view."},
    ],
    "competitor-data": [
        {"id": "external-evidence", "question": "Summarize competitor positioning and what it implies for the target company."},
    ],
    "customer-evidence": [
        {"id": "external-evidence", "question": "Summarize what customers say and what it implies for the business."},
    ],
    "news": [
        {"id": "external-evidence", "question": "Summarize newsworthy developments and their implications."},
    ],
    "company-ir": [
        {"id": "external-evidence", "question": "Summarize IR content and how it changes the business view."},
    ],
    "expert-input": [
        {"id": "external-evidence", "question": "Summarize expert input and its implications."},
    ],
}

# --- Context bundle definitions ---
# Each bundle specifies which evidence categories feed into it.

CONTEXT_BUNDLES: list[dict] = [
    {
        "name": "business-overview",
        "categories": ["sec-annual", "sec-quarterly", "industry-report", "company-ir"],
    },
    {
        "name": "competition",
        "categories": ["sec-annual", "industry-report", "competitor-data"],
    },
    {
        "name": "management",
        "categories": ["sec-annual", "sec-earnings"],
    },
    {
        "name": "risks",
        "categories": ["sec-annual", "sec-quarterly", "news", "regulatory"],
    },
    {
        "name": "valuation",
        "categories": ["sec-financials", "sec-earnings"],
        "extra_globs": ["analysis/valuation/**/*.md"],
    },
]

# --- 10-K / 10-Q section maps ---
# Maps item number → (slug, display_name) for per-section file naming.

SECTION_MAP_10K: dict[str, tuple[str, str]] = {
    "1": ("business", "Business"),
    "1A": ("risk-factors", "Risk Factors"),
    "1B": ("unresolved-staff-comments", "Unresolved Staff Comments"),
    "1C": ("cybersecurity", "Cybersecurity"),
    "2": ("properties", "Properties"),
    "3": ("legal-proceedings", "Legal Proceedings"),
    "4": ("mine-safety-disclosures", "Mine Safety Disclosures"),
    "5": ("market-for-registrant", "Market for Registrant"),
    "7": ("mdna", "MD&A"),
    "7A": ("quantitative-qualitative-market-risk", "Quantitative & Qualitative Market Risk"),
    "8": ("financial-statements", "Financial Statements"),
    "9": ("changes-disagreements-accountants", "Changes/Disagreements with Accountants"),
    "9A": ("controls-and-procedures", "Controls and Procedures"),
    "9B": ("other-information", "Other Information"),
    "10": ("directors-and-officers", "Directors and Officers"),
    "11": ("executive-compensation", "Executive Compensation"),
    "12": ("security-ownership", "Security Ownership"),
    "13": ("related-transactions", "Related Transactions"),
    "14": ("principal-accountant-fees", "Principal Accountant Fees"),
    "15": ("exhibits-schedules", "Exhibits and Schedules"),
}

SECTION_MAP_10Q: dict[str, tuple[str, str]] = {
    "1": ("financial-statements", "Financial Statements"),
    "2": ("mdna", "MD&A"),
    "3": ("quantitative-qualitative-market-risk", "Quantitative & Qualitative Market Risk"),
    "4": ("controls-and-procedures", "Controls and Procedures"),
    "1A": ("risk-factors", "Risk Factors"),
    "5": ("other-information", "Other Information"),
    "6": ("exhibits", "Exhibits"),
}

# Default items to download for each form type.
DEFAULT_10K_ITEMS: list[str] = ["1", "1A", "1C", "2", "3", "7", "7A", "8", "9A"]
DEFAULT_10Q_ITEMS: list[str] = ["1", "2", "1A", "4"]
```

- [ ] **Step 2: Commit**

```bash
git add src/harness/workflows/evidence/constants.py
git commit -m "feat(evidence): add constants module replacing YAML profiles"
```

---

## Phase 2: Rewire collector — per-section download via edgartools

### Task 2.1: Add per-section download helper in sec.py

**Files:**
- Modify: `src/harness/commands/sec.py`
- Create: `tests/test_harness/test_sec_section_download.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_harness/test_sec_section_download.py`:

```python
"""Tests for per-section filing download."""

from pathlib import Path
from unittest.mock import MagicMock

from harness.commands.sec import _download_filing_sections


def test_download_filing_sections_creates_per_section_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "10-K" / "2025-02-18"

    # Mock a filing object with structured item access.
    mock_filing = MagicMock()
    mock_obj = MagicMock()
    mock_obj.__getitem__ = lambda self, key: f"Content for {key}.\nLots of detail."
    mock_filing.obj.return_value = mock_obj

    result = _download_filing_sections(
        filing=mock_filing,
        form="10-K",
        out_dir=out_dir,
    )

    assert result["mode"] == "split"
    assert (out_dir / "01-business.md").exists()
    assert (out_dir / "02-risk-factors.md").exists()
    assert (out_dir / "_sections.md").exists()
    index_text = (out_dir / "_sections.md").read_text(encoding="utf-8")
    assert "01-business.md" in index_text


def test_download_filing_sections_falls_back_on_error(tmp_path: Path) -> None:
    out_dir = tmp_path / "10-K" / "2025-02-18"

    mock_filing = MagicMock()
    mock_filing.obj.side_effect = Exception("Structured access failed")
    mock_filing.markdown.return_value = "# Full filing\nBody text."

    result = _download_filing_sections(
        filing=mock_filing,
        form="10-K",
        out_dir=out_dir,
    )

    assert result["mode"] == "single"
    assert (out_dir / "filing.md").exists()
    assert (out_dir / "_sections.md").exists()
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_harness/test_sec_section_download.py -v`
Expected: FAIL (`cannot import name '_download_filing_sections'`).

- [ ] **Step 3: Implement `_download_filing_sections`**

Add to `src/harness/commands/sec.py`:

```python
from harness.workflows.evidence.constants import (
    DEFAULT_10K_ITEMS,
    DEFAULT_10Q_ITEMS,
    SECTION_MAP_10K,
    SECTION_MAP_10Q,
)


def _download_filing_sections(
    *,
    filing: Any,
    form: str,
    out_dir: Path,
) -> dict[str, Any]:
    """Download individual sections from a filing using edgartools structured access.

    Falls back to single-file download when structured access fails.
    Returns {"mode": "split"|"single", "sections": [...]}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    section_map = SECTION_MAP_10K if form.upper() == "10-K" else SECTION_MAP_10Q
    items = DEFAULT_10K_ITEMS if form.upper() == "10-K" else DEFAULT_10Q_ITEMS

    try:
        filing_obj = filing.obj()
    except Exception:
        return _fallback_single_file(filing, out_dir)

    sections: list[dict[str, str]] = []
    idx = 0
    for item_num in items:
        if item_num not in section_map:
            continue
        slug, display_name = section_map[item_num]
        try:
            text = str(filing_obj[f"Item {item_num}"])
            if not text or text.strip() == "":
                continue
        except (KeyError, IndexError, TypeError):
            continue
        idx += 1
        filename = f"{idx:02d}-{slug}.md"
        (out_dir / filename).write_text(
            f"## ITEM {item_num}. {display_name.upper()}\n\n{text}\n",
            encoding="utf-8",
        )
        sections.append({"filename": filename, "title": f"ITEM {item_num}. {display_name}"})

    if not sections:
        return _fallback_single_file(filing, out_dir)

    _write_sections_index(out_dir, sections)
    return {"mode": "split", "sections": sections}


def _fallback_single_file(filing: Any, out_dir: Path) -> dict[str, Any]:
    """Fall back to downloading the full filing as a single markdown file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        text = filing.markdown() if hasattr(filing, "markdown") else str(filing)
    except Exception:
        text = str(filing)
    (out_dir / "filing.md").write_text(text, encoding="utf-8")
    _write_sections_index(out_dir, [{"filename": "filing.md", "title": "Full filing"}])
    return {"mode": "single", "sections": [{"filename": "filing.md", "title": "Full filing"}]}


def _write_sections_index(out_dir: Path, sections: list[dict[str, str]]) -> None:
    lines = ["# Sections", ""]
    for item in sections:
        lines.append(f"- [{item['title']}](./{item['filename']})")
    (out_dir / "_sections.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_sec_section_download.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/commands/sec.py tests/test_harness/test_sec_section_download.py
git commit -m "feat(sec): per-section filing download via edgartools structured access"
```

### Task 2.2: Wire `_download_filing_sections` into `_bulk_download_one`

**Files:**
- Modify: `src/harness/commands/sec.py`

- [ ] **Step 1: Modify `_bulk_download_one` for 10-K/10-Q**

Edit `src/harness/commands/sec.py`. In the `_bulk_download_one` function, replace the 10-K/10-Q download loop. Instead of writing monolithic `{date}.md` files via `_save_filing`, call `_download_filing_sections(filing=filing, form=form, out_dir=target_dir / date_str)` to produce a dated directory with per-section files. Keep the earnings and financials loops unchanged (they stay as single files).

The existing loop:
```python
for form, count, folder_name in [("10-K", annual, "10-K"), ("10-Q", quarters, "10-Q")]:
    ...
    _save_filing(filing, markdown_target, file_format="markdown")
```

Becomes:
```python
for form, count, folder_name in [("10-K", annual, "10-K"), ("10-Q", quarters, "10-Q")]:
    target_dir = company_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    for filing in _list_filings(company, form=form, limit=count):
        date_str = _filing_date(filing)
        section_dir = target_dir / date_str
        if section_dir.exists():
            skipped += 1
            continue
        _download_filing_sections(filing=filing, form=form, out_dir=section_dir)
        downloaded[form] += 1
```

- [ ] **Step 2: Run existing tests + new section download tests**

Run: `uv run pytest tests/test_harness/test_sec_section_download.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/harness/commands/sec.py
git commit -m "feat(sec): wire per-section download into _bulk_download_one for 10-K/10-Q"
```

---

### Task 2.3: Rewire collector to register ledger entries from disk

**Files:**
- Modify: `src/harness/workflows/evidence/collector.py`
- Modify: `tests/test_harness/test_evidence.py`

- [ ] **Step 1: Add failing test**

Add a new test in `tests/test_harness/test_evidence.py`:

```python
def test_evidence_collect_sec_v2_writes_ledger_and_per_section_files(tmp_path: Path, monkeypatch) -> None:
    import json as _json
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    settings = HarnessSettings(workspace_root=tmp_path, edgar_identity="x x@y.com")

    monkeypatch.setattr("harness.commands.sec._configure_edgar", lambda s: None)

    def fake_bulk_download_one(*, ticker, base_output, annual, quarters, earnings, include_financials, include_html=True, nest_ticker=True):
        # Simulate per-section download result: a directory with section files.
        company_root = base_output / ticker.upper() if nest_ticker else base_output
        section_dir = company_root / "10-K" / "2025-02-18"
        section_dir.mkdir(parents=True, exist_ok=True)
        (section_dir / "01-business.md").write_text("## ITEM 1. BUSINESS\nBusiness.", encoding="utf-8")
        (section_dir / "02-risk-factors.md").write_text("## ITEM 1A. RISK FACTORS\nRisk.", encoding="utf-8")
        (section_dir / "_sections.md").write_text("# Sections\n- [ITEM 1. Business](./01-business.md)\n", encoding="utf-8")
        (company_root / "earnings" / "2025-11-05.md").parent.mkdir(parents=True, exist_ok=True)
        (company_root / "earnings" / "2025-11-05.md").write_text("# Earnings", encoding="utf-8")
        return ["ok"]

    monkeypatch.setattr("harness.commands.sec._bulk_download_one", fake_bulk_download_one)

    result = evidence.collect_sec_command(
        root=str(root),
        ticker="HOOD",
        annual=1,
        quarters=0,
        earnings=1,
        include_financials=False,
        include_html=False,
        settings=settings,
    )

    assert result.exit_code == 0

    ledger_path = root / "data" / "evidence.jsonl"
    lines = [_json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = {entry["category"] for entry in lines}
    assert categories == {"sec-annual", "sec-earnings"}
    annual = [e for e in lines if e["category"] == "sec-annual"]
    assert len(annual) == 1
    assert annual[0]["local_path"] == "data/sources/10-K/2025-02-18"
    assert (root / "data" / "sources" / "10-K" / "2025-02-18" / "01-business.md").exists()
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_evidence_collect_sec_v2_writes_ledger_and_per_section_files -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `collect_sec_sources`**

Edit `src/harness/workflows/evidence/collector.py`. Replace the body with a version that:

- Calls `_bulk_download_one` to produce the files on disk (this function will be updated to use `_download_filing_sections` for 10-K/10-Q).
- Scans the resulting directories/files and calls `upsert_evidence` for each.
- For 10-K/10-Q: expects a directory with per-section files. Registers one ledger entry per filing date pointing to the directory.
- For earnings: registers one ledger entry per file.
- For financials: registers one ledger entry per statement file.
- Never registers HTML files in the ledger.

Key change in imports — remove `from harness.workflows.evidence.section_splitter import split_filing`.

The collector should scan for both directory-style (per-section) and file-style (single monolith or earnings) sources:

```python
def _register_filings(paths: CompanyPaths, *, ticker: str, form_folder: str) -> list[dict[str, Any]]:
    """Register 10-K or 10-Q filings. Expects per-section directories."""
    out: list[dict[str, Any]] = []
    folder = paths.sources_dir / form_folder
    if not folder.exists():
        return out
    category = _FORM_TO_CATEGORY[form_folder]
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.is_dir():
            # Per-section directory
            date_stem = entry.name
            section_count = len([f for f in entry.glob("*.md") if f.name != "_sections.md"])
            notes = f"{section_count} sections" if section_count > 1 else "single-file filing"
            ledger_entry = upsert_evidence(
                paths,
                ticker=ticker,
                category=category,
                status="downloaded",
                title=f"{ticker.upper()} {form_folder} {date_stem}",
                local_path=str(entry.relative_to(paths.root)),
                url=None,
                date=date_stem,
                notes=notes,
                collector="sec",
            )
            out.append(ledger_entry)
        elif entry.suffix == ".md":
            # Legacy monolithic file — register as-is, pointing to the file
            date_stem = entry.stem
            ledger_entry = upsert_evidence(
                paths,
                ticker=ticker,
                category=category,
                status="downloaded",
                title=f"{ticker.upper()} {form_folder} {date_stem}",
                local_path=str(entry.relative_to(paths.root)),
                url=None,
                date=date_stem,
                notes="monolithic filing (legacy)",
                collector="sec",
            )
            out.append(ledger_entry)
    return out
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_evidence_collect_sec_v2_writes_ledger_and_per_section_files -v`
Expected: PASS.

- [ ] **Step 5: Mark old V1 collector test as temporarily xfail**

Decorate `test_evidence_collect_sec_registers_downloaded_sources_and_inventory` and `test_evidence_extract_coverage_status_and_context_round_trip` with `@pytest.mark.xfail(reason="V1 registry semantics; rewritten in later phase", strict=False)`.

- [ ] **Step 6: Commit**

```bash
git add src/harness/workflows/evidence/collector.py tests/test_harness/test_evidence.py
git commit -m "feat(evidence): collect sec writes V2 ledger + per-section files via edgartools"
```

---

## Phase 3: Inventory rewire

### Task 3.1: Inventory reads from ledger

**Files:**
- Modify: `src/harness/workflows/evidence/inventory.py`
- Modify: `tests/test_harness/test_evidence.py`

- [ ] **Step 1: Add failing test**

Add to `tests/test_harness/test_evidence.py`:

```python
def test_inventory_v2_reads_ledger(tmp_path: Path) -> None:
    from harness.workflows.evidence.ledger import upsert_evidence
    from harness.workflows.evidence.inventory import run_inventory
    from harness.workflows.evidence.paths import resolve_company_root

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    target = paths.sources_dir / "10-K" / "2025-02-18"
    target.mkdir(parents=True, exist_ok=True)
    (target / "01-business.md").write_text("x", encoding="utf-8")

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(target.relative_to(paths.root)),
        url=None, date="2025-02-18", notes=None, collector="sec",
    )
    upsert_evidence(
        paths, ticker="HOOD", category="industry-report", status="discovered",
        title="Market report", local_path=None, url="https://example.com", date=None, notes=None, collector="web_fetch",
    )
    upsert_evidence(
        paths, ticker="HOOD", category="news", status="blocked",
        title="Paywalled news", local_path=None, url="https://paywall.example.com", date=None, notes="paywall", collector="web_fetch",
    )

    inv = run_inventory(paths)
    assert inv["counts"]["downloaded"] == 1
    assert inv["counts"]["discovered"] == 1
    assert inv["counts"]["blocked"] == 1
    assert inv["counts"]["downloaded_missing_on_disk"] == 0
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_inventory_v2_reads_ledger -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `build_inventory` to read from `load_ledger`**

Replace `list_sources(paths)` with `load_ledger(paths)`. Replace `registry_total` with `ledger_total`. Same logic, different data source.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_inventory_v2_reads_ledger -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/evidence/inventory.py tests/test_harness/test_evidence.py
git commit -m "feat(evidence): inventory reads V2 ledger"
```

---

## Phase 4: Extraction rewire

### Task 4.1: Extract reads ledger and uses constants for questions

**Files:**
- Modify: `src/harness/workflows/evidence/extraction.py`
- Modify: `src/harness/workflows/evidence/profiles.py`
- Modify: `tests/test_harness/test_evidence.py`

- [ ] **Step 1: Update profiles.py to read from constants**

Edit `src/harness/workflows/evidence/profiles.py`:

```python
def load_extract_profile(name: str) -> dict[str, Any]:
    """Load extraction profile. Reads from constants.py instead of YAML."""
    from harness.workflows.evidence.constants import EXTRACTION_QUESTIONS
    return {"name": name, "categories": {cat: {"questions": qs} for cat, qs in EXTRACTION_QUESTIONS.items()}}


def load_context_profile(name: str) -> dict[str, Any]:
    """Load context profile. Reads from constants.py instead of YAML."""
    from harness.workflows.evidence.constants import CONTEXT_BUNDLES
    return {"name": name, "bundles": list(CONTEXT_BUNDLES)}
```

Keep `load_coverage_profile` as-is for now (it's dead code after `coverage` is removed, but removing it is out of scope per Anton).

- [ ] **Step 2: Add failing test**

Add to `tests/test_harness/test_evidence.py`:

```python
def test_extract_v2_uses_ledger_and_categories(tmp_path: Path, monkeypatch) -> None:
    from harness.workflows.evidence.ledger import upsert_evidence
    from harness.workflows.evidence.extraction import run_extraction
    from harness.workflows.evidence.paths import resolve_company_root

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)
    settings = HarnessSettings(workspace_root=tmp_path, gemini_api_key="fake-key")

    filing_dir = paths.sources_dir / "10-K" / "2025-02-18"
    filing_dir.mkdir(parents=True, exist_ok=True)
    (filing_dir / "01-business.md").write_text("# Business\nProse", encoding="utf-8")
    (filing_dir / "02-risk-factors.md").write_text("# Risks", encoding="utf-8")

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(filing_dir.relative_to(paths.root)),
        url=None, date="2025-02-18", notes=None, collector="sec",
    )

    monkeypatch.setattr(
        "harness.commands.extract._generate_answer",
        lambda **kwargs: "## business-overview\nA\n## financial-highlights\nB\n## growth-drivers\nC\n## competition\nD\n## management\nE\n## risks\nF",
    )

    run = run_extraction(
        paths, profile_name="default", source_prefix=None, match=None, force=True, model="fake", settings=settings,
    )
    assert run["processed_count"] == 1
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_extract_v2_uses_ledger_and_categories -v`
Expected: FAIL.

- [ ] **Step 4: Update `run_extraction` — full V1→V2 field migration**

Edit `src/harness/workflows/evidence/extraction.py`:

- Replace `from harness.workflows.evidence.registry import list_sources, utc_now` with `from harness.workflows.evidence.ledger import load_ledger, utc_now`.
- Replace `list_sources(paths)` with `load_ledger(paths)`.
- Replace `source_kinds = profile.get("source_kinds", {})` with `categories = profile.get("categories", {})`.
- Replace `if entry["source_kind"] not in source_kinds` with `if entry["category"] not in categories`.
- Replace `qa_items = source_kinds[entry["source_kind"]].get("questions", [])` with `qa_items = categories[entry["category"]].get("questions", [])`.
- **Rewrite the `payload["source"]` dict** — replace `"bucket": entry["bucket"], "source_kind": entry["source_kind"]` with `"category": entry["category"]`. V2 entries do not have `bucket` or `source_kind` — accessing them will raise `KeyError`.
- **Rewrite `_render_extracted_markdown`** — replace the lines rendering `f"- bucket: {payload['source']['bucket']}"` and `f"- source_kind: {payload['source']['source_kind']}"` with `f"- category: {payload['source']['category']}"`.
- **Update `_match_text`** — replace `"bucket", "source_kind"` in the key list with `"category"`.
- Add per-section file support — add `_read_source_text` helper:

```python
def _read_source_text(paths: CompanyPaths, local_path: str) -> str:
    path = _resolve_local_file(paths, local_path)
    if path.is_dir():
        parts: list[str] = []
        for item in sorted(path.glob("*.md")):
            if item.name == "_sections.md":
                continue
            parts.append(item.read_text(encoding="utf-8"))
        return "\n\n".join(parts)
    return path.read_text(encoding="utf-8")
```

- Replace `file_text = _resolve_local_file(paths, entry["local_path"]).read_text(...)` with `file_text = _read_source_text(paths, entry["local_path"])`.
- **Add test for `structured_output_base` with directory-backed `local_path`** — V2 per-section filings point to directories. Verify the output path convention produces sensible paths (e.g., `data/structured/10-K/2025-02-18.json`).

- [ ] **Step 5: Run test**

Run: `uv run pytest tests/test_harness/test_evidence.py::test_extract_v2_uses_ledger_and_categories -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/workflows/evidence/extraction.py src/harness/workflows/evidence/profiles.py tests/test_harness/test_evidence.py
git commit -m "feat(evidence): extract reads ledger + categories from constants"
```

---

## Phase 5: Audit prompt

### Task 5.1: Extract the audit prompt into a module constant

**Files:**
- Create: `src/harness/workflows/evidence/audit_prompt.py`

- [ ] **Step 1: Create the module**

Create `src/harness/workflows/evidence/audit_prompt.py` and paste the audit prompt exactly as specified in `docs/12-minerva-evidence-v2-zero-based-redesign.md` §4.3, as a Python string constant `AUDIT_PROMPT_TEMPLATE` with `{ticker}`, `{company_name}`, `{sec_metadata}`, and `{external_source_contents}` placeholders. Copy the prompt verbatim from §4.3 of the spec — all 8 principles and the output format block.

- [ ] **Step 2: Commit**

```bash
git add src/harness/workflows/evidence/audit_prompt.py
git commit -m "feat(evidence): add audit prompt template"
```

---

## Phase 6: Audit command

### Task 6.1: Audit workflow — assemble input, call LLM, write memo

**Files:**
- Create: `src/harness/workflows/evidence/audit.py`
- Create: `tests/test_harness/test_evidence_audit.py`

- [ ] **Step 1: Write failing test with injected LLM callable**

Create `tests/test_harness/test_evidence_audit.py`:

```python
"""Tests for the V2 evidence audit."""

from pathlib import Path

from harness.commands import evidence
from harness.workflows.evidence.audit import run_audit
from harness.workflows.evidence.ledger import upsert_evidence
from harness.workflows.evidence.paths import resolve_company_root


def test_run_audit_writes_memo_using_injected_llm(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    filing_dir = paths.sources_dir / "10-K" / "2025-02-18"
    filing_dir.mkdir(parents=True, exist_ok=True)
    (filing_dir / "01-business.md").write_text("# Business\nBody", encoding="utf-8")
    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(filing_dir.relative_to(paths.root)),
        url=None, date="2025-02-18", notes="1 section", collector="sec",
    )

    external = paths.references_dir / "market-report.md"
    external.write_text("# Market report\nCompetitors", encoding="utf-8")
    upsert_evidence(
        paths, ticker="HOOD", category="industry-report", status="downloaded",
        title="Industry report", local_path=str(external.relative_to(paths.root)),
        url=None, date=None, notes=None, collector="manual",
    )

    captured: dict = {}

    def fake_llm(*, prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "Readiness: ready\n\n## Summary\nLooks fine.\n\n## Recommended Actions\n1. Continue."

    result = run_audit(
        paths,
        categories=None,
        model="fake-audit-model",
        llm=fake_llm,
    )

    assert captured["model"] == "fake-audit-model"
    assert "HOOD 10-K 2025" in captured["prompt"]
    assert "# Market report" in captured["prompt"]
    assert "# Business" not in captured["prompt"]  # SEC bodies excluded; only metadata
    memo_text = Path(result["memo_path"]).read_text(encoding="utf-8")
    assert "# Evidence Audit — HOOD" in memo_text
    assert "Readiness: ready" in memo_text


def test_run_audit_filters_by_categories(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="discovered",
        title="A", local_path=None, url="https://a", date=None, notes=None, collector="manual",
    )
    upsert_evidence(
        paths, ticker="HOOD", category="industry-report", status="discovered",
        title="B", local_path=None, url="https://b", date=None, notes=None, collector="manual",
    )

    captured: dict = {}
    def fake_llm(*, prompt, model):
        captured["prompt"] = prompt
        return "Readiness: ready\n## Summary\nok\n## Recommended Actions\n1. go"

    result = run_audit(paths, categories=["industry-report"], model="m", llm=fake_llm)

    assert "industry-report" in captured["prompt"]
    assert " A " not in captured["prompt"]
    assert "audit-" in Path(result["memo_path"]).name
    assert "industry-report" in Path(result["memo_path"]).name
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_audit.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `run_audit`**

Create `src/harness/workflows/evidence/audit.py` with:
- `run_audit(paths, *, categories, model, llm, company_name=None, ticker=None)` — assembles prompt from ledger, calls LLM, writes memo to `audits/`.
- SEC sources contribute metadata only (title, date, status, section count). External sources contribute full file content.
- `_memo_name(categories)` → `audit-YYYY-MM-DD[-scope].md`.
- `_format_memo(ticker, model, body)` → standard memo header.
- Uses `SEC_CATEGORIES` from `constants.py` to distinguish SEC vs external.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/evidence/audit.py tests/test_harness/test_evidence_audit.py
git commit -m "feat(evidence): audit workflow with injected LLM callable"
```

### Task 6.2: Wire a default LLM callable

**Files:**
- Modify: `src/harness/workflows/evidence/audit.py`

- [ ] **Step 1: Add default LLM factory**

Append `DEFAULT_AUDIT_MODEL = "gpt-5.4"` and `default_audit_llm(api_key, *, prefer_openai=True)` that tries OpenAI first, falls back to Gemini via `harness.commands.extract._generate_answer`.

- [ ] **Step 2: Commit**

```bash
git add src/harness/workflows/evidence/audit.py
git commit -m "feat(evidence): default audit LLM factory"
```

---

## Phase 7: CLI — `add-source` + `audit`, remove `register`/`coverage`

### Task 7.1: Add `evidence add-source` command

**Files:**
- Modify: `src/harness/commands/evidence.py`
- Create: `tests/test_harness/test_evidence_v2_cli.py`

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_harness/test_evidence_v2_cli.py`:

```python
"""CLI wiring tests for V2 evidence commands."""

import json
from pathlib import Path

from harness.cli import dispatch_command
from harness.commands import evidence


def test_add_source_writes_ledger_entry(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    ref = root / "data" / "references" / "market.md"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text("body", encoding="utf-8")

    result = dispatch_command(
        [
            "evidence", "add-source",
            "--root", str(root),
            "--title", "Market report",
            "--category", "industry-report",
            "--status", "downloaded",
            "--path", str(ref),
            "--url", "https://example.com/report",
            "--date", "2026-03-01",
            "--collector", "manual",
        ]
    )
    assert result.exit_code == 0, result.stderr.decode("utf-8")
    ledger = [json.loads(line) for line in (root / "data" / "evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(ledger) == 1
    assert ledger[0]["category"] == "industry-report"
    assert ledger[0]["status"] == "downloaded"


def test_add_source_rejects_downloaded_without_path(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    result = dispatch_command(
        [
            "evidence", "add-source",
            "--root", str(root),
            "--title", "X",
            "--category", "news",
            "--status", "downloaded",
        ]
    )
    assert result.exit_code == 1
    assert "requires --path" in result.stderr.decode("utf-8")


def test_add_source_warns_on_unknown_category(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")

    result = dispatch_command(
        [
            "evidence", "add-source",
            "--root", str(root),
            "--title", "X",
            "--category", "wierd-typo",
            "--status", "discovered",
            "--url", "https://example.com",
        ]
    )
    assert result.exit_code == 0
    assert "unrecognized category" in result.stderr.decode("utf-8").lower()
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_v2_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Wire `add-source` command**

Add `add_source_command` to `src/harness/commands/evidence.py`. Key details:

- **Ticker resolution:** The CLI does not have a `--ticker` flag (spec §4.2 omits it), but `upsert_evidence` requires `ticker`. Resolve ticker from the workspace: first check existing ledger entries, then fall back to reading `source-registry.json` (for migrated workspaces), then fall back to inferring from the root directory name. Use the existing `_ticker_from_root(paths)` helper as the final fallback.
- Category warning uses `RECOGNIZED_CATEGORIES` from `constants.py` — no YAML file needed.
- Wire dispatch branch and Typer decorator.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_v2_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/commands/evidence.py tests/test_harness/test_evidence_v2_cli.py
git commit -m "feat(evidence): add-source CLI with category warnings from constants"
```

### Task 7.2: Add `evidence audit` command

**Files:**
- Modify: `src/harness/commands/evidence.py`
- Modify: `tests/test_harness/test_evidence_v2_cli.py`

- [ ] **Step 1: Add failing test**

Append `test_audit_command_produces_memo` to `tests/test_harness/test_evidence_v2_cli.py`.

- [ ] **Step 2: Wire `audit` command**

Add `audit_command` and dispatch branch. Uses `default_audit_llm` from `audit.py`.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_v2_cli.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/harness/commands/evidence.py tests/test_harness/test_evidence_v2_cli.py
git commit -m "feat(evidence): audit CLI command"
```

### Task 7.3: Remove V1 `register` and `coverage` CLI entry points

**Files:**
- Modify: `src/harness/commands/evidence.py`
- Modify: `tests/test_harness/test_evidence.py`

- [ ] **Step 1: Remove `register` and `coverage` from dispatch + Typer**

Remove `register_command`, `coverage_command`, their dispatch branches, and Typer decorators. Update `EVIDENCE_HELP` to reference `add-source` and `audit`. Remove unused imports.

- [ ] **Step 2: Remove / replace obsolete tests**

Delete `test_evidence_extract_coverage_status_and_context_round_trip`, `test_evidence_collect_sec_registers_downloaded_sources_and_inventory`, and `test_structured_output_base_does_not_match_legacy_01_data_prefix`.

- [ ] **Step 3: Run full evidence suite**

Run: `uv run pytest tests/test_harness/ -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/harness/commands/evidence.py tests/test_harness/test_evidence.py
git commit -m "refactor(evidence): drop V1 register/coverage CLI"
```

---

## Phase 8: Migration script

### Task 8.1: One-shot migration of `source-registry.json` → `evidence.jsonl`

**Files:**
- Create: `src/harness/workflows/evidence/migration.py`
- Create: `tests/test_harness/test_evidence_migration.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_harness/test_evidence_migration.py`:

```python
"""Tests for V1 → V2 migration."""

import json
from pathlib import Path

from harness.commands import evidence
from harness.workflows.evidence.migration import migrate_v1_to_v2
from harness.workflows.evidence.paths import resolve_company_root


def test_migrate_v1_to_v2_dedupes_and_drops_html(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    v1_payload = {
        "root": str(root),
        "ticker": "HOOD",
        "company_name": "Robinhood",
        "slug": "robinhood",
        "sources": [
            {
                "id": "aaa",
                "title": "HOOD 10-K 2025-02-18",
                "ticker": "HOOD",
                "bucket": "sec-filings-annual",
                "source_kind": "sec-10k",
                "status": "downloaded",
                "local_path": "data/sources/10-K/2025-02-18.md",
                "url": None,
                "notes": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "bbb",
                "title": "HOOD 10-K 2025-02-18 (HTML)",
                "ticker": "HOOD",
                "bucket": "sec-filings-annual",
                "source_kind": "sec-10k-html",
                "status": "downloaded",
                "local_path": "data/sources/10-K/2025-02-18.html",
                "url": None,
                "notes": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "ccc",
                "title": "Industry report",
                "ticker": "HOOD",
                "bucket": "external-research",
                "source_kind": "industry-report",
                "status": "discovered",
                "local_path": None,
                "url": "https://example.com/report",
                "notes": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
        ],
        "last_updated": "2025-01-01T00:00:00+00:00",
    }
    paths.source_registry_json.write_text(json.dumps(v1_payload), encoding="utf-8")

    # Create the monolithic file so the ledger path validates.
    md_path = paths.sources_dir / "10-K" / "2025-02-18.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("# 10-K content", encoding="utf-8")

    result = migrate_v1_to_v2(paths)

    assert result["migrated_count"] == 2  # 10-K markdown + industry report; HTML dropped
    entries = [json.loads(line) for line in paths.evidence_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = {entry["category"] for entry in entries}
    assert categories == {"sec-annual", "industry-report"}
    # 10-K points to the existing monolithic file (not re-split)
    annual = next(entry for entry in entries if entry["category"] == "sec-annual")
    assert annual["local_path"] == "data/sources/10-K/2025-02-18.md"
    # Old registry archived
    assert (paths.source_registry_json.with_suffix(".archive.json")).exists()
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_harness/test_evidence_migration.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement migration**

Create `src/harness/workflows/evidence/migration.py`:

- Reads `source-registry.json`.
- Filters out HTML and CSV source kinds.
- Maps `(bucket, source_kind)` → V2 category.
- Calls `upsert_evidence` for each surviving entry, pointing to existing local_path as-is.
- Does NOT re-split or re-download filings. Existing monolithic files stay as-is; the next `collect sec` run will produce per-section files.
- Archives old registry as `.archive.json`.
- Idempotent via deterministic IDs.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/evidence/migration.py tests/test_harness/test_evidence_migration.py
git commit -m "feat(evidence): V1 → V2 migration script"
```

### Task 8.2: Expose `evidence migrate` CLI command

**Files:**
- Modify: `src/harness/commands/evidence.py`
- Modify: `tests/test_harness/test_evidence_v2_cli.py`

- [ ] **Step 1: Add failing test**

Append `test_migrate_cli_command` to `tests/test_harness/test_evidence_v2_cli.py`.

- [ ] **Step 2: Wire `migrate` command**

Add `migrate_command` and dispatch branch.

- [ ] **Step 3: Run tests**

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/harness/commands/evidence.py tests/test_harness/test_evidence_v2_cli.py
git commit -m "feat(evidence): evidence migrate CLI"
```

---

## Phase 9: Downstream integration — analysis context + status

### Task 9.1: `analysis context` reads ledger, filters by `category` — full rewrite of selection and rendering

**Files:**
- Modify: `src/harness/workflows/analysis/context.py`
- Create: `tests/test_harness/test_evidence_v2_downstream.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_harness/test_evidence_v2_downstream.py`:

```python
"""Downstream integration tests for V2 ledger."""

from pathlib import Path

from harness.commands import analysis, evidence
from harness.workflows.evidence.ledger import upsert_evidence
from harness.workflows.evidence.paths import resolve_company_root
from harness.workflows.analysis.context import run_context


def test_analysis_context_v2_filters_by_category(tmp_path: Path) -> None:
    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    filing_dir = paths.sources_dir / "10-K" / "2025-02-18"
    filing_dir.mkdir(parents=True, exist_ok=True)
    (filing_dir / "01-business.md").write_text("# biz", encoding="utf-8")

    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path=str(filing_dir.relative_to(paths.root)),
        url=None, date="2025-02-18", notes=None, collector="sec",
    )

    manifest = run_context(paths, profile_name="default")
    assert {bundle["name"] for bundle in manifest["bundles"]} >= {"business-overview", "competition", "management", "risks", "valuation"}
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Full rewrite of `run_context` and helpers**

Edit `src/harness/workflows/analysis/context.py`:

- Replace `from harness.workflows.evidence.registry import list_sources, utc_now` with `from harness.workflows.evidence.ledger import load_ledger, utc_now`.
- Replace `list_sources(paths)` with `load_ledger(paths)`.
- **Rewrite `_select_sources`** — the current function filters by `bundle.get("buckets")` and `bundle.get("source_kinds")`, and sorts by `(item["bucket"], item["source_kind"], item["title"])`. V2 entries have neither `bucket` nor `source_kind`. Replace with:

```python
def _select_sources(all_sources: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    categories = set(bundle.get("categories", []))
    selected = []
    for entry in all_sources:
        if entry["status"] != "downloaded":
            continue
        if categories and entry.get("category") not in categories:
            continue
        selected.append(entry)
    return sorted(selected, key=lambda item: (item.get("category", ""), item.get("title", "")))
```

- **Rewrite bundle artifact rendering** — the loop that renders per-artifact metadata currently writes `entry['bucket']` and `entry['source_kind']`. Replace with `entry['category']`:

```python
# Old:
f"- bucket: {entry['bucket']}",
f"- source_kind: {entry['source_kind']}",

# New:
f"- category: {entry['category']}",
```

- **Update `included_artifacts` dict** — same: replace `bucket`/`source_kind` fields with `category`.

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/analysis/context.py tests/test_harness/test_evidence_v2_downstream.py
git commit -m "feat(analysis): context reads V2 ledger by category"
```

### Task 9.2: `analysis status` — full rewrite around ledger + audit memos

**Files:**
- Modify: `src/harness/workflows/analysis/status.py`
- Modify: `tests/test_harness/test_evidence_v2_downstream.py`
- Modify: `tests/test_harness/test_evidence.py` (remove/rewrite `test_analysis_status_ignores_generated_indexes_when_advancing_stages`)

This is a full rewrite, not a patch. The current `run_status` is built around V1 concepts throughout:
- `load_registry(paths)` → replaced by `load_ledger(paths)`
- `paths.coverage_json` → coverage is removed; replace with audit memo check
- `coverage_ready` stage gate → replaced by `_audit_says_ready(paths)` scanning `audits/audit-*.md`
- Milestones include `registry` and `coverage` → rename to `ledger` and `audit`
- `_next_step()` suggests `minerva evidence coverage` and `minerva evidence register` → replace with `minerva evidence audit` and `minerva evidence add-source`
- Stage progression logic depends on coverage → rewrite around ledger counts + audit readiness

- [ ] **Step 1: Add failing test**

Append to `tests/test_harness/test_evidence_v2_downstream.py`:

```python
def test_analysis_status_v2_uses_audit_memo_for_readiness(tmp_path: Path) -> None:
    from harness.workflows.analysis.status import run_status

    root = tmp_path / "reports" / "00-companies" / "12-robinhood"
    evidence.init_command(root=str(root), ticker="HOOD", company_name="Robinhood", slug="robinhood")
    paths = resolve_company_root(root)

    # Add some evidence
    upsert_evidence(
        paths, ticker="HOOD", category="sec-annual", status="downloaded",
        title="HOOD 10-K 2025", local_path="data/sources/10-K/2025-02-18",
        url=None, date="2025-02-18", notes=None, collector="sec",
    )
    (paths.sources_dir / "10-K" / "2025-02-18").mkdir(parents=True, exist_ok=True)

    status = run_status(paths)
    assert status["stage"] == "collecting"  # no audit yet
    assert "add-source" in status["next_step"] or "audit" in status["next_step"]
    # Milestones should reference ledger, not registry
    milestone_names = {m["name"] for m in status["milestones"]}
    assert "ledger" in milestone_names
    assert "audit" in milestone_names
    assert "registry" not in milestone_names
    assert "coverage" not in milestone_names

    # Write an audit memo
    paths.audits_dir.mkdir(parents=True, exist_ok=True)
    (paths.audits_dir / "audit-2026-04-22.md").write_text(
        "# Evidence Audit — HOOD\n\nReadiness: ready\n", encoding="utf-8"
    )
    status2 = run_status(paths)
    # With audit ready + sources, should advance past collecting
    assert status2["stage"] != "collecting"
```

- [ ] **Step 2: Full rewrite of `run_status` and `_next_step`**

Edit `src/harness/workflows/analysis/status.py`:

- Replace `from harness.workflows.evidence.registry import load_registry, utc_now` with `from harness.workflows.evidence.ledger import load_ledger, utc_now`.
- Remove `coverage = _load_json(paths.coverage_json)` — coverage no longer exists.
- Replace `registry = load_registry(paths)` / `source_count = len(registry.get("sources", []))` with `ledger = load_ledger(paths)` / `source_count = len(ledger)`.
- Add `_audit_says_ready(paths)` helper that scans `audits/audit-*.md` for a `Readiness: ready` line.
- Rewrite stage transitions: replace `coverage_ready` with `audit_ready`. Stages: `initialized` → `collecting` → `extracting` → `analysis-ready` → `analysis-in-progress` → `memo-in-progress` → `complete`.
- Rewrite milestones: `registry` → `ledger`, `coverage` → `audit`.
- Rewrite `_next_step()`: replace `minerva evidence coverage` with `minerva evidence audit`, replace `minerva evidence register` with `minerva evidence add-source`.

- [ ] **Step 3: Remove/rewrite stale status test**

In `tests/test_harness/test_evidence.py`, remove or xfail `test_analysis_status_ignores_generated_indexes_when_advancing_stages` — it writes `paths.coverage_json` and asserts coverage-based stage transitions that no longer exist.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_harness/test_evidence_v2_downstream.py tests/test_harness/test_evidence.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/workflows/analysis/status.py tests/test_harness/test_evidence_v2_downstream.py tests/test_harness/test_evidence.py
git commit -m "feat(analysis): full status rewrite around V2 ledger + audit memos"
```

---

## Phase 10: Delete YAML profiles, documentation, and smoke test

### Task 10.1: Delete YAML profile files

**Files:**
- Delete: `profiles/evidence/extract/default.yaml`
- Delete: `profiles/evidence/coverage/default.yaml`
- Delete: `profiles/evidence/coverage/test-minimal.yaml`
- Delete: `profiles/analysis/context/default.yaml`

- [ ] **Step 1: Delete files**

```bash
rm profiles/evidence/extract/default.yaml
rm profiles/evidence/coverage/default.yaml
rm profiles/evidence/coverage/test-minimal.yaml
rm profiles/analysis/context/default.yaml
```

- [ ] **Step 2: Run full test suite to confirm nothing breaks**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add -A profiles/
git commit -m "refactor(evidence): delete YAML profiles replaced by constants.py"
```

### Task 10.2: Update docs and add V2 quickstart

**Files:**
- Modify: `docs/INDEX.md`
- Create: `docs/14-evidence-v2-quickstart.md`

- [ ] **Step 1: Add quickstart doc**

Include the three public commands (`init`, `add-source`, `audit`) with examples, the workspace layout, and a migration note.

- [ ] **Step 2: Update index**

- [ ] **Step 3: Commit**

```bash
git add docs/14-evidence-v2-quickstart.md docs/INDEX.md
git commit -m "docs: evidence V2 quickstart"
```

### Task 10.3: End-to-end smoke test

**Files:**
- Modify: `tests/test_harness/test_evidence_v2_cli.py`

- [ ] **Step 1: Add a full-flow smoke test**

Append `test_v2_full_flow_smoke` covering init → collect → audit → status.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_harness/test_evidence_v2_cli.py
git commit -m "test(evidence): V2 end-to-end smoke test"
```

---

## Acceptance Criteria Summary

| Phase | Acceptance |
|---|---|
| 1 | `evidence.jsonl` + `evidence.md` present after init; `audits/`, `plans/` dirs created; `upsert_evidence` deterministic, atomic, idempotent; `constants.py` defines all categories, extraction questions, and context bundles. |
| 2 | `evidence collect sec` downloads per-section files via edgartools structured access; falls back to single-file on error; writes one ledger entry per logical filing; HTML never in ledger. |
| 3 | `evidence inventory` reads `evidence.jsonl`; counts use `ledger_total`; missing-on-disk works for directories. |
| 4 | `evidence extract --profile default` selects by `category` from `constants.py`, concatenates per-section files for input. |
| 5 | `AUDIT_PROMPT_TEMPLATE` matches spec §4.3 verbatim with four placeholders. |
| 6 | `run_audit` writes `audits/audit-YYYY-MM-DD[-scope].md`; SEC metadata only; external full content; LLM call receives well-formed prompt. |
| 7 | `minerva evidence add-source` writes ledger + warns on unknown category; `minerva evidence audit` produces a memo; `register`/`coverage` removed. |
| 8 | `minerva evidence migrate` ingests V1 registry, drops HTML, archives old file. Existing monolithic filings stay as-is (re-collected on next `collect sec`). |
| 9 | `analysis context` and `analysis status` operate on V2 ledger + audit memos. |
| 10 | YAML profiles deleted; docs updated; `uv run pytest` green end-to-end. |
