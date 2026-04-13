"""Morning market brief evidence collection and preparation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from lxml import html as lxml_html

from harness.portfolio_state import (
    append_jsonl,
    canonical_security_id,
    ensure_portfolio_layout,
    load_json,
    load_payload,
    now_utc_iso,
    parse_iso_date,
    portfolio_paths,
    read_text_source,
    write_json,
)
from minerva.sec import get_recent_filings


DEFAULT_FILING_FORMS = ["8-K", "10-K", "10-Q", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"]
DEFAULT_INDEX_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM"]
IR_HTML_NAV_PATTERNS = (
    r"home",
    r"about(?: us)?",
    r"contact(?: us)?",
    r"skip to(?: main content| content)?",
    r"go to(?: footer| main content| content)?",
    r"buy(?: now)?",
    r"log(?:in| on)",
    r"sign in",
    r"sign up",
    r"register",
    r"subscribe",
    r"menu",
    r"search",
    r"learn more",
    r"read more",
    r"investor relations",
    r"press releases?",
    r"news(?:room)?",
    r"events?",
)
IR_HTML_MATERIAL_TITLE_PATTERN = re.compile(
    r"\b(?:"
    r"announces?|reports?|reported|files?|filed|completes?|completed|declares?|launches?|publishes?|"
    r"prices?|priced|acquires?|acquired|acquisition|merger|appoints?|expands?|partners?|partnership|"
    r"enters?|entered|closes?|closed|closing|commences?|receives?|received|approves?|approved|"
    r"results?|earnings|revenue|guidance|outlook|quarter|fiscal|annual|investor day|conference call|"
    r"webcast|presentation|dividend|buyback|repurchase|offering|notes|debt|equity|sec|8-k|10-k|10-q|"
    r"shareholders?|board|trial|study|data|fda|phase\s+[1234]|agreement"
    r")\b"
    r"|"
    r"\b(?:q[1-4]|fy)\s*(?:20)?\d{2}\b"
    r"|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\b",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class RunPaths:
    """Filesystem layout for one morning brief run."""

    workspace_root: Path
    run_date: date

    @property
    def root(self) -> Path:
        return self.workspace_root / "reports" / "03-daily-news" / self.run_date.isoformat()

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def structured_dir(self) -> Path:
        return self.data_dir / "structured"

    @property
    def rendered_dir(self) -> Path:
        return self.data_dir / "rendered"

    @property
    def manifest(self) -> Path:
        return self.raw_dir / "manifest.json"

    @property
    def review_log(self) -> Path:
        return self.workspace_root / "reports" / "03-daily-news" / "review-log.jsonl"


def ensure_daily_run_layout(workspace_root: Path, run_date: date) -> RunPaths:
    """Create the run folder layout and starter files."""
    paths = RunPaths(workspace_root=workspace_root.resolve(), run_date=run_date)
    root = paths.workspace_root / "reports" / "03-daily-news"
    root.mkdir(parents=True, exist_ok=True)
    paths.notes_dir.mkdir(parents=True, exist_ok=True)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    paths.structured_dir.mkdir(parents=True, exist_ok=True)
    paths.rendered_dir.mkdir(parents=True, exist_ok=True)

    _ensure_index(root / "INDEX.md", "Daily News Runs", "Daily morning brief evidence runs and review logs.")
    _ensure_index(paths.root / "INDEX.md", f"Daily Run {run_date.isoformat()}", "Evidence and notes for one run date.")
    _ensure_index(paths.notes_dir / "INDEX.md", "Notes", "Morning brief writeups produced after evidence prep.")
    _ensure_index(paths.data_dir / "INDEX.md", "Data", "Raw, structured, and rendered evidence for this run.")
    _ensure_index(paths.raw_dir / "INDEX.md", "Raw Evidence", "Raw source payloads and the run manifest.")
    _ensure_index(paths.structured_dir / "INDEX.md", "Structured Evidence", "Prepared and audited evidence artifacts.")
    _ensure_index(paths.rendered_dir / "INDEX.md", "Rendered Evidence", "Deterministic markdown renders for human review.")

    for notes_file, title in (
        (paths.notes_dir / "morning-brief-report.md", "Morning Brief Report"),
        (paths.notes_dir / "slack-brief.md", "Slack Brief"),
    ):
        if not notes_file.exists():
            notes_file.write_text(f"# {title}\n\nPending main-agent writeup.\n", encoding="utf-8")

    if not paths.review_log.exists():
        paths.review_log.write_text("", encoding="utf-8")
    if not paths.manifest.exists():
        write_json(paths.manifest, _manifest_seed(paths))
    else:
        manifest = load_manifest(run_paths=paths)
        manifest.setdefault("outputs", {})
        manifest["outputs"].update(_default_manifest_outputs(paths))
        write_json(paths.manifest, manifest)
    return paths


def collect_filings(
    workspace_root: Path,
    *,
    run_date: date,
    source: str | None = None,
    forms: list[str] | None = None,
    since: date | None = None,
    until: date | None = None,
    limit_per_company: int = 10,
) -> dict[str, Any]:
    """Collect normalized SEC filing events for the monitored universe."""
    ensure_portfolio_layout(workspace_root)
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    universe = load_json(portfolio_paths(workspace_root).universe, default=[])
    if not universe:
        raise ValueError("portfolio universe is empty; run `minerva portfolio sync` first")

    effective_since = since or run_date
    effective_until = until or run_date
    raw_companies: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    degraded_reasons: list[str] = []

    if source:
        raw_companies, events = _load_filings_source_payload(source, universe, run_date)
    else:
        for security in universe:
            ticker = str(security.get("ticker") or security.get("security_id") or "").strip()
            if not ticker:
                continue
            try:
                filings = get_recent_filings(
                    ticker,
                    forms=forms or DEFAULT_FILING_FORMS,
                    since=effective_since,
                    until=effective_until,
                    limit=limit_per_company,
                )
            except Exception as exc:
                errors.append({"security_id": str(security.get("security_id", ticker)), "error": str(exc)})
                continue
            raw_companies.append({"security": security, "filings": filings})
            for filing in filings:
                events.append(_normalize_filing_event(security, filing))

    sorted_events = sorted(events, key=lambda item: (item["event_date"], item["security_id"], item["headline"]))

    payload = {
        "date": run_date.isoformat(),
        "collected_at": now_utc_iso(),
        "forms": forms or DEFAULT_FILING_FORMS,
        "source": source,
        "companies": raw_companies,
        "events": sorted_events,
        "errors": errors,
        "degraded_reasons": degraded_reasons,
    }
    raw_path = run_paths.raw_dir / "filings.json"
    rendered_path = run_paths.rendered_dir / "filings.md"
    write_json(raw_path, payload)
    rendered_path.write_text(render_event_markdown("Filings", sorted_events), encoding="utf-8")
    status = "success" if not errors else ("degraded" if events else "error")
    update_manifest_source(
        run_paths,
        "filings",
        {
            "status": status,
            "event_count": len(sorted_events),
            "error_count": len(errors),
            "raw_path": str(raw_path),
            "rendered_path": str(rendered_path),
            "source": source,
            "window": {"since": effective_since.isoformat(), "until": effective_until.isoformat()},
            "degraded_reasons": degraded_reasons,
        },
    )
    return {"status": status, "event_count": len(sorted_events), "error_count": len(errors), "raw_path": raw_path}


def collect_earnings(
    workspace_root: Path,
    *,
    run_date: date,
    source: str | None = None,
    provider: str = "auto",
    finnhub_api_key: str | None = None,
) -> dict[str, Any]:
    """Collect earnings metadata and normalize it into events."""
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    universe = load_json(portfolio_paths(workspace_root).universe, default=[])
    adjacency_map = load_json(portfolio_paths(workspace_root).adjacency_map, default=[])
    payload, degraded_reasons = load_market_provider_payload(
        source=source,
        provider=provider,
        finnhub_api_key=finnhub_api_key,
        run_date=run_date,
    )
    source_rows = payload.get("earnings", payload if isinstance(payload, list) else [])
    events: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []

    for row in source_rows:
        event = _normalize_earnings_event(row, run_date, universe, adjacency_map)
        if event is None:
            suppressed.append(dict(row))
            continue
        events.append(event)
    sorted_events = sorted(events, key=lambda item: (item["event_date"], item["relationship"], item["security_id"], item["headline"]))

    raw_path = run_paths.raw_dir / "earnings.json"
    rendered_path = run_paths.rendered_dir / "earnings.md"
    write_json(
        raw_path,
        {
            "date": run_date.isoformat(),
            "collected_at": now_utc_iso(),
            "provider": provider,
            "source": source,
            "payload": payload,
            "events": sorted_events,
            "suppressed": suppressed,
            "degraded_reasons": degraded_reasons,
        },
    )
    rendered_path.write_text(render_event_markdown("Earnings", sorted_events), encoding="utf-8")
    status = "degraded" if degraded_reasons else "success"
    update_manifest_source(
        run_paths,
        "earnings",
        {
            "status": status,
            "event_count": len(sorted_events),
            "suppressed_count": len(suppressed),
            "raw_path": str(raw_path),
            "rendered_path": str(rendered_path),
            "provider": provider,
            "degraded_reasons": degraded_reasons,
        },
    )
    return {"status": status, "event_count": len(sorted_events), "raw_path": raw_path}


def collect_macro(
    workspace_root: Path,
    *,
    run_date: date,
    source: str | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Collect the run-date macro schedule from a local registry or source file."""
    ensure_portfolio_layout(workspace_root)
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    paths = portfolio_paths(workspace_root)
    registry_file = registry_path or paths.macro_registry
    registry = load_json(registry_file, default={"sources": []})
    events_source = source or registry.get("events_source")
    degraded_reasons: list[str] = []
    source_rows: list[dict[str, Any]] = []
    if events_source:
        loaded_payload, _ = load_payload(str(events_source))
        if isinstance(loaded_payload, list):
            source_rows = [dict(item) for item in loaded_payload if isinstance(item, dict)]
        elif isinstance(loaded_payload, dict):
            source_rows = [dict(item) for item in loaded_payload.get("events", []) if isinstance(item, dict)]
            degraded_reasons.extend(
                sorted(
                    {
                        str(reason).strip()
                        for reason in loaded_payload.get("degraded_reasons", [])
                        if str(reason).strip()
                    }
                )
            )
    else:
        degraded_reasons.append("no macro events source configured")

    events = [_normalize_macro_event(row, run_date) for row in source_rows]
    events = [event for event in events if event is not None]
    sorted_events = sorted(events, key=lambda item: (item["event_date"], item.get("release_time", ""), item["headline"]))

    raw_path = run_paths.raw_dir / "macro.json"
    rendered_path = run_paths.rendered_dir / "macro.md"
    write_json(
        raw_path,
        {
            "date": run_date.isoformat(),
            "collected_at": now_utc_iso(),
            "registry": registry,
            "events": sorted_events,
            "degraded_reasons": degraded_reasons,
        },
    )
    rendered_path.write_text(render_event_markdown("Macro", sorted_events), encoding="utf-8")
    status = "degraded" if degraded_reasons else "success"
    update_manifest_source(
        run_paths,
        "macro",
        {
            "status": status,
            "event_count": len(sorted_events),
            "raw_path": str(raw_path),
            "rendered_path": str(rendered_path),
            "degraded_reasons": degraded_reasons,
        },
    )
    return {"status": status, "event_count": len(sorted_events), "raw_path": raw_path}


