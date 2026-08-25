#!/usr/bin/env python3
"""Deterministic bookkeeping for the morning-brief shell orchestrator."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import signal
import sqlite3
import subprocess
import sys
import time as time_module
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")
IR_BATCH_SIZE = 10
_PLACEHOLDER = re.compile(r"{{([A-Z_]+)}}")
_BROWSER_ALIAS = re.compile(r"^[* ]\s+(t[0-9]+)\s", re.MULTILINE)
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,99}$")
LEASE_MANIFEST_VERSION = 1
COORDINATOR_MANIFEST_VERSION = 1
LEASED_BROWSER_COMMANDS = frozenset(
    {
        "ask",
        "click",
        "describe",
        "dialog",
        "diff",
        "eval",
        "extract",
        "fill",
        "inspect",
        "open",
        "snapshot",
        "status",
        "type",
        "upload",
        "wait",
    }
)


class OpenClawSuccessStopReason(StrEnum):
    COMPLETED = "completed"
    END_TURN = "end_turn"
    STOP = "stop"


class CollectorReportField(StrEnum):
    STATUS = "status"
    INSERTED = "inserted"
    UPDATED = "updated"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    FAILED = "failed"


class CollectorStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"


class ValidationOutcome(StrEnum):
    INVALID_JSON = "invalid_json"
    STATUS_ERROR = "status_error"
    INVALID_RESULT = "invalid_result"
    ABORTED = "aborted"
    AGENT_ERROR = "agent_error"
    TIMEOUT = "timeout"
    ERROR_PAYLOAD = "error_payload"
    INCOMPLETE = "incomplete"
    INVALID_REPORT = "invalid_report"
    INVALID_COUNTS = "invalid_counts"
    COLLECTOR_FAILED = "collector_failed"
    OK = "ok"


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


def validate_collector_report(text: str) -> ValidationOutcome:
    """Validate one crawler's compact final report."""
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        return ValidationOutcome.INVALID_REPORT
    if not isinstance(report, dict) or set(report) != set(CollectorReportField):
        return ValidationOutcome.INVALID_REPORT
    try:
        status = CollectorStatus(report[CollectorReportField.STATUS])
    except (TypeError, ValueError):
        return ValidationOutcome.INVALID_REPORT
    counts = [
        report[field]
        for field in CollectorReportField
        if field is not CollectorReportField.STATUS
    ]
    if any(type(count) is not int or count < 0 for count in counts):
        return ValidationOutcome.INVALID_COUNTS
    if (
        status is not CollectorStatus.OK
        or report[CollectorReportField.FAILED] != 0
    ):
        return ValidationOutcome.COLLECTOR_FAILED
    return ValidationOutcome.OK


def validate_openclaw_result(text: str) -> ValidationOutcome:
    """Return a safe outcome code without exposing agent payload text."""
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return ValidationOutcome.INVALID_JSON
    if not isinstance(envelope, dict) or envelope.get("status") != CollectorStatus.OK:
        return ValidationOutcome.STATUS_ERROR
    result = envelope.get("result")
    if not isinstance(result, dict):
        return ValidationOutcome.INVALID_RESULT
    meta = result.get("meta")
    payloads = result.get("payloads")
    if not isinstance(meta, dict) or not isinstance(payloads, list):
        return ValidationOutcome.INVALID_RESULT
    if meta.get("aborted") is True:
        return ValidationOutcome.ABORTED
    if meta.get("error") is not None:
        return ValidationOutcome.AGENT_ERROR
    if meta.get("timeoutPhase") is not None:
        return ValidationOutcome.TIMEOUT
    if any(
        isinstance(payload, dict) and payload.get("isError") is True
        for payload in payloads
    ):
        return ValidationOutcome.ERROR_PAYLOAD
    try:
        OpenClawSuccessStopReason(meta.get("stopReason"))
    except (TypeError, ValueError):
        return ValidationOutcome.INCOMPLETE
    if len(payloads) != 1 or not isinstance(payloads[0], dict):
        return ValidationOutcome.INVALID_REPORT
    report_text = payloads[0].get("text")
    if not isinstance(report_text, str):
        return ValidationOutcome.INVALID_REPORT
    return validate_collector_report(report_text)


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


