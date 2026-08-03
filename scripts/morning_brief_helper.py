#!/usr/bin/env python3
"""Deterministic bookkeeping for the morning-brief shell orchestrator."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time as time_module
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")
IR_BATCH_SIZE = 10
_PLACEHOLDER = re.compile(r"{{([A-Z_]+)}}")


def parse_run_date(value: str) -> date:
    """Parse a strict ISO calendar date."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"RUN_DATE must be an ISO date (YYYY-MM-DD): {value}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"RUN_DATE must be an ISO date (YYYY-MM-DD): {value}")
    return parsed


def brief_window(run_date: date) -> tuple[datetime, datetime]:
    """Return the fixed [previous-date 04:00, run-date 04:00) ET window."""
    start = datetime.combine(
        run_date - timedelta(days=1), time(hour=4), tzinfo=MARKET_TIMEZONE
    )
    end = datetime.combine(run_date, time(hour=4), tzinfo=MARKET_TIMEZONE)
    return start, end


def render_prompt(template: str, replacements: dict[str, str]) -> str:
    """Render known placeholders once without interpreting replacement text."""
    return _PLACEHOLDER.sub(
        lambda match: replacements.get(match.group(1), match.group(0)), template
    )


def build_ir_batches(
    universe: list[dict[str, Any]], registry: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Join current-universe companies to registry feed metadata and chunk them."""
    registry_by_id = {entry["security_id"]: entry for entry in registry}
    companies: list[dict[str, Any]] = []
    for security in sorted(universe, key=lambda row: row["security_id"]):
        security_id = security["security_id"]
        registry_entry = registry_by_id.get(security_id)
        if registry_entry is None:
            continue
        feeds = [
            {
                "format": str(feed.get("format") or "html"),
                "name": str(feed.get("name") or ""),
                "url": feed["url"],
            }
            for feed in registry_entry["feeds"]
            if feed.get("url")
        ]
        if not feeds:
            continue
        companies.append(
            {
                "company_name": str(
                    security.get("company_name")
                    or registry_entry.get("company_name")
                    or security_id
                ),
                "feeds": feeds,
                "security_id": security_id,
                "source_id": f"ir-{security_id}",
                "ticker": str(security.get("ticker") or security_id),
            }
        )
    return [
        companies[offset : offset + IR_BATCH_SIZE]
        for offset in range(0, len(companies), IR_BATCH_SIZE)
    ]


def window_evidence(
    db: Path, run_date: date, *, skipped: bool = False
) -> dict[str, Any]:
    """Count full-text news inside the fixed evidence window."""
    start, end = brief_window(run_date)
    lower = int(start.timestamp())
    upper = int(end.timestamp())
    result: dict[str, Any] = {
        "eligible_rows": 0,
        "lower_epoch": lower,
        "null_or_blank_summaries": 0,
        "phase": "window-evidence",
        "run_date": run_date.isoformat(),
        "sources": {},
        "status": "skipped" if skipped else "ok",
        "upper_epoch": upper,
        "window_end": end.isoformat(),
        "window_start": start.isoformat(),
    }
    if skipped or not db.is_file():
        return result

    # Use a read-write-capable handle with query-only enforcement. A `mode=ro`
    # connection can transiently fail while the last parallel collector closes
    # a WAL database and SQLite recreates/removes its shared-memory files.
    uri = f"{db.absolute().as_uri()}?mode=rw"
    deadline = time_module.monotonic() + 30
    delay = 0.1
    while True:
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=30)
            break
        except sqlite3.OperationalError:
            if time_module.monotonic() >= deadline:
                raise
            time_module.sleep(delay)
            delay = min(delay * 2, 1.0)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA query_only = ON")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='news'"
        ).fetchone()
        if table is not None:
            predicate = "trim(content) <> '' AND published_at >= ? AND published_at < ?"
            params = (lower, upper)
            result["eligible_rows"] = connection.execute(
                f"SELECT COUNT(*) FROM news WHERE {predicate}", params
            ).fetchone()[0]
            result["null_or_blank_summaries"] = connection.execute(
                f"SELECT COUNT(*) FROM news WHERE {predicate} "
                "AND (summary IS NULL OR trim(summary) = '')",
                params,
            ).fetchone()[0]
            result["sources"] = dict(
                connection.execute(
                    f"SELECT source, COUNT(*) FROM news WHERE {predicate} "
                    "GROUP BY source ORDER BY source",
                    params,
                ).fetchall()
            )
    finally:
        connection.close()
    return result


def collector_summary(launched_path: Path, artifact_root: Path) -> dict[str, Any]:
    """Aggregate per-collector status artifacts in launch order."""
    launched = (
        launched_path.read_text(encoding="utf-8").splitlines()
        if launched_path.is_file()
        else []
    )
    rows = []
    for source_id in launched:
        status_path = artifact_root / source_id / "status.json"
        if status_path.is_file():
            row = json.loads(status_path.read_text(encoding="utf-8"))
        else:
            row = {
                "error": "collector exited without a status artifact",
                "exit_status": -1,
                "source_id": source_id,
                "status": "failed",
            }
        rows.append(row)
    failures = [row for row in rows if row.get("status") != "ok"]
    return {
        "failed": len(failures),
        "failures": failures,
        "phase": "collectors",
        "status": "degraded" if failures else "ok",
        "succeeded": len(rows) - len(failures),
        "total": len(rows),
    }


def synthesis_handoff(
    *,
    run_date: date,
    db: Path,
    prepared_evidence: Path,
    report_output: Path,
    slack_brief_output: Path,
    evidence_stats: Path,
    instructions: Path,
) -> dict[str, Any]:
    """Build the neutral synthesis handoff contract."""
    start, end = brief_window(run_date)
    return {
        "date": run_date.isoformat(),
        "db": str(db),
        "evidence_stats": str(evidence_stats),
        "instructions": str(instructions),
        "prepared_evidence": str(prepared_evidence),
        "report_output": str(report_output),
        "slack_brief_output": str(slack_brief_output),
        "steps": [
            "Query news in the fixed [previous-run 04:00, run-date 04:00) "
            "America/New_York window whose summary is NULL or blank.",
            "Pipe each row's content through `minerva summarize`; retain generated "
            "summaries until all calls succeed.",
            "Persist summaries with parameter binding in one safe transaction, "
            "updating only still-blank rows.",
            "Synthesize notes/morning-brief-report.md and notes/slack-brief.md from "
            "prepared evidence and news in the fixed handoff window.",
        ],
        "status": "ready",
        "window_end": end.isoformat(),
        "window_start": start.isoformat(),
    }


def check_manifest(path: Path) -> None:
    """Require successful prepared-evidence inputs."""
    sources = json.loads(path.read_text(encoding="utf-8")).get("sources", {})
    required = ("filings", "earnings", "market", "prep")
    missing = [name for name in required if name not in sources]
    blocking = [
        name for name in required if sources.get(name, {}).get("status") == "error"
    ]
    if missing:
        raise ValueError(f"missing manifest source entries: {', '.join(missing)}")
    if blocking:
        raise ValueError(
            f"blocking morning-brief collection errors: {', '.join(blocking)}"
        )


def _load_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected a JSON array: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require(command: str, args: list[str], count: int) -> None:
    if len(args) != count:
        raise ValueError(f"{command} expects {count} arguments; received {len(args)}")


def _render_prompt_command(args: list[str]) -> None:
    _require("render-prompt", args, 13)
    (
        template,
        run_date,
        source_name,
        source_id,
        url,
        source_root,
        db,
        news_exist_command,
        news_ingest_command,
        portfolio_tickers,
        collection_scope,
        candidate_file,
        lookup_file,
    ) = args
    replacements = {
        "CANDIDATE_FILE": candidate_file,
        "COLLECT_SCOPE": collection_scope,
        "DATE": run_date,
        "INVEST_DB": db,
        "IR_COMPANIES_JSON": collection_scope,
        "LOOKUP_FILE": lookup_file,
        "NEWS_EXIST_COMMAND": news_exist_command,
        "NEWS_INGEST_COMMAND": news_ingest_command,
        "PORTFOLIO_TICKERS": portfolio_tickers,
        "SOURCE_ID": source_id,
        "SOURCE_NAME": source_name,
        "SOURCE_ROOT": source_root,
        "URL": url,
    }
    text = Path(template).read_text(encoding="utf-8")
    sys.stdout.write(render_prompt(text, replacements))


def _main(command: str, args: list[str]) -> None:
    if command == "previous-date":
        _require(command, args, 1)
        print((parse_run_date(args[0]) - timedelta(days=1)).isoformat())
    elif command == "write-status":
        _require(command, args, 6)
        output, phase, status, exit_status, stdout_path, stderr_path = args
        payload: dict[str, Any] = {
            "exit_status": int(exit_status),
            "phase": phase,
            "status": status,
        }
        if stdout_path:
            payload["stdout"] = stdout_path
        if stderr_path:
            payload["stderr"] = stderr_path
        _write_json(Path(output), payload)
    elif command == "window-evidence":
        if len(args) not in (3, 4) or (len(args) == 4 and args[3] != "--skipped"):
            raise ValueError("window-evidence expects DB RUN_DATE OUTPUT [--skipped]")
        db, run_date, output = args[:3]
        _write_json(
            Path(output),
            window_evidence(
                Path(db), parse_run_date(run_date), skipped=len(args) == 4
            ),
        )
    elif command == "render-prompt":
        _render_prompt_command(args)
    elif command == "collector-status":
        _require(command, args, 9)
        output, source_id, source_name, url, session_id, status, exit_status, log, size = args
        _write_json(
            Path(output),
            {
                "exit_status": int(exit_status),
                "log": log,
                "openclaw_output_bytes": int(size),
                "session_id": session_id,
                "source_id": source_id,
                "source_name": source_name,
                "status": status,
                "url": url,
            },
        )
    elif command == "ir-batches":
        _require(command, args, 2)
        for batch in build_ir_batches(_load_array(Path(args[0])), _load_array(Path(args[1]))):
            print(json.dumps(batch, separators=(",", ":"), sort_keys=True))
    elif command == "collector-summary":
        _require(command, args, 3)
        _write_json(
            Path(args[2]), collector_summary(Path(args[0]), Path(args[1]))
        )
    elif command == "manifest-check":
        _require(command, args, 1)
        check_manifest(Path(args[0]))
    elif command == "write-handoff":
        _require(command, args, 8)
        output, run_date, db, prepared, report, slack, evidence, instructions = args
        _write_json(
            Path(output),
            synthesis_handoff(
                run_date=parse_run_date(run_date),
                db=Path(db),
                prepared_evidence=Path(prepared),
                report_output=Path(report),
                slack_brief_output=Path(slack),
                evidence_stats=Path(evidence),
                instructions=Path(instructions),
            ),
        )
    else:
        raise ValueError(f"unknown command: {command}")


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        print("a helper command is required", file=sys.stderr)
        return 2
    try:
        _main(values[0], values[1:])
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
