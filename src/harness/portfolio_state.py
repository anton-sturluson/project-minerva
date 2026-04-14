"""Portfolio state persistence for the morning brief workflow."""

from __future__ import annotations

import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

logger = logging.getLogger(__name__)


EMPTY_JSON_ARRAY = "[]\n"
EMPTY_JSONL = ""


@dataclass(slots=True)
class PortfolioPaths:
    """Filesystem layout for portfolio state."""

    workspace_root: Path

    @property
    def root(self) -> Path:
        return self.workspace_root / "data" / "01-portfolio"

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def history(self) -> Path:
        return self.root / "history"

    @property
    def holdings(self) -> Path:
        return self.current / "holdings.json"

    @property
    def watchlist(self) -> Path:
        return self.current / "watchlist.json"

    @property
    def universe(self) -> Path:
        return self.current / "universe.json"

    @property
    def adjacency_map(self) -> Path:
        return self.current / "adjacent-map.json"

    @property
    def adjacency_rendered(self) -> Path:
        return self.current / "adjacent-map.md"

    @property
    def thesis_cards(self) -> Path:
        return self.current / "thesis-cards.json"

    @property
    def thesis_rendered(self) -> Path:
        return self.current / "thesis-cards.md"

    @property
    def ir_registry(self) -> Path:
        return self.current / "ir-registry.json"

    @property
    def macro_registry(self) -> Path:
        return self.current / "macro-registry.json"

    @property
    def rendered(self) -> Path:
        return self.current / "rendered.md"

    @property
    def transactions(self) -> Path:
        return self.root / "transactions.json"

    @property
    def sync_log(self) -> Path:
        return self.history / "sync-log.jsonl"

    @property
    def universe_history(self) -> Path:
        return self.history / "universe-history.jsonl"

    @property
    def metadata_history(self) -> Path:
        return self.history / "metadata-history.jsonl"

    @property
    def rendered_history(self) -> Path:
        return self.history / "rendered-history.md"


def portfolio_paths(workspace_root: Path) -> PortfolioPaths:
    """Return normalized portfolio paths."""
    return PortfolioPaths(workspace_root=workspace_root.resolve())


def ensure_portfolio_layout(workspace_root: Path) -> PortfolioPaths:
    """Create the portfolio directory tree and default files when absent."""
    paths = portfolio_paths(workspace_root)
    paths.current.mkdir(parents=True, exist_ok=True)
    paths.history.mkdir(parents=True, exist_ok=True)

    _ensure_index(
        paths.root / "INDEX.md",
        title="Portfolio Data",
        body="Persistent holdings, watchlist, adjacency, thesis, and history state.",
    )
    _ensure_index(
        paths.current / "INDEX.md",
        title="Current Portfolio State",
        body="Latest synced holdings and locally curated monitoring metadata.",
    )
    _ensure_index(
        paths.history / "INDEX.md",
        title="Portfolio History",
        body="Compact sync and metadata logs for portfolio state changes.",
    )

    for json_path in (
        paths.holdings,
        paths.watchlist,
        paths.universe,
        paths.adjacency_map,
        paths.thesis_cards,
        paths.ir_registry,
        paths.transactions,
    ):
        if not json_path.exists():
            json_path.write_text(EMPTY_JSON_ARRAY, encoding="utf-8")
    for jsonl_path in (paths.sync_log, paths.universe_history, paths.metadata_history):
        if not jsonl_path.exists():
            jsonl_path.write_text(EMPTY_JSONL, encoding="utf-8")
    if not paths.macro_registry.exists():
        write_json(paths.macro_registry, _default_macro_registry())
    if not paths.adjacency_rendered.exists():
        paths.adjacency_rendered.write_text(render_adjacency_markdown([]), encoding="utf-8")
    if not paths.thesis_rendered.exists():
        paths.thesis_rendered.write_text(render_thesis_markdown([]), encoding="utf-8")
    if not paths.rendered.exists():
        paths.rendered.write_text("# Portfolio State\n\nNo sync has been run yet.\n", encoding="utf-8")
    if not paths.rendered_history.exists():
        paths.rendered_history.write_text("# Portfolio History\n\nNo history entries yet.\n", encoding="utf-8")
    return paths


