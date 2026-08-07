"""Bounded Terra selection for summarized morning-brief articles."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL = "gpt-5.6-terra"
THINKING = "high"
CONCURRENCY = 4
MAX_BATCHES = 4
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = REPO_ROOT / "scripts" / "prompts" / "morning_brief_selection.md"

ArticleRecord = dict[str, Any]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def balanced_batches(
    records: Sequence[ArticleRecord], *, max_batches: int = MAX_BATCHES
) -> list[list[ArticleRecord]]:
    """Split ordered records into deterministic batches whose sizes differ by at most one."""
    if max_batches < 1:
        raise ValueError("max_batches must be at least one")
    if not records:
        return []
    batch_count = min(max_batches, len(records))
    base_size, remainder = divmod(len(records), batch_count)
    batches: list[list[ArticleRecord]] = []
    offset = 0
    for index in range(batch_count):
        size = base_size + (1 if index < remainder else 0)
        batches.append(list(records[offset : offset + size]))
        offset += size
    return batches


def parse_batch_selection(
    text: str, records: Sequence[ArticleRecord], *, batch_number: int
) -> list[dict[str, Any]]:
    """Parse one Terra result and ground every development in its input records."""
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"batch {batch_number} result must be a JSON object")
    developments = payload.get("selected_developments")
    if not isinstance(developments, list):
        raise ValueError(f"batch {batch_number} selected_developments must be an array")

    records_by_key = {str(record["article_key"]): record for record in records}
    parsed: list[dict[str, Any]] = []
    for index, development in enumerate(developments, start=1):
        if not isinstance(development, dict):
            raise ValueError(
                f"batch {batch_number} development {index} must be an object"
            )
        section = development.get("section")
        if section not in {"portfolio_watchlist", "worth_knowing"}:
            raise ValueError(
                f"batch {batch_number} development {index} has an invalid section"
            )
        takeaway = development.get("takeaway")
        materiality = development.get("materiality")
        keys = development.get("article_keys")
        if not isinstance(takeaway, str) or not takeaway.strip():
            raise ValueError(
                f"batch {batch_number} development {index} needs a takeaway"
            )
        if not isinstance(materiality, str) or not materiality.strip():
            raise ValueError(
                f"batch {batch_number} development {index} needs materiality"
            )
        if (
            not isinstance(keys, list)
            or not keys
            or any(not isinstance(key, str) or not key for key in keys)
        ):
            raise ValueError(
                f"batch {batch_number} development {index} needs article_keys"
            )
        unique_keys = list(dict.fromkeys(keys))
        unknown = [key for key in unique_keys if key not in records_by_key]
        if unknown:
            raise ValueError(
                f"batch {batch_number} returned unknown article key(s): "
                + ", ".join(unknown)
            )
        parsed.append(
            {
                "article_keys": unique_keys,
                "batch": batch_number,
                "materiality": materiality.strip(),
                "section": section,
                "takeaway": takeaway.strip(),
                # URLs are derived from the keyed SQLite records rather than trusted
                # from model-generated text.
                "urls": [str(records_by_key[key]["url"]) for key in unique_keys],
            }
        )
    return parsed


def select_articles_from_handoff(
    handoff_path: Path,
    *,
    prompt_path: Path = DEFAULT_PROMPT,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    """Run one temporary extract-files selection pass and write its grounded shortlist."""
    handoff = _load_handoff(handoff_path)
    records = _read_window_records(
        Path(handoff["db"]), handoff["window_start"], handoff["window_end"]
    )
    batches = balanced_batches(records)
    identities = _portfolio_identities(
        Path(handoff["holdings_path"]), Path(handoff["watchlist_path"])
    )

    developments: list[dict[str, Any]] = []
    if batches:
        with tempfile.TemporaryDirectory(prefix="minerva-terra-selection-") as raw_tmp:
            temp_root = Path(raw_tmp)
            batch_paths = _write_batches(temp_root, batches, identities)
            result_root = temp_root / "results"
            command = [
                "uv",
                "run",
                "minerva",
                "extract-files",
                "--questions-file",
                str(prompt_path.resolve()),
            ]
            for batch_path in batch_paths:
                command.extend(["--files", str(batch_path)])
            command.extend(
                [
                    "--out",
                    str(result_root),
                    "--model",
                    MODEL,
                    "--thinking",
                    THINKING,
                    "--concurrency",
                    str(CONCURRENCY),
                ]
            )
            completed = command_runner(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                diagnostic = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    f"Terra extract-files failed with status {completed.returncode}: "
                    f"{diagnostic[-1000:]}"
                )
            outputs = _validated_outputs(result_root / "manifest.json", batch_paths)
            for batch_number, (batch, output) in enumerate(
                zip(batches, outputs, strict=True), start=1
            ):
                developments.extend(
                    parse_batch_selection(
                        output.read_text(encoding="utf-8"),
                        batch,
                        batch_number=batch_number,
                    )
                )

    selected_keys = {
        key for development in developments for key in development["article_keys"]
    }
    selected_articles = [
        record for record in records if record["article_key"] in selected_keys
    ]
    source_counts: dict[str, int] = {}
    for record in records:
        source = str(record["source"])
        source_counts[source] = source_counts.get(source, 0) + 1

    shortlist = {
        "counts": {
            "batches": len(batches),
            "excluded_articles": len(records) - len(selected_articles),
            "input_articles": len(records),
            "selected_articles": len(selected_articles),
            "selected_developments": len(developments),
            "sources": dict(sorted(source_counts.items())),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "concurrency": CONCURRENCY,
            "database": str(Path(handoff["db"])),
            "extractor": "uv run minerva extract-files",
            "model": MODEL,
            "prompt": str(prompt_path.resolve()),
            "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
            "thinking": THINKING,
            "window_end": handoff["window_end"],
            "window_start": handoff["window_start"],
        },
        "schema_version": 1,
        "selected_articles": selected_articles,
        "selected_developments": developments,
        "status": "ready",
    }
    _write_json_atomic(Path(handoff["article_shortlist"]), shortlist)
    return shortlist


def _load_handoff(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required_strings = (
        "article_shortlist",
        "db",
        "holdings_path",
        "watchlist_path",
        "window_end",
        "window_start",
    )
    if not isinstance(payload, dict) or payload.get("status") != "ready":
        raise ValueError("synthesis handoff is not ready")
    missing = [
        key
        for key in required_strings
        if not isinstance(payload.get(key), str) or not payload[key]
    ]
    if missing:
        raise ValueError("synthesis handoff has invalid fields: " + ", ".join(missing))
    return payload


def _read_window_records(
    db: Path, window_start: str, window_end: str
) -> list[ArticleRecord]:
    lower = _epoch(window_start)
    upper = _epoch(window_end)
    if lower >= upper:
        raise ValueError("selection window must have a positive duration")
    uri = f"{db.resolve().as_uri()}?mode=rw"
    with sqlite3.connect(uri, uri=True, timeout=30) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT article_key, url, title, source, published_at, summary "
            "FROM news WHERE trim(content) <> '' "
            "AND published_at >= ? AND published_at < ? "
            "ORDER BY published_at, article_key",
            (lower, upper),
        ).fetchall()
    incomplete = [row[0] for row in rows if row[5] is None or not str(row[5]).strip()]
    if incomplete:
        raise ValueError(
            f"selection requires complete summaries; {len(incomplete)} article(s) are blank"
        )
    return [
        {
            "article_key": str(row[0]),
            "published_at": int(row[4]),
            "source": str(row[3]),
            "summary": str(row[5]).strip(),
            "title": str(row[2]),
            "url": str(row[1]),
        }
        for row in rows
    ]


def _epoch(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid handoff timestamp: {value}") from exc


def _portfolio_identities(holdings_path: Path, watchlist_path: Path) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for kind, path in (("holding", holdings_path), ("watchlist", watchlist_path)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"portfolio identity file must be an array: {path}")
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError(f"portfolio identity row must be an object: {path}")
            security_id = str(row.get("security_id") or "").strip()
            ticker = str(row.get("ticker") or security_id).strip()
            if not security_id and not ticker:
                continue
            identities.append(
                {
                    "company_name": str(row.get("company_name") or ticker),
                    "kind": kind,
                    "security_id": security_id or ticker,
                    "ticker": ticker or security_id,
                }
            )
    return sorted(
        identities, key=lambda row: (row["kind"], row["security_id"], row["ticker"])
    )


def _write_batches(
    temp_root: Path,
    batches: Sequence[Sequence[ArticleRecord]],
    identities: Sequence[dict[str, str]],
) -> list[Path]:
    paths: list[Path] = []
    for number, batch in enumerate(batches, start=1):
        path = temp_root / f"batch-{number:03d}.json"
        path.write_text(
            json.dumps(
                {"articles": batch, "portfolio_watchlist": identities},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _validated_outputs(manifest_path: Path, batch_paths: Sequence[Path]) -> list[Path]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or len(entries) != len(batch_paths):
        raise ValueError("extract-files manifest does not account for every batch")
    by_source: dict[Path, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") != "ok":
            raise ValueError("extract-files manifest contains an unsuccessful batch")
        source = Path(str(entry.get("source") or "")).resolve()
        if source in by_source:
            raise ValueError("extract-files manifest contains a duplicate batch")
        by_source[source] = entry
    expected = [path.resolve() for path in batch_paths]
    if set(by_source) != set(expected):
        raise ValueError("extract-files manifest batch set does not match its inputs")
    outputs: list[Path] = []
    for source in expected:
        output = Path(str(by_source[source].get("output") or ""))
        if not output.is_file():
            raise ValueError(f"extract-files result is missing for {source.name}")
        outputs.append(output)
    return outputs


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
    temporary.replace(path)