def parse_browser_aliases(text: str) -> set[str]:
    """Parse aliases from the stable `browser tabs` table format."""
    return set(_BROWSER_ALIAS.findall(text))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_create_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish one immutable JSON artifact without overwriting it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lease_lock(manifest_path: Path) -> Iterator[None]:
    lock_path = manifest_path.parent / ".allocation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_lease_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("version") != LEASE_MANIFEST_VERSION
        or type(payload.get("owner_pid")) is not int
        or not isinstance(payload.get("leases"), list)
    ):
        raise ValueError(f"invalid browser lease manifest: {path}")
    return payload


def initialize_lease_manifest(path: Path, owner_pid: int) -> None:
    """Create one run-scoped browser lease manifest."""
    if owner_pid <= 0:
        raise ValueError("browser lease owner PID must be positive")
    with _lease_lock(path):
        if path.exists():
            raise ValueError(f"browser lease manifest already exists: {path}")
        _atomic_write_json(
            path,
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "leases": [],
                "owner_pid": owner_pid,
                "version": LEASE_MANIFEST_VERSION,
            },
        )


def _browser_command() -> list[str]:
    command = shlex.split(os.environ.get("MINERVA_BROWSER_COMMAND", "browser"))
    if not command:
        raise ValueError("MINERVA_BROWSER_COMMAND must not be empty")
    return command