def sync_portfolio(
    workspace_root: Path,
    *,
    as_of: date,
    holdings_source: str | None = None,
    transactions_source: str | None = None,
    watchlist_source: str | None = None,
    sheet_id: str | None = None,
    holdings_gid: str | None = None,
    transactions_gid: str | None = None,
) -> dict[str, Any]:
    """Sync holdings and transactions into portfolio state."""
    paths = ensure_portfolio_layout(workspace_root)
    previous_universe = load_json(paths.universe, default=[])

    resolved_holdings_source = holdings_source or _google_sheet_csv_url(sheet_id, holdings_gid)
    resolved_transactions_source = transactions_source or _google_sheet_csv_url(sheet_id, transactions_gid)

    holdings_rows = load_tabular_rows(resolved_holdings_source) if resolved_holdings_source else load_json(paths.holdings, default=[])
    transactions_rows = (
        load_tabular_rows(resolved_transactions_source) if resolved_transactions_source else load_json(paths.transactions, default=[])
    )
    if not holdings_rows:
        raise ValueError("no holdings source was provided and no existing holdings state was found")

    watchlist_rows = load_tabular_rows(watchlist_source) if watchlist_source else load_json(paths.watchlist, default=[])

    holdings = _dedupe_records(normalize_holdings(holdings_rows))
    watchlist = _dedupe_records(normalize_watchlist(watchlist_rows))
    universe = build_universe(holdings, watchlist)
    transactions = normalize_transactions(transactions_rows)

    write_json(paths.holdings, holdings)
    write_json(paths.watchlist, watchlist)
    write_json(paths.universe, universe)
    write_json(paths.transactions, transactions)

    change_summary = _universe_delta(previous_universe, universe)
    rendered = render_portfolio_summary(
        as_of=as_of,
        holdings=holdings,
        watchlist=watchlist,
        universe=universe,
        transactions=transactions,
        adjacency=load_json(paths.adjacency_map, default=[]),
        thesis_cards=load_json(paths.thesis_cards, default=[]),
    )
    paths.rendered.write_text(rendered, encoding="utf-8")

    append_jsonl(
        paths.sync_log,
        {
            "timestamp": now_utc_iso(),
            "as_of": as_of.isoformat(),
            "sources": {
                "holdings": resolved_holdings_source or str(paths.holdings),
                "transactions": resolved_transactions_source or str(paths.transactions),
                "watchlist": watchlist_source or str(paths.watchlist),
            },
            "counts": {
                "holdings": len(holdings),
                "watchlist": len(watchlist),
                "universe": len(universe),
                "transactions": len(transactions),
            },
            "changes": change_summary,
        },
    )
    if change_summary["added"] or change_summary["removed"]:
        append_jsonl(
            paths.universe_history,
            {
                "timestamp": now_utc_iso(),
                "as_of": as_of.isoformat(),
                **change_summary,
            },
        )
    append_jsonl(
        paths.metadata_history,
        {
            "timestamp": now_utc_iso(),
            "event": "portfolio-sync",
            "rendered_path": str(paths.rendered),
            "counts": {"adjacency": len(load_json(paths.adjacency_map, default=[])), "thesis_cards": len(load_json(paths.thesis_cards, default=[]))},
        },
    )
    update_history_render(paths)
    return {
        "as_of": as_of.isoformat(),
        "holdings_count": len(holdings),
        "watchlist_count": len(watchlist),
        "universe_count": len(universe),
        "transactions_count": len(transactions),
        "rendered_path": paths.rendered,
        "sources": {
            "holdings": resolved_holdings_source,
            "transactions": resolved_transactions_source,
            "watchlist": watchlist_source or str(paths.watchlist),
        },
    }