def collect_macro_registry_events(
    workspace_root: Path,
    *,
    run_date: date,
    registry_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Build a normalized macro-events payload from configured official registry sources."""
    ensure_portfolio_layout(workspace_root)
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    paths = portfolio_paths(workspace_root)
    registry_file = registry_path or paths.macro_registry
    registry = load_json(registry_file, default={"sources": []})
    sources = [dict(item) for item in registry.get("sources", []) if isinstance(item, dict)]
    destination = (output_path or (run_paths.raw_dir / "macro-events.json")).resolve()

    events: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    degraded_reasons: list[str] = []
    if not sources:
        degraded_reasons.append("no macro registry sources configured")

    for source_entry in sources:
        summary, collected_events = _collect_macro_registry_source(source_entry, run_date)
        source_summaries.append(summary)
        events.extend(collected_events)
        degraded_reasons.extend(summary.get("degraded_reasons", []))

    deduped_events = _dedupe_macro_source_rows(events)
    payload = {
        "date": run_date.isoformat(),
        "generated_at": now_utc_iso(),
        "registry_path": str(Path(registry_file).resolve()),
        "events": deduped_events,
        "sources": source_summaries,
        "degraded_reasons": sorted({reason for reason in degraded_reasons if reason}),
    }
    write_json(destination, payload)

    status = "degraded" if payload["degraded_reasons"] else "success"
    update_manifest_source(
        run_paths,
        "macro-collect",
        {
            "status": status,
            "event_count": len(deduped_events),
            "source_count": len(source_summaries),
            "output_path": str(destination),
            "registry_path": str(Path(registry_file).resolve()),
            "degraded_reasons": payload["degraded_reasons"],
        },
    )
    return {
        "status": status,
        "event_count": len(deduped_events),
        "source_count": len(source_summaries),
        "output_path": destination,
    }


def collect_ir(
    workspace_root: Path,
    *,
    run_date: date,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Collect IR releases from a locally curated registry."""
    ensure_portfolio_layout(workspace_root)
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    paths = portfolio_paths(workspace_root)
    registry = load_json(registry_path or paths.ir_registry, default=[])

    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    degraded_reasons: list[str] = []
    if not registry:
        degraded_reasons.append("no IR registry configured")
    configured_feeds = 0
    for entry in registry:
        security_id = canonical_security_id(entry.get("security_id") or entry.get("ticker") or entry.get("company_name"))
        for feed in entry.get("feeds", []):
            feed_url = str(feed.get("url") or "").strip()
            feed_format = str(feed.get("format") or "rss").strip().lower()
            if not feed_url:
                continue
            configured_feeds += 1
            try:
                feed_events = _parse_ir_feed(feed_url, feed_format, run_date, security_id, entry)
            except Exception as exc:
                errors.append({"security_id": security_id, "url": feed_url, "error": str(exc)})
                continue
            events.extend(feed_events)
    if registry and configured_feeds == 0:
        degraded_reasons.append("IR registry has no configured feeds")
    sorted_events = sorted(events, key=lambda item: (item["event_date"], item["security_id"], item["headline"]))

    raw_path = run_paths.raw_dir / "ir.json"
    rendered_path = run_paths.rendered_dir / "ir.md"
    write_json(
        raw_path,
        {
            "date": run_date.isoformat(),
            "collected_at": now_utc_iso(),
            "registry": registry,
            "events": sorted_events,
            "errors": errors,
            "degraded_reasons": degraded_reasons,
        },
    )
    rendered_path.write_text(render_event_markdown("IR", sorted_events), encoding="utf-8")
    status = "success"
    if degraded_reasons or errors:
        status = "degraded" if sorted_events or degraded_reasons else "error"
    update_manifest_source(
        run_paths,
        "ir",
        {
            "status": status,
            "event_count": len(sorted_events),
            "error_count": len(errors),
            "raw_path": str(raw_path),
            "rendered_path": str(rendered_path),
            "degraded_reasons": degraded_reasons,
        },
    )
    return {"status": status, "event_count": len(sorted_events), "raw_path": raw_path}


def collect_market(
    workspace_root: Path,
    *,
    run_date: date,
    source: str | None = None,
    provider: str = "auto",
    finnhub_api_key: str | None = None,
) -> dict[str, Any]:
    """Collect a narrow market context snapshot."""
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    payload, degraded_reasons = load_market_provider_payload(
        source=source,
        provider=provider,
        finnhub_api_key=finnhub_api_key,
        run_date=run_date,
    )
    events = normalize_market_events(payload, run_date)
    sorted_events = sorted(events, key=lambda item: (item["event_date"], item.get("category", ""), item["headline"]))

    raw_path = run_paths.raw_dir / "market.json"
    rendered_path = run_paths.rendered_dir / "market.md"
    write_json(
        raw_path,
        {
            "date": run_date.isoformat(),
            "collected_at": now_utc_iso(),
            "provider": provider,
            "source": source,
            "payload": payload,
            "events": sorted_events,
            "degraded_reasons": degraded_reasons,
        },
    )
    rendered_path.write_text(render_event_markdown("Market", sorted_events), encoding="utf-8")
    status = "degraded" if degraded_reasons else "success"
    update_manifest_source(
        run_paths,
        "market",
        {
            "status": status,
            "event_count": len(sorted_events),
            "raw_path": str(raw_path),
            "rendered_path": str(rendered_path),
            "provider": provider,
            "degraded_reasons": degraded_reasons,
        },
    )
    return {"status": status, "event_count": len(sorted_events), "raw_path": raw_path}


def prepare_evidence(workspace_root: Path, *, run_date: date) -> dict[str, Any]:
    """Build an agent-ready evidence pack from collected sources."""
    ensure_portfolio_layout(workspace_root)
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    paths = portfolio_paths(workspace_root)
    manifest = load_manifest(run_paths)
    universe = load_json(paths.universe, default=[])
    adjacency_map = load_json(paths.adjacency_map, default=[])
    thesis_cards = load_json(paths.thesis_cards, default=[])

    source_payloads = {name: _load_raw_source(run_paths, name) for name in ("filings", "earnings", "macro", "ir", "market")}
    source_events = {name: payload.get("events", []) for name, payload in source_payloads.items()}

    all_events: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_name, events in source_events.items():
        for event in events:
            enriched = enrich_event_relationships(dict(event), universe, adjacency_map)
            dedupe_key = build_event_key(enriched)
            if dedupe_key in seen:
                suppressed.append({"reason": "duplicate", "event": enriched})
                continue
            if enriched.get("event_date") not in {"", run_date.isoformat()}:
                suppressed.append({"reason": "stale", "event": enriched})
                continue
            if not enriched.get("headline"):
                suppressed.append({"reason": "missing-headline", "event": enriched})
                continue
            seen.add(dedupe_key)
            enriched["source_name"] = source_name
            all_events.append(enriched)

    sorted_events = sorted(
        all_events,
        key=lambda item: (
            item["group"],
            item.get("relationship", ""),
            item.get("security_id", ""),
            item["headline"],
        ),
    )
    grouped = group_prepared_events(sorted_events)
    thesis_map = {str(card.get("security_id", "")): card for card in thesis_cards}
    prepared = {
        "date": run_date.isoformat(),
        "generated_at": now_utc_iso(),
        "universe": universe,
        "events": sorted_events,
        "grouped_events": grouped,
        "suppressed": suppressed,
        "thesis_cards": {key: thesis_map[key] for key in sorted(thesis_map)},
        "source_status": manifest.get("sources", {}),
    }

    universe_path = run_paths.structured_dir / "universe.json"
    prepared_path = run_paths.structured_dir / "prepared-evidence.json"
    source_status_path = run_paths.rendered_dir / "source-status.md"
    grouped_path = run_paths.rendered_dir / "grouped-events.md"
    evidence_path = run_paths.rendered_dir / "evidence.md"
    write_json(universe_path, universe)
    write_json(prepared_path, prepared)
    grouped_path.write_text(render_grouped_events_markdown(grouped), encoding="utf-8")
    source_status_path.write_text(render_source_status_markdown(manifest.get("sources", {})), encoding="utf-8")
    evidence_path.write_text(render_event_markdown("Prepared Evidence", sorted_events), encoding="utf-8")

    update_manifest_source(
        run_paths,
        "prep",
        {
            "status": "success",
            "event_count": len(sorted_events),
            "suppressed_count": len(suppressed),
            "prepared_path": str(prepared_path),
            "grouped_events_path": str(grouped_path),
            "source_status_path": str(source_status_path),
            "evidence_path": str(evidence_path),
            "universe_path": str(universe_path),
        },
    )
    return {"status": "success", "event_count": len(sorted_events), "prepared_path": prepared_path}


def audit_evidence(workspace_root: Path, *, run_date: date) -> dict[str, Any]:
    """Run a bounded audit on prepared evidence."""
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    manifest = load_manifest(run_paths)
    prepared = load_json(run_paths.structured_dir / "prepared-evidence.json", default={})
    prepared_events = prepared.get("events", [])
    prepared_keys = {build_event_key(event) for event in prepared_events}
    suppressed_keys = {
        build_event_key(item.get("event", {}))
        for item in prepared.get("suppressed", [])
        if isinstance(item, dict) and isinstance(item.get("event"), dict)
    }
    raw_sources = {name: _load_raw_source(run_paths, name) for name in ("filings", "earnings", "macro", "ir", "market")}

    missed_events: list[dict[str, Any]] = []
    for name, payload in raw_sources.items():
        for event in payload.get("events", []):
            event_key = build_event_key(event)
            if event_key in prepared_keys or event_key in suppressed_keys:
                continue
            if _event_date(event, run_date) != run_date.isoformat():
                continue
            if not str(event.get("headline") or "").strip():
                continue
            if event.get("source") == "market" and event.get("change_pct") is None:
                missed_events.append({"source": name, "event": event})
                continue
            missed_events.append({"source": name, "event": event})

    source_failures = {
        name: details for name, details in manifest.get("sources", {}).items() if details.get("status") not in {"success", ""}
    }
    covered_security_ids = {str(event.get("security_id", "")) for event in prepared_events if event.get("relationship") == "monitored"}
    universe = load_json(portfolio_paths(workspace_root).universe, default=[])
    uncovered_monitored = [
        str(item.get("security_id", ""))
        for item in universe
        if str(item.get("security_id", "")) and str(item.get("security_id", "")) not in covered_security_ids
    ]

    audit_payload = {
        "date": run_date.isoformat(),
        "generated_at": now_utc_iso(),
        "missed_events": missed_events,
        "source_failures": source_failures,
        "uncovered_monitored": uncovered_monitored,
    }
    audit_path = run_paths.structured_dir / "audit.json"
    rendered_path = run_paths.rendered_dir / "audit.md"
    write_json(audit_path, audit_payload)
    rendered_path.write_text(render_audit_markdown(audit_payload), encoding="utf-8")
    update_manifest_source(
        run_paths,
        "audit",
        {
            "status": "success",
            "missed_event_count": len(missed_events),
            "audit_path": str(audit_path),
            "rendered_path": str(rendered_path),
        },
    )
    return {"status": "success", "missed_event_count": len(missed_events), "audit_path": audit_path}


def append_review_log(workspace_root: Path, *, run_date: date, notes: str | None = None) -> dict[str, Any]:
    """Append one structured review log entry for the run."""
    run_paths = ensure_daily_run_layout(workspace_root, run_date)
    manifest = load_manifest(run_paths)
    audit = load_json(run_paths.structured_dir / "audit.json", default={})
    entry = {
        "run_id": run_date.isoformat(),
        "date": run_date.isoformat(),
        "logged_at": now_utc_iso(),
        "source_failures": {
            name: details
            for name, details in manifest.get("sources", {}).items()
            if details.get("status") not in {"success", ""}
        },
        "degraded_modes_used": sorted(
            {
                reason
                for details in manifest.get("sources", {}).values()
                for reason in details.get("degraded_reasons", [])
            }
        ),
        "misses_found_later": len(audit.get("missed_events", [])),
        "recurring_pain_points": audit.get("uncovered_monitored", []),
        "notes": (notes or "").strip(),
    }
    append_jsonl(run_paths.review_log, entry)
    update_manifest_source(
        run_paths,
        "review-log",
        {
            "status": "success",
            "review_log_path": str(run_paths.review_log),
            "logged_at": entry["logged_at"],
            "entry_count": len(_read_review_log(run_paths.review_log)),
        },
    )
    return {"status": "success", "review_log_path": run_paths.review_log}


def _load_filings_source_payload(
    source: str,
    universe: list[dict[str, Any]],
    run_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load fixture-backed filing payloads for deterministic local runs."""
    payload, _ = load_payload(source)
    universe_lookup = _build_universe_lookup(universe)

    explicit_events: list[dict[str, Any]] = []
    company_rows: list[dict[str, Any]] = []
    filing_rows: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        company_rows = [dict(item) for item in payload.get("companies", []) if isinstance(item, dict)]
        explicit_events = [
            _normalize_filing_source_event(dict(item), universe_lookup, run_date)
            for item in payload.get("events", [])
            if isinstance(item, dict)
        ]
        filing_rows = [dict(item) for item in payload.get("filings", []) if isinstance(item, dict)]
    elif isinstance(payload, list):
        filing_rows = [dict(item) for item in payload if isinstance(item, dict)]
    else:
        raise ValueError(f"unsupported filings source payload: {source}")

    raw_companies: list[dict[str, Any]] = []
    for item in company_rows:
        security = _resolve_filing_security(item.get("security"), universe_lookup)
        filings = [dict(filing) for filing in item.get("filings", []) if isinstance(filing, dict)]
        raw_companies.append({"security": security, "filings": filings})

    grouped: dict[str, dict[str, Any]] = {}
    for filing in filing_rows:
        security = _resolve_filing_security(filing, universe_lookup)
        security_id = str(security.get("security_id", "")).strip()
        if not security_id:
            continue
        bucket = grouped.setdefault(security_id, {"security": security, "filings": []})
        bucket["filings"].append(filing)
    raw_companies.extend(grouped.values())
    raw_companies = sorted(raw_companies, key=lambda item: str(item.get("security", {}).get("security_id", "")))

    normalized_events = [event for event in explicit_events if event.get("event_date") == run_date.isoformat()]
    if not explicit_events:
        for company in raw_companies:
            security = company.get("security", {})
            for filing in company.get("filings", []):
                event = _normalize_filing_event(security, filing)
                if event.get("event_date") == run_date.isoformat():
                    normalized_events.append(event)
    normalized_events.sort(key=lambda item: (item["event_date"], item["security_id"], item["headline"]))
    return raw_companies, normalized_events


def _build_universe_lookup(universe: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for security in universe:
        normalized = dict(security)
        security_id = canonical_security_id(
            normalized.get("security_id") or normalized.get("ticker") or normalized.get("company_name")
        )
        if not security_id:
            continue
        normalized["security_id"] = security_id
        normalized.setdefault("ticker", security_id)
        for candidate in (security_id, normalized.get("ticker"), normalized.get("company_name")):
            key = canonical_security_id(candidate)
            if key:
                lookup[key] = normalized
    return lookup


def _resolve_filing_security(value: Any, universe_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if isinstance(value, dict):
        raw = dict(value)
        security_id = canonical_security_id(raw.get("security_id") or raw.get("ticker") or raw.get("company_name"))
        if security_id and security_id in universe_lookup:
            return dict(universe_lookup[security_id])
        if security_id:
            return {
                "security_id": security_id,
                "ticker": str(raw.get("ticker") or security_id),
                "company_name": str(raw.get("company_name") or raw.get("name") or security_id),
            }
    security_id = canonical_security_id(value)
    if security_id and security_id in universe_lookup:
        return dict(universe_lookup[security_id])
    if not security_id:
        return {}
    return {"security_id": security_id, "ticker": security_id, "company_name": str(value or security_id)}


def _normalize_filing_source_event(
    event: dict[str, Any],
    universe_lookup: dict[str, dict[str, Any]],
    run_date: date,
) -> dict[str, Any]:
    security = _resolve_filing_security(event, universe_lookup)
    security_id = str(security.get("security_id", "")).strip()
    form = str(event.get("form", "")).strip()
    headline = str(event.get("headline") or "").strip()
    if not headline:
        headline = f"{security_id} filed {form}".strip() if security_id or form else "Filing event"
    return {
        "source": "filings",
        "event_type": "filing",
        "event_date": _event_date(event, run_date),
        "security_id": security_id,
        "ticker": str(security.get("ticker") or security_id),
        "relationship": "monitored",
        "headline": headline,
        "form": form,
        "reference_url": str(event.get("reference_url") or event.get("url") or "").strip(),
        "metadata": event,
    }


def load_market_provider_payload(
    *,
    source: str | None,
    provider: str,
    finnhub_api_key: str | None,
    run_date: date,
) -> tuple[dict[str, Any], list[str]]:
    """Load shared market-data payloads for earnings and market commands."""
    degraded_reasons: list[str] = []
    if source:
        payload, _ = load_payload(source)
        if isinstance(payload, dict):
            return payload, degraded_reasons
        if isinstance(payload, list):
            return {"earnings": payload, "market": payload}, degraded_reasons
        return {"earnings": [], "market": []}, ["unsupported source payload"]

    effective_provider = provider
    if provider == "auto":
        effective_provider = "finnhub" if finnhub_api_key else "file"
    if effective_provider == "finnhub" and finnhub_api_key:
        return _load_finnhub_payload(run_date, finnhub_api_key), degraded_reasons

    degraded_reasons.append("no market data source configured")
    return {"earnings": [], "market": [], "indexes": [], "rates": [], "fx": []}, degraded_reasons


def normalize_market_events(payload: dict[str, Any], run_date: date) -> list[dict[str, Any]]:
    """Normalize a narrow market payload into context events."""
    events: list[dict[str, Any]] = []
    for row in payload.get("market", []):
        event = _normalize_market_event(row, run_date)
        if event is not None:
            events.append(event)
    if events:
        return sorted(events, key=lambda item: item["headline"])

    for row in payload.get("indexes", []):
        event = _normalize_market_event(row, run_date)
        if event is not None:
            events.append(event)
    for row in payload.get("rates", []):
        event = _normalize_market_event(row, run_date, category="rates")
        if event is not None:
            events.append(event)
    for row in payload.get("fx", []):
        event = _normalize_market_event(row, run_date, category="fx")
        if event is not None:
            events.append(event)
    return sorted(events, key=lambda item: item["headline"])


def enrich_event_relationships(
    event: dict[str, Any],
    universe: list[dict[str, Any]],
    adjacency_map: list[dict[str, Any]],
) -> dict[str, Any]:
    """Re-apply relationship tagging during prep."""
    security_id = canonical_security_id(event.get("security_id") or event.get("ticker"))
    event["security_id"] = security_id
    event.setdefault("relationship", relationship_for_security(security_id, universe, adjacency_map))
    event.setdefault("group", group_for_event(event))
    return event


def build_event_key(event: dict[str, Any]) -> str:
    """Build a deterministic dedupe key for an event."""
    return "|".join(
        [
            str(event.get("source_name") or event.get("source", "")),
            str(event.get("security_id", "")),
            str(event.get("headline", "")),
            str(event.get("event_date", "")),
        ]
    )


def group_prepared_events(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group prepared events into candidate brief sections."""
    grouped: dict[str, list[dict[str, Any]]] = {
        "company-specific": [],
        "read-through": [],
        "macro-policy": [],
        "market-context": [],
    }
    for event in events:
        grouped.setdefault(event["group"], []).append(event)
    for group_name, group_events in grouped.items():
        grouped[group_name] = sorted(
            group_events,
            key=lambda item: (item.get("relationship", ""), item.get("security_id", ""), item.get("headline", "")),
        )
    return grouped


def relationship_for_security(
    security_id: str,
    universe: list[dict[str, Any]],
    adjacency_map: list[dict[str, Any]],
) -> str:
    """Resolve monitored vs adjacent vs market relationship tags."""
    monitored_ids = {str(item.get("security_id", "")) for item in universe}
    if security_id in monitored_ids:
        return "monitored"
    adjacent_ids = {str(item.get("adjacent", "")) for item in adjacency_map}
    if security_id in adjacent_ids:
        return "adjacent"
    return "market"


def group_for_event(event: dict[str, Any]) -> str:
    """Assign an event to a prep section."""
    source_name = str(event.get("source_name") or event.get("source", "")).lower()
    relationship = str(event.get("relationship", "")).lower()
    if source_name in {"macro"}:
        return "macro-policy"
    if source_name in {"market"}:
        return "market-context"
    if relationship == "adjacent":
        return "read-through"
    return "company-specific"


def load_manifest(run_paths: RunPaths) -> dict[str, Any]:
    """Read the run manifest."""
    return load_json(run_paths.manifest, default=_manifest_seed(run_paths))


def update_manifest_source(run_paths: RunPaths, source_name: str, details: dict[str, Any]) -> None:
    """Update one source section in the run manifest."""
    manifest = load_manifest(run_paths)
    manifest.setdefault("sources", {})[source_name] = details
    manifest.setdefault("outputs", {}).update(_default_manifest_outputs(run_paths))
    manifest["updated_at"] = now_utc_iso()
    degraded_modes = {
        reason
        for source_details in manifest.get("sources", {}).values()
        for reason in source_details.get("degraded_reasons", [])
    }
    manifest["degraded_modes"] = sorted(degraded_modes)
    write_json(run_paths.manifest, manifest)


def render_event_markdown(title: str, events: list[dict[str, Any]]) -> str:
    """Render a flat event list as markdown."""
    lines = [f"# {title}", ""]
    if not events:
        lines.append("No events collected.")
        return "\n".join(lines) + "\n"
    for event in events:
        parts = [
            event.get("event_date", ""),
            event.get("relationship", ""),
            event.get("security_id", ""),
            event.get("headline", ""),
        ]
        extra = event.get("reference_url") or event.get("source_url") or ""
        lines.append(f"- {' | '.join(part for part in parts if part)}{f' | {extra}' if extra else ''}")
    return "\n".join(lines) + "\n"


def render_grouped_events_markdown(grouped: dict[str, list[dict[str, Any]]]) -> str:
    """Render grouped prepared events."""
    lines = ["# Grouped Events", ""]
    for group_name in ("company-specific", "read-through", "macro-policy", "market-context"):
        lines.append(f"## {group_name}")
        group_events = grouped.get(group_name, [])
        if not group_events:
            lines.append("- None")
        else:
            for event in group_events:
                lines.append(f"- {event.get('headline', '')} | {event.get('security_id', '')} | {event.get('source_name', '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_source_status_markdown(source_status: dict[str, Any]) -> str:
    """Render source status summary."""
    lines = ["# Source Status", ""]
    if not source_status:
        lines.append("- No sources recorded.")
        return "\n".join(lines) + "\n"
    for name, details in sorted(source_status.items()):
        line = f"- {name}: status={details.get('status', '')} | events={details.get('event_count', details.get('missed_event_count', 0))}"
        degraded_reasons = details.get("degraded_reasons", [])
        if degraded_reasons:
            line += f" | degraded={', '.join(str(reason) for reason in degraded_reasons)}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def render_audit_markdown(audit_payload: dict[str, Any]) -> str:
    """Render audit findings as markdown."""
    lines = [
        "# Audit",
        "",
        f"- Missed events: {len(audit_payload.get('missed_events', []))}",
        f"- Source failures: {len(audit_payload.get('source_failures', {}))}",
        f"- Uncovered monitored securities: {len(audit_payload.get('uncovered_monitored', []))}",
        "",
        "## Missed Events",
    ]
    missed_events = audit_payload.get("missed_events", [])
    if not missed_events:
        lines.append("- None")
    else:
        for item in missed_events:
            event = item.get("event", {})
            lines.append(f"- {item.get('source', '')} | {event.get('security_id', '')} | {event.get('headline', '')}")
    lines.extend(["", "## Uncovered Monitored"])
    uncovered = audit_payload.get("uncovered_monitored", [])
    if not uncovered:
        lines.append("- None")
    else:
        for security_id in uncovered:
            lines.append(f"- {security_id}")
    return "\n".join(lines) + "\n"


def _manifest_seed(run_paths: RunPaths) -> dict[str, Any]:
    created_at = now_utc_iso()
    return {
        "run_id": run_paths.run_date.isoformat(),
        "date": run_paths.run_date.isoformat(),
        "created_at": created_at,
        "updated_at": created_at,
        "sources": {},
        "outputs": _default_manifest_outputs(run_paths),
        "degraded_modes": [],
    }


def _default_manifest_outputs(run_paths: RunPaths) -> dict[str, Any]:
    return {
        "run_root": str(run_paths.root),
        "notes_dir": str(run_paths.notes_dir),
        "raw_dir": str(run_paths.raw_dir),
        "structured_dir": str(run_paths.structured_dir),
        "rendered_dir": str(run_paths.rendered_dir),
        "raw": {
            "filings": str(run_paths.raw_dir / "filings.json"),
            "earnings": str(run_paths.raw_dir / "earnings.json"),
            "macro": str(run_paths.raw_dir / "macro.json"),
            "ir": str(run_paths.raw_dir / "ir.json"),
            "market": str(run_paths.raw_dir / "market.json"),
            "manifest": str(run_paths.manifest),
        },
        "structured": {
            "universe": str(run_paths.structured_dir / "universe.json"),
            "prepared_evidence": str(run_paths.structured_dir / "prepared-evidence.json"),
            "audit": str(run_paths.structured_dir / "audit.json"),
        },
        "rendered": {
            "filings": str(run_paths.rendered_dir / "filings.md"),
            "earnings": str(run_paths.rendered_dir / "earnings.md"),
            "macro": str(run_paths.rendered_dir / "macro.md"),
            "ir": str(run_paths.rendered_dir / "ir.md"),
            "market": str(run_paths.rendered_dir / "market.md"),
            "evidence": str(run_paths.rendered_dir / "evidence.md"),
            "grouped_events": str(run_paths.rendered_dir / "grouped-events.md"),
            "source_status": str(run_paths.rendered_dir / "source-status.md"),
            "audit": str(run_paths.rendered_dir / "audit.md"),
        },
        "notes": {
            "morning_brief_report": str(run_paths.notes_dir / "morning-brief-report.md"),
            "slack_brief": str(run_paths.notes_dir / "slack-brief.md"),
        },
        "manifest": str(run_paths.manifest),
        "review_log": str(run_paths.review_log),
    }


def _load_raw_source(run_paths: RunPaths, name: str) -> dict[str, Any]:
    path = run_paths.raw_dir / f"{name}.json"
    return load_json(path, default={})


def _read_review_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalize_filing_event(security: dict[str, Any], filing: dict[str, Any]) -> dict[str, Any]:
    security_id = str(security.get("security_id") or security.get("ticker") or "").strip()
    form = str(filing.get("form", "")).strip()
    description = str(filing.get("description") or filing.get("primary_document") or "").strip()
    headline = f"{security_id} filed {form}".strip()
    if description:
        headline = f"{headline}: {description}"
    return {
        "source": "filings",
        "event_type": "filing",
        "event_date": str(filing.get("filing_date", "")).strip(),
        "security_id": security_id,
        "ticker": str(security.get("ticker") or security_id),
        "relationship": "monitored",
        "headline": headline,
        "form": form,
        "reference_url": str(filing.get("url") or "").strip(),
        "metadata": filing,
    }


def _normalize_earnings_event(
    row: dict[str, Any],
    run_date: date,
    universe: list[dict[str, Any]],
    adjacency_map: list[dict[str, Any]],
) -> dict[str, Any] | None:
    security_id = canonical_security_id(row.get("ticker") or row.get("symbol") or row.get("security_id") or row.get("company"))
    relationship = relationship_for_security(security_id, universe, adjacency_map)
    market_relevant = bool(row.get("market_relevant"))
    if relationship == "market" and not market_relevant:
        return None
    event_date = _event_date(row, run_date)
    report_status = str(row.get("status") or row.get("report_status") or "scheduled").strip().lower()
    timing = str(row.get("timing") or row.get("report_time") or row.get("time") or "unknown").strip().lower()
    headline = str(row.get("headline") or row.get("title") or f"{security_id} earnings {report_status}").strip()
    return {
        "source": "earnings",
        "event_type": "earnings",
        "event_date": event_date,
        "security_id": security_id,
        "ticker": str(row.get("ticker") or security_id),
        "relationship": relationship,
        "headline": headline,
        "status": report_status,
        "timing": timing,
        "reference_url": str(row.get("url") or row.get("reference_url") or "").strip(),
        "metadata": row,
    }


def _normalize_macro_event(row: dict[str, Any], run_date: date) -> dict[str, Any] | None:
    event_date = _event_date(row, run_date)
    if event_date != run_date.isoformat():
        return None
    headline = str(row.get("event_name") or row.get("title") or row.get("headline") or "").strip()
    if not headline:
        return None
    return {
        "source": "macro",
        "event_type": "macro",
        "event_date": event_date,
        "security_id": "",
        "relationship": "market",
        "headline": headline,
        "release_time": str(row.get("release_time") or row.get("time") or "").strip(),
        "category": str(row.get("category") or "macro"),
        "importance": str(row.get("importance") or row.get("importance_tag") or "standard"),
        "source_url": str(row.get("url") or row.get("source_url") or "").strip(),
        "metadata": row,
    }


def _collect_macro_registry_source(source_entry: dict[str, Any], run_date: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_name = str(source_entry.get("name") or "macro-source").strip()
    source_url = str(source_entry.get("url") or "").strip()
    parser = str(source_entry.get("parser") or _default_macro_parser(source_entry)).strip().lower()
    degraded_reasons: list[str] = []

    if not source_url:
        degraded_reasons.append(f"{source_name}: missing source URL")
        return {
            "name": source_name,
            "url": source_url,
            "parser": parser,
            "status": "degraded",
            "event_count": 0,
            "degraded_reasons": degraded_reasons,
        }, []

    try:
        if parser in {"normalized_json", "json"}:
            payload, _ = load_payload(source_url)
            events = _parse_normalized_macro_payload(payload, source_entry, run_date)
        else:
            raw_text, _ = read_text_source(source_url)
            events = _parse_macro_registry_payload(parser, raw_text, source_url, source_entry, run_date)
    except Exception as exc:
        degraded_reasons.append(f"{source_name}: {exc}")
        return {
            "name": source_name,
            "url": source_url,
            "parser": parser,
            "status": "degraded",
            "event_count": 0,
            "degraded_reasons": degraded_reasons,
        }, []

    return {
        "name": source_name,
        "url": source_url,
        "parser": parser,
        "status": "degraded" if degraded_reasons else "success",
        "event_count": len(events),
        "degraded_reasons": degraded_reasons,
    }, events


def _default_macro_parser(source_entry: dict[str, Any]) -> str:
    source_name = str(source_entry.get("name") or "").strip().lower()
    if "bls" in source_name:
        return "bls_schedule"
    if "bea" in source_name:
        return "bea_schedule"
    if "federal reserve" in source_name or "fomc" in source_name:
        return "federal_reserve_events"
    if "treasury" in source_name:
        return "treasury_press_releases"
    return "dated_list"


def _parse_macro_registry_payload(
    parser: str,
    raw_text: str,
    source_url: str,
    source_entry: dict[str, Any],
    run_date: date,
) -> list[dict[str, Any]]:
    if parser in {"bls_schedule", "bea_schedule", "table_schedule"}:
        return _parse_macro_table_schedule(raw_text, source_url, source_entry, run_date)
    if parser in {"federal_reserve_events", "treasury_press_releases", "dated_list"}:
        return _parse_macro_dated_list(raw_text, source_url, source_entry, run_date)
    raise ValueError(f"unsupported macro parser `{parser}`")


def _parse_normalized_macro_payload(payload: Any, source_entry: dict[str, Any], run_date: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [dict(item) for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        rows = [dict(item) for item in payload.get("events", []) if isinstance(item, dict)]
    else:
        raise ValueError("unsupported normalized macro payload")

    events: list[dict[str, Any]] = []
    for row in rows:
        if _event_date(row, run_date) != run_date.isoformat():
            continue
        headline = str(row.get("event_name") or row.get("title") or row.get("headline") or "").strip()
        if not headline:
            continue
        events.append(_macro_source_row(headline, source_entry, run_date, row.get("source_url") or row.get("url"), row.get("release_time") or row.get("time")))
    return events


def _parse_macro_table_schedule(
    raw_text: str,
    source_url: str,
    source_entry: dict[str, Any],
    run_date: date,
) -> list[dict[str, Any]]:
    document = lxml_html.fromstring(raw_text)
    events: list[dict[str, Any]] = []
    for row in document.xpath("//tr"):
        cell_texts = [_normalize_whitespace(" ".join(cell.itertext())) for cell in row.xpath("./th|./td")]
        cell_texts = [text for text in cell_texts if text]
        if len(cell_texts) < 2:
            continue

        row_date = None
        date_text = ""
        for cell_text in cell_texts:
            row_date = _extract_date(cell_text, run_date.year)
            if row_date is not None:
                date_text = cell_text
                break
        if row_date != run_date:
            continue

        release_time = ""
        for cell_text in cell_texts:
            matched_time = _extract_time(cell_text)
            if matched_time:
                release_time = matched_time
                break

        headline_candidates = [
            text
            for text in cell_texts
            if text != date_text and text != release_time and not _looks_like_date_or_time(text, run_date.year)
        ]
        headline = max(headline_candidates, key=len, default="")
        if not headline:
            headline = _first_link_text(row)
        if not headline:
            continue

        event_url = _first_link_url(row, source_url)
        events.append(_macro_source_row(headline, source_entry, run_date, event_url, release_time))
    return events


def _parse_macro_dated_list(
    raw_text: str,
    source_url: str,
    source_entry: dict[str, Any],
    run_date: date,
) -> list[dict[str, Any]]:
    document = lxml_html.fromstring(raw_text)
    candidates = document.xpath(
        "//article"
        " | //li"
        " | //tr"
        " | //div[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'event')]"
        " | //div[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'release')]"
        " | //div[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'press')]"
    )

    events: list[dict[str, Any]] = []
    seen_nodes: set[int] = set()
    for node in candidates:
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))

        text = _normalize_whitespace(" ".join(node.itertext()))
        node_date = _extract_date(text, run_date.year)
        if node_date is None:
            datetimes = [value for value in node.xpath(".//@datetime") if isinstance(value, str)]
            for value in datetimes:
                node_date = _extract_date(value, run_date.year)
                if node_date is not None:
                    break
        if node_date != run_date:
            continue

        release_time = _extract_time(text)
        headline = _first_link_text(node)
        if not headline:
            headline = _best_headline_from_text(text, run_date.year, release_time)
        if not headline:
            continue

        event_url = _first_link_url(node, source_url)
        events.append(_macro_source_row(headline, source_entry, run_date, event_url, release_time))
    return events


def _macro_source_row(
    headline: Any,
    source_entry: dict[str, Any],
    run_date: date,
    source_url: Any,
    release_time: Any,
) -> dict[str, Any]:
    return {
        "date": run_date.isoformat(),
        "event_name": str(headline).strip(),
        "release_time": str(release_time or source_entry.get("release_time") or "").strip(),
        "category": str(source_entry.get("category") or "macro").strip() or "macro",
        "importance": str(source_entry.get("importance") or "standard").strip() or "standard",
        "source_url": str(source_url or source_entry.get("url") or "").strip(),
        "source_name": str(source_entry.get("name") or "").strip(),
    }


def _dedupe_macro_source_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        headline = str(row.get("event_name") or "").strip()
        if not headline:
            continue
        key = "|".join(
            [
                str(row.get("date") or ""),
                str(row.get("source_name") or ""),
                str(row.get("release_time") or ""),
                headline,
            ]
        )
        deduped.setdefault(key, row)
    return sorted(
        deduped.values(),
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("release_time") or ""),
            str(item.get("source_name") or ""),
            str(item.get("event_name") or ""),
        ),
    )


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_date(text: str, fallback_year: int) -> date | None:
    normalized = _normalize_whitespace(text).replace("Sept ", "Sep ").replace("Sept.", "Sep.")
    candidate_patterns = (
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        (
            r"\b(?:(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)(?:day)?\,?\s+)?"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
            r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:,\s*\d{4})?\b"
        ),
    )
    for pattern in candidate_patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            parsed = _parse_date_candidate(match.group(0), fallback_year)
            if parsed is not None:
                return parsed
    return None


def _parse_date_candidate(raw_value: str, fallback_year: int) -> date | None:
    candidate = _normalize_whitespace(raw_value)
    candidate = re.sub(
        r"^(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)(?:day)?\,?\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = candidate.replace(".", "").replace("Sept ", "Sep ")
    formats = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%B %d", "%b %d")
    for fmt in formats:
        try:
            parsed = datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
        if "%Y" not in fmt and "%y" not in fmt:
            parsed = parsed.replace(year=fallback_year)
        return parsed
    return None


def _extract_time(text: str) -> str:
    normalized = _normalize_whitespace(text)
    match = re.search(
        r"\b(?:\d{1,2}:\d{2}(?:\s*(?:a\.?m\.?|p\.?m\.?|AM|PM))?|\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?|AM|PM))(?:\s*(?:ET|EST|EDT))?\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        return ""
    token = match.group(0).strip()
    if not re.search(r"\d", token):
        return ""
    return token


def _looks_like_date_or_time(text: str, fallback_year: int) -> bool:
    return _extract_date(text, fallback_year) is not None or bool(_extract_time(text))


def _first_link_text(node: Any) -> str:
    for value in node.xpath(".//a[normalize-space()]"):
        text = _normalize_whitespace(" ".join(value.itertext()))
        if text:
            return text
    return ""


def _first_link_url(node: Any, base_url: str) -> str:
    for value in node.xpath(".//a[@href]"):
        href = str(value.get("href") or "").strip()
        if href:
            return urljoin(base_url, href)
    return str(base_url)


def _best_headline_from_text(text: str, fallback_year: int, release_time: str) -> str:
    fragments = [fragment.strip(" -|") for fragment in re.split(r"[|]", _normalize_whitespace(text)) if fragment.strip(" -|")]
    candidates = [
        fragment
        for fragment in fragments
        if fragment != release_time and not _looks_like_date_or_time(fragment, fallback_year)
    ]
    return max(candidates, key=len, default="")


def _normalize_market_event(
    row: dict[str, Any],
    run_date: date,
    *,
    category: str | None = None,
) -> dict[str, Any] | None:
    change_pct = _to_float(row.get("change_pct") or row.get("percent_change") or row.get("pct"))
    material = bool(row.get("material")) or (change_pct is not None and abs(change_pct) >= 1.0)
    symbol = str(row.get("symbol") or row.get("name") or row.get("pair") or "").strip()
    headline = str(row.get("headline") or f"{symbol} moved {change_pct:.2f}%").strip() if change_pct is not None else str(row.get("headline") or symbol)
    return {
        "source": "market",
        "event_type": "market",
        "event_date": _event_date(row, run_date),
        "security_id": symbol,
        "relationship": "market",
        "headline": headline,
        "category": category or str(row.get("category") or "indexes"),
        "change_pct": change_pct,
        "material": material,
        "reference_url": str(row.get("url") or "").strip(),
        "metadata": row,
    }


def _parse_ir_feed(
    feed_url: str,
    feed_format: str,
    run_date: date,
    security_id: str,
    entry: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_text, _ = read_text_source(feed_url)
    if feed_format in {"rss", "atom", "xml"}:
        if _looks_like_html_document(raw_text):
            return _parse_ir_html(raw_text, run_date, security_id, feed_url)
        return _parse_ir_xml(raw_text, run_date, security_id, entry)
    if feed_format == "json":
        payload = json.loads(raw_text)
        items = payload if isinstance(payload, list) else payload.get("items", [])
        return [
            {
                "source": "ir",
                "event_type": "ir",
                "event_date": _event_date(item, run_date),
                "security_id": security_id,
                "relationship": "monitored",
                "headline": str(item.get("title") or item.get("headline") or "").strip(),
                "reference_url": str(item.get("url") or item.get("link") or "").strip(),
                "metadata": item,
            }
            for item in items
            if _event_date(item, run_date) == run_date.isoformat() and str(item.get("title") or item.get("headline") or "").strip()
        ]
    if feed_format == "html":
        return _parse_ir_html(raw_text, run_date, security_id, feed_url)
    raise ValueError(f"unsupported IR feed format: {feed_format}")


def _parse_ir_xml(raw_text: str, run_date: date, security_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(raw_text)
    items = root.findall(".//item") or root.findall(".//entry")
    events: list[dict[str, Any]] = []
    for item in items:
        title = _xml_text(item, "title")
        link = _xml_text(item, "link")
        if not link:
            link = item.findtext("{http://www.w3.org/2005/Atom}link") or ""
            if not link:
                link_node = item.find("{http://www.w3.org/2005/Atom}link")
                link = link_node.attrib.get("href", "") if link_node is not None else ""
        published = _xml_text(item, "pubDate") or _xml_text(item, "published") or _xml_text(item, "updated")
        item_date = _coerce_event_date(published) or run_date.isoformat()
        if item_date != run_date.isoformat() or not title:
            continue
        events.append(
            {
                "source": "ir",
                "event_type": "ir",
                "event_date": item_date,
                "security_id": security_id,
                "ticker": str(entry.get("ticker") or security_id),
                "relationship": "monitored",
                "headline": title,
                "reference_url": link,
                "metadata": {"published": published},
            }
        )
    return events


def _parse_ir_html(raw_text: str, run_date: date, security_id: str, base_url: str = "") -> list[dict[str, Any]]:
    document = lxml_html.fromstring(raw_text)
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in document.xpath("//a[@href]"):
        title = _normalize_whitespace(" ".join(node.itertext()))
        href = urljoin(base_url, str(node.get("href") or "").strip())
        if not _looks_like_ir_press_release(title):
            continue
        dedupe_key = (title.casefold(), href)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        events.append(
            {
                "source": "ir",
                "event_type": "ir",
                "event_date": run_date.isoformat(),
                "security_id": security_id,
                "relationship": "monitored",
                "headline": title,
                "reference_url": href,
                "metadata": {},
            }
        )
    return events[:10]


def _looks_like_html_document(raw_text: str) -> bool:
    snippet = raw_text.lstrip()[:500]
    return bool(re.search(r"<!doctype\s+html|<html\b|<body\b|<head\b", snippet, flags=re.IGNORECASE))


def _looks_like_ir_press_release(title: str) -> bool:
    normalized = _normalize_whitespace(title)
    if len(normalized) < 10:
        return False
    if not re.search(r"[A-Za-z]", normalized):
        return False
    lowered = normalized.casefold()
    if any(re.fullmatch(pattern, lowered) for pattern in IR_HTML_NAV_PATTERNS):
        return False
    if any(lowered.startswith(prefix) for prefix in ("skip to", "go to", "buy ", "log in", "sign in", "sign up")):
        return False
    return bool(IR_HTML_MATERIAL_TITLE_PATTERN.search(normalized))


def _load_finnhub_payload(run_date: date, api_key: str) -> dict[str, Any]:
    base_url = "https://finnhub.io/api/v1"
    session = requests.Session()
    earnings_response = session.get(
        f"{base_url}/calendar/earnings",
        params={"from": run_date.isoformat(), "to": run_date.isoformat(), "token": api_key},
        timeout=30,
    )
    earnings_response.raise_for_status()
    earnings_payload = earnings_response.json()

    indexes: list[dict[str, Any]] = []
    for symbol in DEFAULT_INDEX_SYMBOLS:
        response = session.get(f"{base_url}/quote", params={"symbol": symbol, "token": api_key}, timeout=30)
        response.raise_for_status()
        quote = response.json()
        indexes.append(
            {
                "symbol": symbol,
                "change_pct": quote.get("dp"),
                "headline": f"{symbol} moved {quote.get('dp', 0):.2f}%",
                "material": abs(float(quote.get("dp", 0) or 0)) >= 1.0,
            }
        )
    return {
        "earnings": earnings_payload.get("earningsCalendar", earnings_payload.get("earnings", [])),
        "indexes": indexes,
        "rates": [],
        "fx": [],
    }


def _ensure_index(path: Path, title: str, body: str) -> None:
    if path.exists():
        return
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def _xml_text(node: ElementTree.Element, tag_name: str) -> str:
    value = node.findtext(tag_name)
    if value:
        return value.strip()
    for child in node:
        if child.tag.endswith(tag_name) and child.text:
            return child.text.strip()
    return ""


def _event_date(row: dict[str, Any], fallback_date: date) -> str:
    candidates = [
        row.get("date"),
        row.get("event_date"),
        row.get("report_date"),
        row.get("published"),
        row.get("timestamp"),
    ]
    for candidate in candidates:
        coerced = _coerce_event_date(candidate)
        if coerced:
            return coerced
    return fallback_date.isoformat()


def _coerce_event_date(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None