def _call_browser(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_browser_command(), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _snapshot_browser_aliases() -> set[str]:
    result = _call_browser(["tabs"])
    if result.returncode != 0:
        raise ValueError("browser_tabs_failed")
    return parse_browser_aliases(result.stdout)


def allocate_browser_lease(path: Path, source_id: str, url: str) -> str:
    """Open exactly one serialized browser window and record its unique alias."""
    with _lease_lock(path):
        manifest = _load_lease_manifest(path)
        if any(
            lease.get("source_id") == source_id and lease.get("closed_at") is None
            for lease in manifest["leases"]
        ):
            raise ValueError(f"source already has an open browser lease: {source_id}")
        before = _snapshot_browser_aliases()
        opened = _call_browser(["open", url, "--new", "--window"])
        after = _snapshot_browser_aliases()
        new_aliases = after - before
        if len(new_aliases) != 1:
            raise ValueError(
                "browser allocation requires exactly one new alias; "
                f"observed {len(new_aliases)}"
            )
        alias = next(iter(new_aliases))
        attempt = 1 + sum(
            lease.get("source_id") == source_id for lease in manifest["leases"]
        )
        manifest["leases"].append(
            {
                "alias": alias,
                "allocated_at": datetime.now(timezone.utc).isoformat(),
                "attempt": attempt,
                "closed_at": None,
                "source_id": source_id,
                "url": url,
            }
        )
        _atomic_write_json(path, manifest)
        if opened.returncode != 0:
            _close_browser_lease_locked(path, manifest, source_id, alias)
            raise ValueError("browser_open_failed")
        return alias


def _find_open_lease(
    manifest: dict[str, Any], source_id: str, alias: str
) -> dict[str, Any]:
    matches = [
        lease
        for lease in manifest["leases"]
        if lease.get("source_id") == source_id
        and lease.get("alias") == alias
        and lease.get("closed_at") is None
    ]
    if len(matches) != 1:
        raise ValueError(f"no unique open lease for {source_id}:{alias}")
    return matches[0]


def _close_browser_lease_locked(
    path: Path, manifest: dict[str, Any], source_id: str, alias: str
) -> None:
    lease = _find_open_lease(manifest, source_id, alias)
    aliases = _snapshot_browser_aliases()
    if alias in aliases:
        closed = _call_browser(["close", alias])
        if closed.returncode != 0:
            raise ValueError(f"browser_close_failed:{alias}")
    lease["closed_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(path, manifest)


def close_browser_lease(path: Path, source_id: str, alias: str) -> None:
    """Close one exact recorded lease, never a baseline alias."""
    with _lease_lock(path):
        manifest = _load_lease_manifest(path)
        _close_browser_lease_locked(path, manifest, source_id, alias)


def cleanup_browser_leases(path: Path, *, remove: bool = False) -> None:
    """Close all still-open aliases recorded by this run."""
    if not path.is_file():
        return
    with _lease_lock(path):
        manifest = _load_lease_manifest(path)
        open_leases = [
            lease for lease in manifest["leases"] if lease.get("closed_at") is None
        ]
        if not open_leases:
            if remove:
                path.unlink(missing_ok=True)
            return
        aliases = _snapshot_browser_aliases()
        errors: list[str] = []
        for lease in open_leases:
            alias = lease.get("alias")
            if not isinstance(alias, str):
                errors.append("invalid_alias")
                continue
            if alias in aliases:
                result = _call_browser(["close", alias])
                if result.returncode != 0:
                    errors.append(alias)
                    continue
                aliases.remove(alias)
            lease["closed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(path, manifest)
        if errors:
            raise ValueError(f"browser lease cleanup failed: {','.join(errors)}")
        if remove:
            path.unlink(missing_ok=True)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_stale_lease_manifests(directory: Path) -> list[Path]:
    """Recover only this helper's manifests whose owning process is gone."""
    recovered: list[Path] = []
    if not directory.is_dir():
        return recovered
    for path in sorted(directory.glob("lease-*.json")):
        try:
            manifest = _load_lease_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if _pid_exists(manifest["owner_pid"]):
            continue
        cleanup_browser_leases(path, remove=True)
        recovered.append(path)
    return recovered


def render_leased_browser_prompt(
    template: str, manifest: Path, source_id: str, alias: str
) -> str:
    """Bind a browser crawler prompt to one manifest-checked command."""
    command = shlex.join(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "leased-browser",
            str(manifest),
            source_id,
            alias,
        ]
    )
    if template.count("{{BROWSER_ALIAS}}") != 1:
        raise ValueError("browser prompt must contain one BROWSER_ALIAS placeholder")
    if template.count("{{LEASED_BROWSER_COMMAND}}") < 1:
        raise ValueError("browser prompt is missing LEASED_BROWSER_COMMAND")
    return template.replace("{{BROWSER_ALIAS}}", alias).replace(
        "{{LEASED_BROWSER_COMMAND}}", command
    )


def run_leased_browser_command(
    path: Path, source_id: str, alias: str, args: Sequence[str]
) -> int:
    """Enforce one recorded alias and forbid tab lifecycle operations."""
    if not args or args[0] not in LEASED_BROWSER_COMMANDS:
        raise ValueError("leased browser command is not allowed")
    forbidden = ("--tab", "--new", "--window")
    if any(
        arg == option or arg.startswith(f"{option}=")
        for arg in args
        for option in forbidden
    ):
        raise ValueError("leased browser command contains a forbidden option")
    # Hold the cross-run lock only for ownership validation. Browser work on
    # distinct aliases remains parallel; lifecycle commands run only after the
    # owning child has completed (or after the parent has been terminated).
    with _lease_lock(path):
        manifest = _load_lease_manifest(path)
        _find_open_lease(manifest, source_id, alias)
    result = subprocess.run([*_browser_command(), *args, "--tab", alias])
    return result.returncode


def initialize_coordinator_jobs(path: Path, max_concurrent: int) -> None:
    if max_concurrent <= 0:
        raise ValueError("max_concurrent must be positive")
    _atomic_write_json(
        path,
        {
            "jobs": [],
            "max_concurrent": max_concurrent,
            "version": COORDINATOR_MANIFEST_VERSION,
        },
    )


def _load_coordinator_jobs(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("version") != COORDINATOR_MANIFEST_VERSION
        or not isinstance(payload.get("jobs"), list)
    ):
        raise ValueError(f"invalid coordinator jobs manifest: {path}")
    return payload


def append_coordinator_job(path: Path, job: dict[str, Any]) -> None:
    payload = _load_coordinator_jobs(path)
    source_id = job["source_id"]
    if any(existing.get("source_id") == source_id for existing in payload["jobs"]):
        raise ValueError(f"duplicate coordinator source id: {source_id}")
    payload["jobs"].append(job)
    _atomic_write_json(path, payload)


def record_coordinator_result(
    jobs_path: Path,
    result_dir: Path,
    source_id: str,
    attempts: int,
    status: str,
    error: str,
) -> None:
    jobs = _load_coordinator_jobs(jobs_path)["jobs"]
    matches = [job for job in jobs if job.get("source_id") == source_id]
    if len(matches) != 1:
        raise ValueError(f"unknown coordinator source id: {source_id}")
    job = matches[0]
    max_attempts = job.get("max_attempts")
    if (
        attempts <= 0
        or type(max_attempts) is not int
        or attempts > max_attempts
        or status not in {CollectorStatus.OK, CollectorStatus.FAILED}
        or (status == CollectorStatus.OK and bool(error))
        or (status == CollectorStatus.FAILED and not error)
    ):
        raise ValueError("invalid coordinator result")
    if error and not _SAFE_ERROR.fullmatch(error):
        raise ValueError("invalid coordinator error code")
    status_path = result_dir / source_id / "status.json"
    if status_path.exists():
        raise ValueError(f"coordinator result already recorded: {source_id}")
    log_path = Path(job["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"finished_at: {datetime.now(timezone.utc).isoformat()}\n")
        log_file.write(f"status: {status}\n")
        log_file.write(f"exit_status: {0 if status == CollectorStatus.OK else 1}\n")
        log_file.write(f"attempts: {attempts}\n")
        if error:
            log_file.write(f"error: {error}\n")
        log_file.write("note: crawler output discarded to prevent article-body persistence\n")
    try:
        _atomic_create_json(
            status_path,
            {
                "attempts": attempts,
                "error": error or None,
                "exit_status": 0 if status == CollectorStatus.OK else 1,
                "log": job["log_file"],
                "session_id": f"coordinator:{source_id}:{attempts}",
                "source_id": source_id,
                "source_name": job["source_name"],
                "status": status,
                "url": job["url"],
            },
        )
    except FileExistsError as exc:
        raise ValueError(f"coordinator result already recorded: {source_id}") from exc


def finalize_coordinator_results(jobs_path: Path, result_dir: Path) -> None:
    """Materialize failure statuses for jobs the parent did not record."""
    for job in _load_coordinator_jobs(jobs_path)["jobs"]:
        status_path = result_dir / job["source_id"] / "status.json"
        if status_path.is_file():
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                status_path.unlink(missing_ok=True)
            else:
                if _validate_coordinator_status(job, payload):
                    continue
                status_path.unlink(missing_ok=True)
        try:
            record_coordinator_result(
                jobs_path,
                result_dir,
                job["source_id"],
                1,
                CollectorStatus.FAILED,
                "coordinator_failed",
            )
        except ValueError:
            # A continuation can win the atomic create between the existence
            # check and finalization after a timeout or signal. Accept only its
            # fully valid artifact; otherwise preserve the validation failure.
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise
            if not _validate_coordinator_status(job, payload):
                raise


def _validate_coordinator_envelope(
    text: str, expected: int
) -> tuple[ValidationOutcome, bool]:
    """Validate a final envelope or the exact yielded/paused dispatch shape."""
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return ValidationOutcome.INVALID_JSON, False
    if not isinstance(envelope, dict) or envelope.get("status") != CollectorStatus.OK:
        return ValidationOutcome.STATUS_ERROR, False
    result = envelope.get("result")
    if not isinstance(result, dict):
        return ValidationOutcome.INVALID_RESULT, False
    meta, payloads = result.get("meta"), result.get("payloads")
    if not isinstance(meta, dict) or not isinstance(payloads, list):
        return ValidationOutcome.INVALID_RESULT, False
    if meta.get("aborted") is not False:
        outcome = (
            ValidationOutcome.ABORTED
            if meta.get("aborted") is True
            else ValidationOutcome.INVALID_RESULT
        )
        return outcome, False
    if meta.get("error") is not None or meta.get("failureSignal") is not None:
        return ValidationOutcome.AGENT_ERROR, False
    if meta.get("timeoutPhase") is not None:
        return ValidationOutcome.TIMEOUT, False
    if any(
        isinstance(payload, dict) and payload.get("isError") is True
        for payload in payloads
    ):
        return ValidationOutcome.ERROR_PAYLOAD, False

    yielded = meta.get("yielded")
    liveness = meta.get("livenessState")
    if yielded is True or liveness == "paused":
        if (
            yielded is not True
            or liveness != "paused"
            or meta.get("stopReason") != OpenClawSuccessStopReason.END_TURN
            or payloads != []
        ):
            return ValidationOutcome.INVALID_RESULT, False
        return ValidationOutcome.OK, True

    if yielded not in (None, False) or liveness != "working":
        return ValidationOutcome.INVALID_RESULT, False
    try:
        OpenClawSuccessStopReason(meta.get("stopReason"))
    except (TypeError, ValueError):
        return ValidationOutcome.INCOMPLETE, False
    if len(payloads) != 1 or not isinstance(payloads[0], dict):
        return ValidationOutcome.INVALID_REPORT, False
    try:
        report = json.loads(payloads[0].get("text", ""))
    except (json.JSONDecodeError, TypeError):
        return ValidationOutcome.INVALID_REPORT, False
    if report != {"status": "ok", "completed": expected}:
        return ValidationOutcome.INVALID_REPORT, False
    return ValidationOutcome.OK, False


def validate_coordinator_result(text: str, expected: int) -> ValidationOutcome:
    """Validate one final or yielded OpenClaw coordinator envelope."""
    return _validate_coordinator_envelope(text, expected)[0]


def _validate_coordinator_status(job: dict[str, Any], payload: Any) -> bool:
    if not isinstance(payload, dict) or set(payload) != {
        "attempts",
        "error",
        "exit_status",
        "log",
        "session_id",
        "source_id",
        "source_name",
        "status",
        "url",
    }:
        return False
    attempts = payload["attempts"]
    if type(attempts) is not int or attempts <= 0:
        return False
    max_attempts = job.get("max_attempts")
    if type(max_attempts) is not int or attempts > max_attempts:
        return False
    if (
        payload["source_id"] != job.get("source_id")
        or payload["source_name"] != job.get("source_name")
        or payload["url"] != job.get("url")
        or payload["log"] != job.get("log_file")
        or payload["session_id"]
        != f"coordinator:{job.get('source_id')}:{attempts}"
    ):
        return False
    status = payload["status"]
    error = payload["error"]
    if status == CollectorStatus.OK:
        return payload["exit_status"] == 0 and error is None
    return (
        status == CollectorStatus.FAILED
        and payload["exit_status"] == 1
        and isinstance(error, str)
        and _SAFE_ERROR.fullmatch(error) is not None
    )


def coordinator_results_outcome(
    jobs_path: Path, result_dir: Path
) -> ValidationOutcome:
    """Validate the durable final status artifact for every manifest job."""
    for job in _load_coordinator_jobs(jobs_path)["jobs"]:
        status_path = result_dir / job["source_id"] / "status.json"
        if not status_path.is_file():
            return ValidationOutcome.INCOMPLETE
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ValidationOutcome.INVALID_REPORT
        if not _validate_coordinator_status(job, payload):
            return ValidationOutcome.INVALID_REPORT
    return ValidationOutcome.OK


class _CoordinatorSignal(Exception):
    pass


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_coordinator_process(
    command: Sequence[str],
    *,
    timeout: int,
    lease_manifest: Path,
    jobs_path: Path,
    result_dir: Path,
) -> ValidationOutcome:
    """Run one parent, await durable results after yield, and clean leases."""
    process: subprocess.Popen[str] | None = None
    previous_handlers: dict[int, Any] = {}
    deadline = time_module.monotonic() + timeout

    def handle_signal(_signum: int, _frame: Any) -> None:
        raise _CoordinatorSignal

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, handle_signal)
        try:
            process = subprocess.Popen(
                list(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return ValidationOutcome.AGENT_ERROR

        remaining = deadline - time_module.monotonic()
        if remaining <= 0:
            _stop_process(process)
            return ValidationOutcome.TIMEOUT
        try:
            stdout, _ = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            return ValidationOutcome.TIMEOUT
        if process.returncode != 0:
            return ValidationOutcome.AGENT_ERROR

        jobs = _load_coordinator_jobs(jobs_path)["jobs"]
        envelope_outcome, yielded = _validate_coordinator_envelope(
            stdout, len(jobs)
        )
        if envelope_outcome is not ValidationOutcome.OK:
            return envelope_outcome

        result_outcome = coordinator_results_outcome(jobs_path, result_dir)
        if not yielded:
            return result_outcome
        while result_outcome is ValidationOutcome.INCOMPLETE:
            remaining = deadline - time_module.monotonic()
            if remaining <= 0:
                return ValidationOutcome.TIMEOUT
            time_module.sleep(min(0.1, remaining))
            result_outcome = coordinator_results_outcome(jobs_path, result_dir)
        return result_outcome
    except _CoordinatorSignal:
        if process is not None:
            _stop_process(process)
        return ValidationOutcome.ABORTED
    finally:
        try:
            try:
                cleanup_browser_leases(lease_manifest, remove=True)
            finally:
                finalize_coordinator_results(jobs_path, result_dir)
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


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
                "status": CollectorStatus.FAILED,
            }
        rows.append(row)
    failures = [
        row for row in rows if row.get("status") != CollectorStatus.OK
    ]
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
    slack_brief_output: Path,
    evidence_stats: Path,
    collector_stats: Path,
    holdings_path: Path,
    watchlist_path: Path,
    instructions: Path,
) -> dict[str, Any]:
    """Build the neutral synthesis handoff contract."""
    start, end = brief_window(run_date)
    return {
        "date": run_date.isoformat(),
        "db": str(db),
        "collector_stats": str(collector_stats),
        "evidence_stats": str(evidence_stats),
        "holdings_path": str(holdings_path),
        "instructions": str(instructions),
        "prepared_evidence": str(prepared_evidence),
        "slack_brief_output": str(slack_brief_output),
        "watchlist_path": str(watchlist_path),
        "steps": [
            "Query news in the fixed [previous-run 04:00, run-date 04:00) "
            "America/New_York window whose summary is NULL or blank.",
            "Pipe each row's content through `minerva summarize`; retain generated "
            "summaries until all calls succeed.",
            "Persist summaries with parameter binding in one safe transaction, "
            "updating only still-blank rows.",
            "Build one ranked topic shortlist from every complete summary and "
            "render it directly to notes/slack-brief.md.",
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
    if command == "self-command":
        _require(command, args, 0)
        print(shlex.join([sys.executable, str(Path(__file__).resolve())]))
    elif command == "previous-date":
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
    elif command == "validate-openclaw":
        _require(command, args, 0)
        outcome = validate_openclaw_result(sys.stdin.read())
        if outcome is not ValidationOutcome.OK:
            raise ValueError(outcome)
    elif command == "validate-collector-file":
        _require(command, args, 1)
        outcome = validate_collector_report(Path(args[0]).read_text(encoding="utf-8"))
        print(outcome)
        if outcome is not ValidationOutcome.OK:
            raise ValueError(outcome)
    elif command == "lease-recover":
        _require(command, args, 1)
        for recovered in recover_stale_lease_manifests(Path(args[0])):
            print(recovered)
    elif command == "lease-init":
        _require(command, args, 2)
        initialize_lease_manifest(Path(args[0]), int(args[1]))
    elif command == "lease-allocate":
        _require(command, args, 3)
        print(allocate_browser_lease(Path(args[0]), args[1], args[2]))
    elif command == "lease-close":
        _require(command, args, 3)
        close_browser_lease(Path(args[0]), args[1], args[2])
    elif command == "lease-cleanup":
        _require(command, args, 1)
        cleanup_browser_leases(Path(args[0]), remove=True)
    elif command == "lease-prompt":
        _require(command, args, 5)
        source, destination, manifest, source_id, alias = args
        rendered = render_leased_browser_prompt(
            Path(source).read_text(encoding="utf-8"),
            Path(manifest),
            source_id,
            alias,
        )
        Path(destination).write_text(rendered, encoding="utf-8")
    elif command == "leased-browser":
        if len(args) < 4:
            raise ValueError("leased-browser expects MANIFEST SOURCE ALIAS COMMAND [ARGS]")
        status = run_leased_browser_command(Path(args[0]), args[1], args[2], args[3:])
        if status != 0:
            raise ValueError(f"leased browser exited with status {status}")
    elif command == "render-coordinator":
        _require(command, args, 6)
        template, output, jobs, leases, artifacts, helper_command = args
        text = Path(template).read_text(encoding="utf-8")
        rendered = render_prompt(
            text,
            {
                "COLLECTOR_ARTIFACT_DIR": artifacts,
                "COORDINATOR_JOBS": jobs,
                "HELPER_COMMAND": helper_command,
                "LEASE_MANIFEST": leases,
            },
        )
        unresolved = sorted(set(_PLACEHOLDER.findall(rendered)))
        if unresolved:
            raise ValueError(f"unresolved coordinator placeholders: {unresolved}")
        Path(output).write_text(rendered, encoding="utf-8")
    elif command == "coordinator-init":
        _require(command, args, 2)
        initialize_coordinator_jobs(Path(args[0]), int(args[1]))
    elif command == "coordinator-job":
        _require(command, args, 10)
        (
            jobs_path,
            source_id,
            source_name,
            url,
            access,
            prompt_file,
            source_root,
            max_attempts,
            timeout,
            log_file,
        ) = args
        if access not in {"browser", "web_fetch"}:
            raise ValueError(f"invalid collector access: {access}")
        append_coordinator_job(
            Path(jobs_path),
            {
                "access": access,
                "log_file": log_file,
                "max_attempts": int(max_attempts),
                "prompt_file": prompt_file,
                "source_id": source_id,
                "source_name": source_name,
                "source_root": source_root,
                "task_name": re.sub(r"[^a-z0-9_-]", "-", source_id.lower()),
                "timeout": int(timeout),
                "url": url,
            },
        )
    elif command == "coordinator-record":
        _require(command, args, 6)
        jobs_path, result_dir, source_id, attempts, status, error = args
        record_coordinator_result(
            Path(jobs_path), Path(result_dir), source_id, int(attempts), status, error
        )
    elif command == "coordinator-finalize":
        _require(command, args, 2)
        finalize_coordinator_results(Path(args[0]), Path(args[1]))
    elif command == "run-coordinator":
        if len(args) < 6 or args[4] != "--":
            raise ValueError(
                "run-coordinator expects LEASE_MANIFEST JOBS RESULTS TIMEOUT -- COMMAND [ARGS]"
            )
        lease_manifest = Path(args[0])
        jobs_path = Path(args[1])
        result_dir = Path(args[2])
        outcome = run_coordinator_process(
            args[5:],
            timeout=int(args[3]),
            lease_manifest=lease_manifest,
            jobs_path=jobs_path,
            result_dir=result_dir,
        )
        if outcome is ValidationOutcome.ABORTED:
            raise SystemExit(130)
        if outcome is not ValidationOutcome.OK:
            raise ValueError(outcome)
    elif command == "collector-status":
        _require(command, args, 10)
        (
            output,
            source_id,
            source_name,
            url,
            session_id,
            status,
            exit_status,
            log,
            attempts,
            error,
        ) = args
        _write_json(
            Path(output),
            {
                "attempts": int(attempts),
                "error": error or None,
                "exit_status": int(exit_status),
                "log": log,
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
        _require(command, args, 10)
        (
            output,
            run_date,
            db,
            prepared,
            slack,
            evidence,
            collectors,
            holdings,
            watchlist,
            instructions,
        ) = args
        _write_json(
            Path(output),
            synthesis_handoff(
                run_date=parse_run_date(run_date),
                db=Path(db),
                prepared_evidence=Path(prepared),
                slack_brief_output=Path(slack),
                evidence_stats=Path(evidence),
                collector_stats=Path(collectors),
                holdings_path=Path(holdings),
                watchlist_path=Path(watchlist),
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