def add_adjacency_entry(
    workspace_root: Path,
    *,
    monitored: str,
    adjacent: str,
    relationship_type: str,
    note: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    """Create or replace one adjacency entry."""
    paths = ensure_portfolio_layout(workspace_root)
    entries = load_json(paths.adjacency_map, default=[])
    monitored_id = canonical_security_id(monitored)
    adjacent_id = canonical_security_id(adjacent)
    normalized_relationship_type = relationship_type.strip()

    if not monitored_id or not adjacent_id:
        raise ValueError("both monitored and adjacent identifiers are required")
    if not normalized_relationship_type:
        raise ValueError("relationship type is required")

    replacement = {
        "monitored": monitored_id,
        "adjacent": adjacent_id,
        "relationship_type": normalized_relationship_type,
        "note": (note or "").strip(),
        "priority": (priority or "").strip(),
        "updated_at": now_utc_iso(),
    }
    filtered = [
        entry
        for entry in entries
        if not (
            str(entry.get("monitored", "")).upper() == monitored_id
            and str(entry.get("adjacent", "")).upper() == adjacent_id
            and str(entry.get("relationship_type", "")).strip().lower() == normalized_relationship_type.lower()
        )
    ]
    filtered.append(replacement)
    filtered.sort(key=lambda item: (item["monitored"], item["adjacent"], item["relationship_type"]))
    write_json(paths.adjacency_map, filtered)
    paths.adjacency_rendered.write_text(render_adjacency_markdown(filtered), encoding="utf-8")
    append_jsonl(
        paths.metadata_history,
        {"timestamp": now_utc_iso(), "event": "adjacency-add", "entry": replacement},
    )
    update_history_render(paths)
    return replacement


def remove_adjacency_entry(
    workspace_root: Path,
    *,
    monitored: str,
    adjacent: str,
    relationship_type: str | None = None,
) -> dict[str, Any]:
    """Remove adjacency entries for a monitored-adjacent pair."""
    paths = ensure_portfolio_layout(workspace_root)
    entries = load_json(paths.adjacency_map, default=[])
    monitored_id = canonical_security_id(monitored)
    adjacent_id = canonical_security_id(adjacent)
    normalized_relationship_type = (relationship_type or "").strip().lower()
    if not monitored_id or not adjacent_id:
        raise ValueError("both monitored and adjacent identifiers are required")
    kept = [
        entry
        for entry in entries
        if not (
            str(entry.get("monitored", "")).upper() == monitored_id
            and str(entry.get("adjacent", "")).upper() == adjacent_id
            and (
                not normalized_relationship_type
                or str(entry.get("relationship_type", "")).strip().lower() == normalized_relationship_type
            )
        )
    ]
    removed_count = len(entries) - len(kept)
    write_json(paths.adjacency_map, kept)
    paths.adjacency_rendered.write_text(render_adjacency_markdown(kept), encoding="utf-8")
    append_jsonl(
        paths.metadata_history,
        {
            "timestamp": now_utc_iso(),
            "event": "adjacency-remove",
            "monitored": monitored_id,
            "adjacent": adjacent_id,
            "relationship_type": normalized_relationship_type,
            "removed_count": removed_count,
        },
    )
    update_history_render(paths)
    return {
        "removed_count": removed_count,
        "monitored": monitored_id,
        "adjacent": adjacent_id,
        "relationship_type": normalized_relationship_type,
    }


def set_thesis_card(
    workspace_root: Path,
    *,
    security: str,
    summary: str,
    expectations: list[str],
    disconfirming_signals: list[str],
) -> dict[str, Any]:
    """Create or replace one thesis card."""
    paths = ensure_portfolio_layout(workspace_root)
    security_id = canonical_security_id(security)
    normalized_summary = summary.strip()
    if not security_id:
        raise ValueError("security identifier is required")
    if not normalized_summary:
        raise ValueError("summary is required")
    cards = load_json(paths.thesis_cards, default=[])
    replacement = {
        "security_id": security_id,
        "thesis_summary": normalized_summary,
        "key_expectations": [item for item in (part.strip() for part in expectations) if item],
        "disconfirming_signals": [item for item in (part.strip() for part in disconfirming_signals) if item],
        "updated_at": now_utc_iso(),
    }
    filtered = [card for card in cards if str(card.get("security_id", "")).upper() != security_id]
    filtered.append(replacement)
    filtered.sort(key=lambda item: item["security_id"])
    write_json(paths.thesis_cards, filtered)
    paths.thesis_rendered.write_text(render_thesis_markdown(filtered), encoding="utf-8")
    append_jsonl(
        paths.metadata_history,
        {"timestamp": now_utc_iso(), "event": "thesis-set", "security_id": security_id},
    )
    update_history_render(paths)
    return replacement


FINNHUB_SYMBOL_TABLE: dict[str, dict[str, Any]] = {
    "ACFN": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "ACFN"},
    "AIM": {"exchange": "NYSE MKT", "country": "US", "sec_registered": True, "finnhub_symbol": "AIM"},
    "AVGO": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "AVGO"},
    "BEPC": {"exchange": "NYSE", "country": "US", "sec_registered": True, "finnhub_symbol": "BEPC"},
    "DUOL": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "DUOL"},
    "GOOGL": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "GOOGL"},
    "IMVT": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "IMVT"},
    "KPG": {"exchange": "ASX", "country": "AU", "sec_registered": False, "finnhub_symbol": "KPG.AX"},
    "LGCY": {"exchange": "NYSE MKT", "country": "US", "sec_registered": True, "finnhub_symbol": "LGCY"},
    "OSCR": {"exchange": "NYSE", "country": "US", "sec_registered": True, "finnhub_symbol": "OSCR"},
    "SPOT": {"exchange": "NYSE", "country": "LU", "sec_registered": True, "finnhub_symbol": "SPOT"},
    "TOI": {"exchange": "TSXV", "country": "CA", "sec_registered": False, "finnhub_symbol": "TOI.V"},
    "TSLA": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "TSLA"},
    "TSM": {"exchange": "TWSE / NYSE ADR", "country": "TW", "sec_registered": True, "finnhub_symbol": "TSM"},
    "VCSH": {"exchange": "NYSE Arca", "country": "US", "sec_registered": True, "finnhub_symbol": "VCSH"},
    "ZDC": {"exchange": "TSXV", "country": "CA", "sec_registered": False, "finnhub_symbol": "ZDC.V"},
}


def enrich_portfolio(
    workspace_root: Path,
    *,
    finnhub_api_key: str | None = None,
    delay_seconds: float = 0.1,
) -> dict[str, Any]:
    """Enrich portfolio records with exchange, country, sec_registered, and finnhub_symbol."""
    paths = ensure_portfolio_layout(workspace_root)
    holdings = load_json(paths.holdings, default=[])
    watchlist = load_json(paths.watchlist, default=[])

    enriched_count = 0
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    for record_list in (holdings, watchlist):
        for record in record_list:
            ticker = str(record.get("ticker") or record.get("security_id") or "").strip().upper()
            if not ticker:
                continue

            if record.get("exchange") and record.get("finnhub_symbol") and "sec_registered" in record:
                skipped.append(ticker)
                continue

            metadata = _resolve_enrichment_metadata(ticker, record, finnhub_api_key, delay_seconds)
            if metadata:
                record.update(metadata)
                enriched_count += 1
            else:
                errors.append({"ticker": ticker, "error": "could not resolve metadata"})

    write_json(paths.holdings, holdings)
    write_json(paths.watchlist, watchlist)

    universe = build_universe(holdings, watchlist)
    write_json(paths.universe, universe)

    return {
        "enriched_count": enriched_count,
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "errors": errors,
    }


def _resolve_enrichment_metadata(
    ticker: str,
    record: dict[str, Any],
    finnhub_api_key: str | None,
    delay_seconds: float,
) -> dict[str, Any] | None:
    if ticker in FINNHUB_SYMBOL_TABLE:
        return dict(FINNHUB_SYMBOL_TABLE[ticker])

    if not finnhub_api_key:
        return None

    base_url = "https://finnhub.io/api/v1"
    session = requests.Session()

    try:
        time.sleep(delay_seconds)
        profile_resp = session.get(
            f"{base_url}/stock/profile2",
            params={"symbol": ticker, "token": finnhub_api_key},
            timeout=30,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()

        if profile.get("ticker"):
            return {
                "exchange": str(profile.get("exchange") or "").strip(),
                "country": str(profile.get("country") or "").strip(),
                "sec_registered": str(profile.get("country") or "").strip() == "US",
                "finnhub_symbol": str(profile.get("ticker") or ticker).strip(),
            }

        company_name = str(record.get("company_name") or "").strip()
        if company_name:
            time.sleep(delay_seconds)
            search_resp = session.get(
                f"{base_url}/search",
                params={"q": company_name, "token": finnhub_api_key},
                timeout=30,
            )
            search_resp.raise_for_status()
            results = search_resp.json().get("result", [])
            if results:
                best = results[0]
                finnhub_sym = str(best.get("symbol") or ticker).strip()
                time.sleep(delay_seconds)
                profile_resp2 = session.get(
                    f"{base_url}/stock/profile2",
                    params={"symbol": finnhub_sym, "token": finnhub_api_key},
                    timeout=30,
                )
                profile_resp2.raise_for_status()
                profile2 = profile_resp2.json()
                if profile2.get("ticker"):
                    return {
                        "exchange": str(profile2.get("exchange") or "").strip(),
                        "country": str(profile2.get("country") or "").strip(),
                        "sec_registered": str(profile2.get("country") or "").strip() == "US",
                        "finnhub_symbol": str(profile2.get("ticker") or finnhub_sym).strip(),
                    }
    except Exception as exc:
        logger.warning("enrichment failed for %s: %s", ticker, exc)

    return None


def render_portfolio_summary(
    *,
    as_of: date,
    holdings: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    universe: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    adjacency: list[dict[str, Any]],
    thesis_cards: list[dict[str, Any]],
) -> str:
    """Render current portfolio state as deterministic markdown."""
    holding_lines = [f"- `{item['security_id']}` | {item.get('company_name', 'Unknown')} | {item.get('weight', '')}" for item in holdings]
    watchlist_lines = [f"- `{item['security_id']}` | {item.get('company_name', 'Unknown')}" for item in watchlist]
    recent_transactions = transactions[:10]
    transaction_lines = [
        f"- {item.get('trade_date', '')} | `{item.get('security_id', '')}` | {item.get('action', '')} | {item.get('quantity', '')}"
        for item in recent_transactions
    ]
    return "\n".join(
        [
            "# Portfolio State",
            "",
            f"- As of: {as_of.isoformat()}",
            f"- Holdings: {len(holdings)}",
            f"- Watchlist: {len(watchlist)}",
            f"- Universe: {len(universe)}",
            f"- Transactions: {len(transactions)}",
            f"- Adjacency mappings: {len(adjacency)}",
            f"- Thesis cards: {len(thesis_cards)}",
            "",
            "## Holdings",
            *(holding_lines or ["- None"]),
            "",
            "## Watchlist",
            *(watchlist_lines or ["- None"]),
            "",
            "## Recent Transactions",
            *(transaction_lines or ["- None"]),
        ]
    ).rstrip() + "\n"


def render_adjacency_markdown(entries: list[dict[str, Any]]) -> str:
    """Render adjacency entries as markdown."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in sorted(entries, key=lambda item: (item.get("monitored", ""), item.get("adjacent", ""))):
        grouped.setdefault(str(entry.get("monitored", "")), []).append(entry)
    lines = ["# Adjacency Map", ""]
    if not grouped:
        lines.append("No adjacency mappings configured.")
        return "\n".join(lines) + "\n"
    for monitored, members in grouped.items():
        lines.append(f"## {monitored}")
        for member in members:
            note = f" | {member['note']}" if member.get("note") else ""
            priority = f" | priority={member['priority']}" if member.get("priority") else ""
            lines.append(f"- `{member['adjacent']}` | {member['relationship_type']}{priority}{note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_thesis_markdown(cards: list[dict[str, Any]]) -> str:
    """Render thesis cards as markdown."""
    lines = ["# Thesis Cards", ""]
    if not cards:
        lines.append("No thesis cards configured.")
        return "\n".join(lines) + "\n"
    for card in sorted(cards, key=lambda item: item.get("security_id", "")):
        expectations = [f"- {item}" for item in card.get("key_expectations", [])] or ["- None"]
        disconfirming = [f"- {item}" for item in card.get("disconfirming_signals", [])] or ["- None"]
        lines.extend(
            [
                f"## {card['security_id']}",
                "",
                card.get("thesis_summary", "").strip() or "(no thesis summary)",
                "",
                "### Key Expectations",
                *expectations,
                "",
                "### Disconfirming Signals",
                *disconfirming,
                "",
                f"Updated: {card.get('updated_at', '')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_universe(holdings: list[dict[str, Any]], watchlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine holdings and watchlist into a monitored universe."""
    merged: dict[str, dict[str, Any]] = {}
    for row in holdings + watchlist:
        security_id = str(row["security_id"])
        current = dict(merged.get(security_id, {}))
        current.update(row)
        sources = sorted(set(current.get("sources", [])) | {str(row.get("source_kind", "monitored"))})
        current["sources"] = sources
        merged[security_id] = current
    return [merged[key] for key in sorted(merged)]


def normalize_holdings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize holdings rows into canonical portfolio records."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        record = _normalize_security_row(row, source_kind="holding")
        if record["security_id"]:
            normalized.append(record)
    return normalized


def normalize_watchlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize watchlist rows into canonical portfolio records."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        record = _normalize_security_row(row, source_kind="watchlist")
        if record["security_id"]:
            normalized.append(record)
    return normalized


def normalize_transactions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize transaction rows."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        ticker = _clean_ticker(row.get("ticker") or row.get("symbol") or row.get("security_id") or row.get("security"))
        company_name = _clean_name(row.get("company") or row.get("name") or row.get("security"))
        security_id = canonical_security_id(ticker or company_name)
        trade_date = _stringify_date(row.get("date") or row.get("trade_date") or row.get("timestamp"))
        if not security_id:
            continue
        normalized.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "company_name": company_name,
                "trade_date": trade_date,
                "action": str(row.get("action") or row.get("side") or row.get("transaction") or "").strip().lower(),
                "quantity": _maybe_number(row.get("quantity") or row.get("shares")),
                "price": _maybe_number(row.get("price")),
                "notes": str(row.get("notes") or row.get("memo") or "").strip(),
            }
        )
    normalized.sort(key=lambda item: (item.get("trade_date", ""), item["security_id"]), reverse=True)
    return normalized


def load_tabular_rows(source: str | None) -> list[dict[str, Any]]:
    """Load list-like data from JSON, YAML, or CSV."""
    if not source:
        return []
    payload, suffix = load_payload(source)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "items", "holdings", "transactions", "watchlist", "events"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    if suffix == ".csv" and isinstance(payload, str):
        return list(csv.DictReader(StringIO(payload)))
    raise ValueError(f"unsupported tabular source: {source}")


def load_payload(source: str) -> tuple[Any, str]:
    """Load a structured payload from a local file or URL."""
    raw_text, suffix = read_text_source(source)
    normalized_suffix = suffix.lower()
    if normalized_suffix == ".csv":
        return list(csv.DictReader(StringIO(raw_text))), normalized_suffix
    if normalized_suffix in {".yaml", ".yml"}:
        return yaml.safe_load(raw_text) or [], normalized_suffix
    if normalized_suffix == ".jsonl":
        return [json.loads(line) for line in raw_text.splitlines() if line.strip()], normalized_suffix
    return json.loads(raw_text), normalized_suffix


def read_text_source(source: str) -> tuple[str, str]:
    """Read text from a local path or HTTP URL."""
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(source, timeout=30)
        response.raise_for_status()
        suffix = Path(parsed.path).suffix or _suffix_from_content_type(response.headers.get("content-type", ""))
        return response.text, suffix or ".json"
    candidate = Path(source).expanduser()
    text = candidate.read_text(encoding="utf-8")
    return text, candidate.suffix or ".json"


def write_json(path: Path, payload: Any) -> None:
    """Write deterministic JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path, *, default: Any) -> Any:
    """Load JSON with a default when the file is missing."""
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON record to a log file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file when present."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def update_history_render(paths: PortfolioPaths) -> None:
    """Render a compact markdown history summary."""
    sync_entries = read_jsonl(paths.sync_log)[-10:]
    metadata_entries = read_jsonl(paths.metadata_history)[-10:]
    lines = ["# Portfolio History", "", "## Recent Syncs"]
    if not sync_entries:
        lines.append("- None")
    else:
        for entry in reversed(sync_entries):
            counts = entry.get("counts", {})
            lines.append(
                f"- {entry.get('as_of', '')} | holdings={counts.get('holdings', 0)} | universe={counts.get('universe', 0)}"
            )
    lines.extend(["", "## Recent Metadata Changes"])
    if not metadata_entries:
        lines.append("- None")
    else:
        for entry in reversed(metadata_entries):
            lines.append(f"- {entry.get('timestamp', '')} | {entry.get('event', '')}")
    paths.rendered_history.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def canonical_security_id(value: Any) -> str:
    """Return a stable uppercase security identifier."""
    ticker = _clean_ticker(value)
    if ticker:
        return ticker
    name = _clean_name(value)
    if not name:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug.upper()


def now_utc_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso_date(raw: str | None) -> date:
    """Parse an ISO date string, defaulting to today when absent."""
    if not raw:
        return date.today()
    return date.fromisoformat(raw)


def _normalize_security_row(row: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
    ticker = _clean_ticker(row.get("ticker") or row.get("symbol"))
    company_name = _clean_name(row.get("company") or row.get("name") or row.get("security"))
    security_id = canonical_security_id(row.get("security_id") or ticker or company_name or row.get("cusip"))
    record: dict[str, Any] = {
        "security_id": security_id,
        "ticker": ticker,
        "company_name": company_name,
        "cusip": str(row.get("cusip") or "").strip(),
        "weight": _maybe_number(row.get("weight") or row.get("portfolio_weight")),
        "shares": _maybe_number(row.get("shares") or row.get("quantity")),
        "notes": str(row.get("notes") or "").strip(),
        "source_kind": source_kind,
    }
    for field in ("exchange", "country", "finnhub_symbol"):
        value = row.get(field)
        if value is not None and str(value).strip():
            record[field] = str(value).strip()
    if "sec_registered" in row:
        raw = row["sec_registered"]
        if isinstance(raw, bool):
            record["sec_registered"] = raw
        elif str(raw).strip().lower() in {"true", "1", "yes"}:
            record["sec_registered"] = True
        elif str(raw).strip().lower() in {"false", "0", "no"}:
            record["sec_registered"] = False
    return record


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        if not record.get("security_id"):
            continue
        deduped[str(record["security_id"])] = record
    return [deduped[key] for key in sorted(deduped)]


def _universe_delta(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, list[str]]:
    previous_ids = {str(item.get("security_id", "")) for item in previous}
    current_ids = {str(item.get("security_id", "")) for item in current}
    return {
        "added": sorted(current_ids - previous_ids),
        "removed": sorted(previous_ids - current_ids),
    }


def _maybe_number(value: Any) -> float | int | None:
    if value in {None, "", "null"}:
        return None
    if isinstance(value, (int, float)):
        return value
    raw = str(value).strip().replace(",", "").replace("%", "")
    if not raw:
        return None
    try:
        if raw.isdigit():
            return int(raw)
        return float(raw)
    except ValueError:
        return None


def _stringify_date(value: Any) -> str:
    if value in {None, ""}:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return raw


def _clean_ticker(value: Any) -> str:
    raw = str(value or "").strip().upper()
    raw = raw.replace("/", "-")
    if not raw or raw in {"NONE", "NAN", "NULL"}:
        return ""
    return raw


def _clean_name(value: Any) -> str:
    raw = str(value or "").strip()
    return "" if raw.upper() in {"NONE", "NAN", "NULL"} else raw


def _ensure_index(path: Path, *, title: str, body: str) -> None:
    if path.exists():
        return
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def _google_sheet_csv_url(sheet_id: str | None, gid: str | None) -> str | None:
    if not sheet_id or not gid:
        return None
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def _suffix_from_content_type(content_type: str) -> str:
    lowered = content_type.lower()
    if "csv" in lowered:
        return ".csv"
    if "yaml" in lowered or "yml" in lowered:
        return ".yaml"
    if "jsonl" in lowered:
        return ".jsonl"
    return ".json"


def _default_macro_registry() -> dict[str, Any]:
    return {
        "sources": [
            {"name": "BLS", "category": "macro", "url": "https://www.bls.gov/schedule/news_release/"},
            {"name": "BEA", "category": "macro", "url": "https://www.bea.gov/news/schedule"},
            {"name": "Federal Reserve", "category": "policy", "url": "https://www.federalreserve.gov/newsevents.htm"},
            {"name": "Treasury", "category": "policy", "url": "https://home.treasury.gov/news/press-releases"},
        ]
    }
