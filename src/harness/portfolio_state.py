"""Portfolio state persistence for the morning brief workflow."""

from __future__ import annotations

import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from io import StringIO
from pathlib import Path
from typing import Any, Mapping, NotRequired, Sequence, TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import yaml

logger = logging.getLogger(__name__)


EMPTY_JSON_ARRAY = "[]\n"
EMPTY_JSONL = ""

# Section-header rows in Google Sheet that are not real securities.
NON_SECURITY_TICKERS = frozenset({
    "CASH", "TOTAL", "CURRENT ASSET", "INVESTABLE",
    "NON-INVESTABLE", "INVESTABLE CURRENT ASSET",
})

THESIS_CARD_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
THESIS_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
FISCAL_PERIOD_PATTERN = re.compile(r"^(FY\d{4}|H[12] FY\d{4}|Q[1-4] FY\d{4})$")
FISCAL_PERIOD_EXAMPLES = "FY2026, H1 FY2026, H2 FY2026, Q1 FY2026, Q2 FY2026, Q3 FY2026, Q4 FY2026"
MAX_THESIS_LIST_ITEMS = 5
MAX_THESIS_METRICS = 5
MAIN_PORTFOLIO = "Main"
_GVIZ_RESPONSE_LIMIT = 10 * 1024 * 1024
_GVIZ_PERCENTAGE_POINT_FIELDS = frozenset({"weight", "cost_weight", "target_weight"})
_GVIZ_DATE_PATTERN = re.compile(r"^Date\((\d{4}),(\d{1,2}),(\d{1,2})\)$")


class EnrichmentField(StrEnum):
    EXCHANGE = "exchange"
    COUNTRY = "country"
    SEC_REGISTERED = "sec_registered"
    FINNHUB_SYMBOL = "finnhub_symbol"


class ThesisMetricObservation(TypedDict):
    """One dated or undated observation for a thesis-card metric."""

    period: str
    value: str
    date: NotRequired[str]
    source: NotRequired[str]


class ThesisMetric(TypedDict):
    """Metric tracked on a thesis card."""

    name: str
    unit: str
    observations: list[ThesisMetricObservation]


class ThesisCard(TypedDict):
    """Current thesis-card schema."""

    card_id: str
    ticker_symbols: list[str]
    summary: str
    core_thesis: list[str]
    key_metrics: list[ThesisMetric]
    signals: list[str]
    game_plan: NotRequired[str]
    updated_at: str


# Explicit mapping from normalized-lowercase CSV headers to canonical keys.
_CSV_HEADER_MAP: dict[str, str] = {
    "ticker": "ticker",
    "category": "category",
    "year of purcase": "year_of_purchase",
    "cost": "cost",
    "# shares": "shares",
    "total cost": "total_cost",
    "price": "price",
    "market value": "market_value",
    "% change": "pct_change",
    "net": "net",
    "cagr": "cagr",
    "% portfolio\n(value-based)": "weight",
    "% portfolio (value-based)": "weight",
    "% portfolio\n(cost-based)": "cost_weight",
    "% portfolio (cost-based)": "cost_weight",
    "target %\n(value-based)": "target_weight",
    "target % (value-based)": "target_weight",
    "target diff": "target_diff",
    "cagr target": "cagr_target",
    "price target": "price_target",
    "target year": "target_year",
    "exchange": "exchange",
}


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

    # Fetch and normalize every source before replacing any current state. A
    # lookup, schema, or validation failure therefore leaves the prior state intact.
    holdings_rows = load_tabular_rows(resolved_holdings_source) if resolved_holdings_source else load_json(paths.holdings, default=[])
    transactions_rows = (
        load_tabular_rows(resolved_transactions_source) if resolved_transactions_source else load_json(paths.transactions, default=[])
    )
    if not holdings_rows:
        raise ValueError("no holdings source was provided and no existing holdings state was found")

    watchlist_rows = load_tabular_rows(watchlist_source) if watchlist_source else load_json(paths.watchlist, default=[])

    holdings = _dedupe_records(normalize_holdings(holdings_rows))
    if not holdings:
        raise ValueError("holdings source contained zero valid Main portfolio securities")
    watchlist = _dedupe_records(normalize_watchlist(watchlist_rows))
    transactions = normalize_transactions(transactions_rows)

    # Carry forward enrichment fields from previous holdings so a re-sync
    # from the Google Sheet does not lose country/sec_registered/finnhub_symbol.
    previous_holdings = load_json(paths.holdings, default=[])
    _carry_forward_enrichment(holdings, previous_holdings)

    universe = build_universe(holdings, watchlist)
    adjacency = load_json(paths.adjacency_map, default=[])
    thesis_cards = load_json(paths.thesis_cards, default=[])
    if not isinstance(adjacency, list) or not isinstance(thesis_cards, list):
        raise ValueError("adjacency and thesis metadata must be JSON arrays")
    change_summary = _universe_delta(previous_universe, universe)
    rendered = render_portfolio_summary(
        as_of=as_of,
        holdings=holdings,
        watchlist=watchlist,
        universe=universe,
        transactions=transactions,
        adjacency=adjacency,
        thesis_cards=thesis_cards,
    )
    timestamp = now_utc_iso()
    sync_entry = {
        "timestamp": timestamp,
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
    }
    metadata_entry = {
        "timestamp": timestamp,
        "event": "portfolio-sync",
        "rendered_path": str(paths.rendered),
        "counts": {"adjacency": len(adjacency), "thesis_cards": len(thesis_cards)},
    }
    history_rendered = _render_history_markdown(
        [*read_jsonl(paths.sync_log), sync_entry],
        [*read_jsonl(paths.metadata_history), metadata_entry],
    )

    write_json(paths.holdings, holdings)
    write_json(paths.watchlist, watchlist)
    write_json(paths.universe, universe)
    write_json(paths.transactions, transactions)
    paths.rendered.write_text(rendered, encoding="utf-8")
    append_jsonl(paths.sync_log, sync_entry)
    if change_summary["added"] or change_summary["removed"]:
        append_jsonl(
            paths.universe_history,
            {"timestamp": timestamp, "as_of": as_of.isoformat(), **change_summary},
        )
    append_jsonl(paths.metadata_history, metadata_entry)
    paths.rendered_history.write_text(history_rendered, encoding="utf-8")
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


def validate_fiscal_period(value: str) -> str:
    """Validate and normalize a thesis metric fiscal period."""
    period = value.strip()
    if not FISCAL_PERIOD_PATTERN.match(period):
        raise ValueError(
            "metric observation period must use fiscal format; "
            f"examples: {FISCAL_PERIOD_EXAMPLES}"
        )
    return period


def set_thesis_card(
    workspace_root: Path,
    *,
    card_id: str,
    ticker_symbols: list[str],
    summary: str,
    core_thesis: list[str],
    signals: list[str],
    game_plan: str | None = None,
) -> ThesisCard:
    """Create or replace a thesis card definition while preserving metrics."""
    paths = ensure_portfolio_layout(workspace_root)
    normalized_card_id = _normalize_thesis_card_id(card_id)
    normalized_tickers = _normalize_thesis_tickers(ticker_symbols)
    normalized_summary = summary.strip()
    normalized_core_thesis = _normalize_thesis_list(core_thesis, field_name="core_thesis")
    normalized_signals = _normalize_thesis_list(signals, field_name="signals")

    if not normalized_summary:
        raise ValueError("summary is required for a thesis card")

    cards = _load_thesis_cards(paths)
    existing = next((card for card in cards if card.get("card_id") == normalized_card_id), None)
    # Preserve-on-omit: when game_plan is None (flag not passed) keep the existing
    # value; when an explicit string is passed, strip and use it (empty string clears).
    if game_plan is None:
        normalized_game_plan = str(existing.get("game_plan", "")).strip() if existing else ""
    else:
        normalized_game_plan = game_plan.strip()
    replacement: ThesisCard = {
        "card_id": normalized_card_id,
        "ticker_symbols": normalized_tickers,
        "summary": normalized_summary,
        "core_thesis": normalized_core_thesis,
        "key_metrics": list(existing.get("key_metrics", [])) if existing else [],
        "signals": normalized_signals,
        "game_plan": normalized_game_plan,
        "updated_at": now_utc_iso(),
    }
    updated_cards = [card for card in cards if card.get("card_id") != normalized_card_id]
    updated_cards.append(replacement)
    _write_thesis_cards(paths, updated_cards, event="thesis-set", event_payload={"card_id": normalized_card_id})
    return replacement


def add_thesis_metric(
    workspace_root: Path,
    *,
    card_id: str,
    name: str,
    unit: str | None,
    period: str,
    value: str,
    date: str | None,
    source: str | None,
) -> ThesisMetric:
    """Append one observation to a thesis card metric, creating the metric if needed."""
    paths = ensure_portfolio_layout(workspace_root)
    normalized_card_id = _normalize_thesis_card_id(card_id)
    metric_name = name.strip()
    metric_value = value.strip()
    metric_unit = (unit or "").strip()
    metric_period = validate_fiscal_period(period)
    if not metric_name:
        raise ValueError("metric name is required")
    if not metric_value:
        raise ValueError("metric observation value is required")

    cards = _load_thesis_cards(paths)
    card = next((item for item in cards if item.get("card_id") == normalized_card_id), None)
    if not card:
        raise ValueError(
            f"no thesis card exists for `{normalized_card_id}`; create it first with "
            f"`portfolio thesis set {normalized_card_id} --ticker GTLB --summary ...`"
        )

    metrics = card.setdefault("key_metrics", [])
    metric: ThesisMetric | None = next(
        (item for item in metrics if item["name"].strip().lower() == metric_name.lower()),
        None,
    )
    if metric is None:
        if len(metrics) >= MAX_THESIS_METRICS:
            raise ValueError(f"a thesis card supports a maximum of {MAX_THESIS_METRICS} key metrics")
        metric = {"name": metric_name, "unit": metric_unit, "observations": []}
        metrics.append(metric)
    elif metric_unit:
        metric["unit"] = metric_unit
    else:
        metric.setdefault("unit", "")

    observation: ThesisMetricObservation = {"period": metric_period, "value": metric_value}
    normalized_date = (date or "").strip()
    normalized_source = (source or "").strip()
    if normalized_date:
        observation["date"] = normalized_date
    if normalized_source:
        observation["source"] = normalized_source
    metric.setdefault("observations", []).append(observation)
    card["updated_at"] = now_utc_iso()

    _write_thesis_cards(
        paths,
        cards,
        event="thesis-metric-add",
        event_payload={"card_id": normalized_card_id, "metric": metric_name, "period": metric_period},
    )
    return metric


def get_thesis_by_ticker(workspace_root: Path, *, ticker: str) -> list[ThesisCard]:
    """Return thesis cards linked to a ticker symbol."""
    paths = ensure_portfolio_layout(workspace_root)
    normalized_ticker = _normalize_thesis_tickers([ticker])[0]
    cards = _load_thesis_cards(paths)
    return [
        card
        for card in sorted(cards, key=lambda item: item["card_id"])
        if normalized_ticker in {symbol.strip().upper() for symbol in card["ticker_symbols"]}
    ]


def _load_thesis_cards(paths: PortfolioPaths) -> list[ThesisCard]:
    cards = load_json(paths.thesis_cards, default=[])
    if not isinstance(cards, list):
        raise ValueError("thesis-cards.json must contain a JSON array")
    return [card for card in cards if isinstance(card, dict) and "card_id" in card]


def _write_thesis_cards(
    paths: PortfolioPaths,
    cards: list[ThesisCard],
    *,
    event: str,
    event_payload: dict[str, str],
) -> None:
    sorted_cards = sorted(cards, key=lambda item: item["card_id"])
    write_json(paths.thesis_cards, sorted_cards)
    paths.thesis_rendered.write_text(render_thesis_markdown(sorted_cards), encoding="utf-8")
    append_jsonl(paths.metadata_history, {"timestamp": now_utc_iso(), "event": event, **event_payload})
    update_history_render(paths)


def _normalize_thesis_card_id(value: str) -> str:
    card_id = (value or "").strip()
    if not card_id:
        raise ValueError("card_id is required")
    if not THESIS_CARD_ID_PATTERN.match(card_id):
        raise ValueError(
            "card_id must be lowercase kebab-style using letters, numbers, and hyphens; "
            "examples: `gtlb`, `memory-hbm`, `mu-specific`"
        )
    return card_id


def _normalize_thesis_tickers(values: list[str]) -> list[str]:
    tickers = _split_thesis_values(values)
    normalized: list[str] = []
    for ticker in tickers:
        candidate = ticker.upper()
        if not THESIS_TICKER_PATTERN.match(candidate):
            raise ValueError(
                f"ticker symbol `{ticker}` is invalid; use uppercase ticker syntax, examples: `GTLB`, `MU`, `SK-HYNIX`"
            )
        if candidate not in normalized:
            normalized.append(candidate)
    if not normalized:
        raise ValueError("at least one --ticker value is required for a thesis card")
    return normalized


def _normalize_thesis_list(values: list[str], *, field_name: str) -> list[str]:
    items = _split_thesis_values(values)
    if len(items) > MAX_THESIS_LIST_ITEMS:
        raise ValueError(f"{field_name} supports a maximum of {MAX_THESIS_LIST_ITEMS} items")
    return items


def _split_thesis_values(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for part in value.replace("|", ";").split(";"):
            normalized = part.strip()
            if normalized:
                items.append(normalized)
    return items


FINNHUB_SYMBOL_TABLE: dict[str, dict[str, Any]] = {
    "ACFN": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "ACFN", "company_name": "Acorn Energy Inc"},
    "AIM": {"exchange": "ASX", "country": "AU", "sec_registered": False, "finnhub_symbol": "AIM.AX", "company_name": "Ai-Media Technologies Ltd"},
    "AVGO": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "AVGO", "company_name": "Broadcom Inc"},
    "BEPC": {"exchange": "NYSE", "country": "US", "sec_registered": True, "finnhub_symbol": "BEPC", "company_name": "Brookfield Renewable Corp"},
    "COIN": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "COIN", "company_name": "Coinbase Global Inc"},
    "DUOL": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "DUOL", "company_name": "Duolingo Inc"},
    "GOOGL": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "GOOGL", "company_name": "Alphabet Inc"},
    "HEM": {"exchange": "Nasdaq Stockholm", "country": "SE", "sec_registered": False, "finnhub_symbol": "HEM.ST", "company_name": "Hemnet Group AB (publ)"},
    "HOOD": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "HOOD", "company_name": "Robinhood Markets Inc"},
    "IMVT": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "IMVT", "company_name": "Immunovant Inc"},
    "KPG": {"exchange": "ASX", "country": "AU", "sec_registered": False, "finnhub_symbol": "KPG.AX", "company_name": "Kelly Partners Group Holdings Ltd"},
    "LGCY": {"exchange": "NYSE MKT", "country": "US", "sec_registered": True, "finnhub_symbol": "LGCY", "company_name": "Legacy Housing Corp"},
    "OSCR": {"exchange": "NYSE", "country": "US", "sec_registered": True, "finnhub_symbol": "OSCR", "company_name": "Oscar Health Inc"},
    "SPOT": {"exchange": "NYSE", "country": "LU", "sec_registered": True, "finnhub_symbol": "SPOT", "company_name": "Spotify Technology SA"},
    "TOI": {"exchange": "TSXV", "country": "CA", "sec_registered": False, "finnhub_symbol": "TOI.V", "company_name": "Topicus.com Inc"},
    "TSLA": {"exchange": "NASDAQ", "country": "US", "sec_registered": True, "finnhub_symbol": "TSLA", "company_name": "Tesla Inc"},
    "TSM": {"exchange": "TWSE / NYSE ADR", "country": "TW", "sec_registered": True, "finnhub_symbol": "TSM", "company_name": "Taiwan Semiconductor Manufacturing Co Ltd"},
    "VCSH": {"exchange": "NYSE Arca", "country": "US", "sec_registered": True, "finnhub_symbol": "VCSH", "company_name": "Vanguard Short-Term Corporate Bond ETF"},
    "ZDC": {"exchange": "TSXV", "country": "CA", "sec_registered": False, "finnhub_symbol": "ZDC.V", "company_name": "Zedcor Inc"},
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

            if (
                record.get("exchange")
                and record.get("finnhub_symbol")
                and "sec_registered" in record
                and record.get("company_name")
            ):
                skipped.append(ticker)
                continue

            if ticker in NON_SECURITY_TICKERS:
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

    # Try base ticker without exchange suffix (e.g. KPG.AX -> KPG, TOI.V -> TOI)
    base_ticker = ticker.split(".")[0] if "." in ticker else None
    if base_ticker and base_ticker in FINNHUB_SYMBOL_TABLE:
        return dict(FINNHUB_SYMBOL_TABLE[base_ticker])

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
                "company_name": str(profile.get("name") or "").strip(),
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
                        "company_name": str(profile2.get("name") or "").strip(),
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


def render_thesis_markdown(cards: Sequence[Mapping[str, object]]) -> str:
    """Render thesis cards as markdown, including metric observation tables."""
    lines = ["# Thesis Cards", ""]
    if not cards:
        lines.append("No thesis cards configured.")
        return "\n".join(lines) + "\n"

    current_cards = [card for card in cards if "card_id" in card]
    if not current_cards:
        lines.append("No thesis cards configured.")
        return "\n".join(lines) + "\n"

    for card in sorted(current_cards, key=lambda item: item["card_id"]):
        tickers = ", ".join(f"`{ticker}`" for ticker in card.get("ticker_symbols", [])) or "None"
        core_thesis = [f"- {item}" for item in card.get("core_thesis", [])] or ["- None"]
        signals = [f"- {item}" for item in card.get("signals", [])] or ["- None"]
        game_plan = str(card.get("game_plan", "")).strip()
        lines.extend(
            [
                f"## {card['card_id']}",
                "",
                f"- Tickers: {tickers}",
                f"- Updated: {card.get('updated_at', '')}",
                "",
                str(card.get("summary", "")).strip() or "(no thesis summary)",
                "",
                "### Game Plan",
                game_plan or "(no game plan)",
                "",
                "### Core Thesis",
                *core_thesis,
                "",
                "### Signals",
                *signals,
                "",
                "### Metrics",
            ]
        )
        metrics = card.get("key_metrics", [])
        if not metrics:
            lines.extend(["No metrics configured.", ""])
            continue
        for metric in metrics:
            unit = str(metric.get("unit", "")).strip()
            heading = str(metric.get("name", "")).strip()
            if unit:
                heading = f"{heading} ({unit})"
            lines.extend(
                [
                    "",
                    f"#### {heading}",
                    "",
                    "| Period | Date | Value | Source |",
                    "| --- | --- | --- | --- |",
                ]
            )
            observations = metric.get("observations", [])
            if observations:
                for observation in observations:
                    lines.append(
                        "| "
                        + " | ".join(
                            _markdown_table_cell(observation.get(key, ""))
                            for key in ("period", "date", "value", "source")
                        )
                        + " |"
                    )
            else:
                lines.append("|  |  |  |  |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").strip()


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


def _main_portfolio_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return Main rows, defaulting only a wholly absent portfolio column."""
    has_portfolio_column = any("portfolio" in row for row in rows)
    if not has_portfolio_column:
        return rows
    return [
        row
        for row in rows
        if str(row.get("portfolio") or "").strip().casefold() == MAIN_PORTFOLIO.casefold()
    ]


def _row_is_blank(row: Mapping[str, Any]) -> bool:
    return all(value is None or str(value).strip() == "" for value in row.values())


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip() != "":
            return row[key]
    return None


def normalize_holdings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize only Main holdings into canonical portfolio records.

    A legacy source with no ``portfolio`` column is treated as Main. Once the
    column exists, only explicitly Main-labeled rows are eligible; blanks and
    every other label are excluded.
    """
    normalized: list[dict[str, Any]] = []
    for row_number, row in enumerate(_main_portfolio_rows(rows), start=2):
        record = _normalize_security_row(row, source_kind="holding")
        if not record["security_id"] or record["security_id"] in NON_SECURITY_TICKERS:
            continue
        raw_shares = _first_present(row, "shares", "quantity")
        raw_weight = _first_present(row, "weight", "portfolio_weight")
        if raw_shares is not None and record["shares"] is None:
            raise ValueError(
                f"holding row {row_number} ({record['security_id']}): shares must be numeric"
            )
        if raw_weight is not None and record["weight"] is None:
            raise ValueError(
                f"holding row {row_number} ({record['security_id']}): weight must be numeric"
            )
        shares = record.get("shares")
        if isinstance(shares, (int, float)) and shares <= 0:
            continue
        record["portfolio"] = MAIN_PORTFOLIO
        normalized.append(record)
    return normalized


def normalize_watchlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Main-only watchlist rows into canonical portfolio records."""
    normalized: list[dict[str, Any]] = []
    for row in _main_portfolio_rows(rows):
        record = _normalize_security_row(row, source_kind="watchlist")
        if record["security_id"]:
            normalized.append(record)
    return normalized


def normalize_transactions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Main transactions, validating the modern USD ledger shape."""
    normalized: list[dict[str, Any]] = []
    for input_index, row in enumerate(_main_portfolio_rows(rows)):
        modern_usd = "price_usd" in row or "total_usd" in row
        if modern_usd and "portfolio" not in row:
            raise ValueError(f"transaction row {input_index + 2}: portfolio is required")
        canonical_modern = modern_usd and all(
            key in row for key in ("security_id", "trade_date", "action", "quantity", "price")
        )
        ticker_source = _first_present(row, "ticker", "symbol")
        if ticker_source is None and not ("ticker" in row and "security_id" in row):
            ticker_source = _first_present(row, "security_id", "security")
        ticker = _clean_ticker(ticker_source)
        company_name = _clean_name(_first_present(row, "company_name", "company", "name", "security"))
        security_id = canonical_security_id(_first_present(row, "security_id") or ticker or company_name)
        if (
            modern_usd
            and not canonical_modern
            and not _row_is_blank(row)
            and _first_present(row, "symbol", "ticker") is None
        ):
            raise ValueError(f"transaction row {input_index + 2}: symbol is required")
        if not security_id or security_id in NON_SECURITY_TICKERS:
            if modern_usd and not _row_is_blank(row) and security_id not in NON_SECURITY_TICKERS:
                raise ValueError(f"transaction row {input_index + 2}: symbol is required")
            continue

        trade_date = _stringify_date(_first_present(row, "date", "trade_date", "timestamp"))
        action_keys = (
            ("action", "side", "transaction", "type")
            if modern_usd
            else ("action", "side", "transaction")
        )
        action = str(_first_present(row, *action_keys) or "").strip().lower()

        if modern_usd:
            if not trade_date:
                raise ValueError(f"transaction row {input_index + 2} ({security_id}): date is required")
            try:
                date.fromisoformat(trade_date)
            except ValueError as exc:
                raise ValueError(
                    f"transaction row {input_index + 2} ({security_id}): invalid date"
                ) from exc
            if action not in {"buy", "sell"}:
                raise ValueError(
                    f"transaction row {input_index + 2} ({security_id}): action must be buy or sell"
                )
            quantity = _required_positive_number(
                _first_present(row, "quantity", "shares"),
                row_number=input_index + 2,
                security_id=security_id,
                field="shares",
            )
            price = _required_positive_number(
                _first_present(row, "price") if canonical_modern else _first_present(row, "price_usd"),
                row_number=input_index + 2,
                security_id=security_id,
                field="price",
            )
            total_usd = _required_positive_number(
                _first_present(row, "total_usd"),
                row_number=input_index + 2,
                security_id=security_id,
                field="total",
            )
            currency = str(row.get("currency") or "").strip().upper()
            if currency and currency != "USD":
                raise ValueError(
                    f"transaction row {input_index + 2} ({security_id}): "
                    "reported USD total conflicts with currency"
                )
        else:
            quantity = _maybe_number(_first_present(row, "quantity", "shares"))
            price = _maybe_number(_first_present(row, "price"))

        record: dict[str, Any] = {
            "security_id": security_id,
            "ticker": ticker,
            "company_name": company_name,
            "trade_date": trade_date,
            "action": action,
            "quantity": quantity,
            "price": price,
            "portfolio": MAIN_PORTFOLIO,
            "notes": str(row.get("notes") or row.get("memo") or "").strip(),
        }
        if modern_usd:
            record["total_usd"] = total_usd
        normalized.append(record)

    normalized.sort(key=lambda item: item["trade_date"], reverse=True)
    return normalized


def _normalize_csv_key(raw: str) -> str:
    """Normalize a single CSV header to a canonical snake_case key."""
    lowered = raw.strip().lower()
    if lowered in _CSV_HEADER_MAP:
        return _CSV_HEADER_MAP[lowered]
    # Generic fallback: replace spaces and special chars with underscores.
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def _normalize_csv_headers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-key a list of CSV row dicts using canonical snake_case headers."""
    return [{_normalize_csv_key(k): v for k, v in row.items()} for row in rows]


def _is_google_sheets_url(source: str) -> bool:
    parsed = urlparse(source)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "docs.google.com"
        and re.match(r"^/spreadsheets/d/[^/]+/", parsed.path) is not None
    )


def _google_sheets_gviz_url(source: str) -> str:
    """Build an unformatted GViz URL from an explicit numeric query gid."""
    parsed = urlparse(source)
    if not _is_google_sheets_url(source):
        raise ValueError("not a recognized Google Sheets URL")
    match = re.match(r"^(/spreadsheets/d/[^/]+)(?:/.*)?$", parsed.path)
    if not match:
        raise ValueError("invalid Google Sheets URL")

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    gids = [value.strip() for key, value in query_pairs if key == "gid"]
    has_named_selection = any(key == "sheet" for key, _ in query_pairs)
    if len(gids) != 1 or not gids[0].isdigit() or has_named_selection:
        raise ValueError("Google Sheets source requires one explicit numeric query gid")

    allowed = {"gid", "range", "tq", "headers"}
    preserved = [(key, value) for key, value in query_pairs if key in allowed]
    preserved.append(("tqx", "out:json"))
    return urlunparse(
        (
            "https",
            parsed.netloc,
            f"{match.group(1)}/gviz/tq",
            "",
            urlencode(preserved),
            "",
        )
    )


def _rows_from_gviz_response(raw_text: str) -> list[dict[str, Any]]:
    """Parse a bounded Google Visualization JSON/JSONP table without eval."""
    if len(raw_text.encode("utf-8")) > _GVIZ_RESPONSE_LIMIT:
        raise ValueError("Google Visualization response exceeds the size limit")
    stripped = raw_text.strip()
    wrapper = re.fullmatch(
        r"(?:/\*O_o\*/\s*)?google\.visualization\.Query\.setResponse\((\{.*\})\);?",
        stripped,
        flags=re.DOTALL,
    )
    json_text = wrapper.group(1) if wrapper else stripped
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid Google Visualization response wrapper") from exc
    if not isinstance(payload, dict):
        raise ValueError("Google Visualization response must be an object")
    if payload.get("status") != "ok":
        errors = payload.get("errors")
        detail = ""
        if isinstance(errors, list):
            messages = [
                str(item.get("detailed_message") or item.get("message") or item.get("reason") or "").strip()
                for item in errors
                if isinstance(item, dict)
            ]
            detail = ": " + "; ".join(message for message in messages if message) if any(messages) else ""
        raise ValueError(f"Google Visualization query failed{detail}")

    table = payload.get("table")
    if not isinstance(table, dict):
        raise ValueError("Google Visualization response has no table")
    cols = table.get("cols")
    source_rows = table.get("rows")
    if not isinstance(cols, list) or not isinstance(source_rows, list):
        raise ValueError("Google Visualization table must contain cols and rows arrays")

    headers: list[str] = []
    for index, col in enumerate(cols):
        if not isinstance(col, dict):
            raise ValueError("Google Visualization column is malformed")
        label = str(col.get("label") or col.get("id") or f"column_{index + 1}")
        header = _normalize_csv_key(label)
        if not header or header in headers:
            raise ValueError("Google Visualization table has blank or duplicate headers")
        headers.append(header)

    rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        if not isinstance(source_row, dict) or not isinstance(source_row.get("c"), list):
            raise ValueError("Google Visualization row is malformed")
        cells = source_row["c"]
        if len(cells) > len(headers):
            raise ValueError("Google Visualization row has more cells than columns")
        row: dict[str, Any] = {}
        for index, header in enumerate(headers):
            cell = cells[index] if index < len(cells) else None
            if cell is None:
                value = None
            elif not isinstance(cell, dict):
                raise ValueError("Google Visualization cell is malformed")
            else:
                # Use the underlying value (v), never the rounded display (f).
                value = _decode_gviz_value(cell.get("v"))
            if header in _GVIZ_PERCENTAGE_POINT_FIELDS and isinstance(value, (int, float)):
                value = _decimal_to_number(Decimal(str(value)) * Decimal(100))
            row[header] = value
        rows.append(row)
    return rows


def _decode_gviz_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = _GVIZ_DATE_PATTERN.fullmatch(value)
    if not match:
        return value
    year, zero_based_month, day = (int(part) for part in match.groups())
    try:
        return date(year, zero_based_month + 1, day).isoformat()
    except ValueError as exc:
        raise ValueError("Google Visualization table contains an invalid Date value") from exc


def load_tabular_rows(source: str | None) -> list[dict[str, Any]]:
    """Load list-like data from JSON, YAML, CSV, or a Google Sheets URL."""
    if not source:
        return []
    if _is_google_sheets_url(source):
        gviz_url = _google_sheets_gviz_url(source)
        raw_text, _ = read_text_source(gviz_url, accept="application/json")
        return _rows_from_gviz_response(raw_text)
    payload, suffix = load_payload(source)
    if isinstance(payload, list):
        rows = [dict(item) for item in payload if isinstance(item, dict)]
        return _normalize_csv_headers(rows) if suffix == ".csv" else rows
    if isinstance(payload, dict):
        for key in ("rows", "items", "holdings", "transactions", "watchlist", "events"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    if suffix == ".csv" and isinstance(payload, str):
        rows = list(csv.DictReader(StringIO(payload)))
        return _normalize_csv_headers(rows)
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


_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_shared_session: requests.Session | None = None


def _http_session() -> requests.Session:
    """Return a shared requests session with browser-like headers."""
    global _shared_session  # noqa: PLW0603
    if _shared_session is None:
        _shared_session = requests.Session()
        _shared_session.headers.update(_BROWSER_HEADERS)
    return _shared_session


def read_text_source(source: str, *, accept: str | None = None) -> tuple[str, str]:
    """Read text from a local path or HTTP URL."""
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        headers: dict[str, str] = {}
        if accept:
            headers["Accept"] = accept
        response = _http_session().get(source, timeout=30, headers=headers if headers else None)
        # Retry once on 429 (rate limit)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "2"))
            import time as _time_mod
            _time_mod.sleep(min(retry_after, 10))
            response = _http_session().get(source, timeout=30, headers=headers if headers else None)
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


def _render_history_markdown(
    sync_entries: list[dict[str, Any]],
    metadata_entries: list[dict[str, Any]],
) -> str:
    lines = ["# Portfolio History", "", "## Recent Syncs"]
    sync_entries = sync_entries[-10:]
    metadata_entries = metadata_entries[-10:]
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
    return "\n".join(lines).rstrip() + "\n"


def update_history_render(paths: PortfolioPaths) -> None:
    """Render a compact markdown history summary."""
    body = _render_history_markdown(
        read_jsonl(paths.sync_log),
        read_jsonl(paths.metadata_history),
    )
    paths.rendered_history.write_text(body, encoding="utf-8")


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


def _carry_forward_enrichment(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
) -> None:
    """Merge enrichment fields from *previous* holdings into *current* in-place.

    For ``exchange``, the new (sheet) value wins when present; for all other
    enrichment fields the previous value is restored when the new record lacks it.
    """
    prev_by_id: dict[str, dict[str, Any]] = {
        str(r.get("security_id", "")): r for r in previous if r.get("security_id")
    }
    for record in current:
        sid = str(record.get("security_id", ""))
        prev = prev_by_id.get(sid)
        if not prev:
            continue
        for field in EnrichmentField:
            prev_val = prev.get(field)
            new_val = record.get(field)
            if field is EnrichmentField.EXCHANGE:
                # Prefer the new (sheet) value if present, else keep previous.
                if not (new_val and str(new_val).strip()):
                    if prev_val is not None:
                        record[field.value] = prev_val
            else:
                if new_val is None and prev_val is not None:
                    record[field.value] = prev_val


def _normalize_security_row(row: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
    ticker = _clean_ticker(row.get("ticker") or row.get("symbol"))
    company_name = _clean_name(row.get("company") or row.get("name") or row.get("company_name") or row.get("security"))
    security_id = canonical_security_id(row.get("security_id") or ticker or company_name or row.get("cusip"))
    record: dict[str, Any] = {
        "security_id": security_id,
        "ticker": ticker,
        "company_name": company_name,
        "cusip": str(row.get("cusip") or "").strip(),
        "weight": _maybe_number(_first_present(row, "weight", "portfolio_weight")),
        "shares": _maybe_number(_first_present(row, "shares", "quantity")),
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
    """Parse finite plain, currency, accounting, and percentage numbers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if not raw or raw.lower() in {"null", "none", "nan", "inf", "infinity", "-inf", "-infinity"}:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1].strip()
    raw = re.sub(r"^(?:USD\s*|US\$\s*|\$\s*)", "", raw, flags=re.IGNORECASE)
    raw = raw.replace(",", "").replace("%", "").strip()
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    if negative:
        parsed = -parsed
    return _decimal_to_number(parsed)


def _decimal_to_number(value: Decimal) -> float | int:
    if value == value.to_integral_value():
        return int(value)
    # Public state has historically exposed JSON numbers. Decimal is used while
    # parsing/manipulating values, then intentionally converted at this boundary.
    return float(value)


def _required_positive_number(
    value: Any,
    *,
    row_number: int,
    security_id: str,
    field: str,
) -> float | int:
    parsed = _maybe_number(value)
    if parsed is None:
        raise ValueError(f"transaction row {row_number} ({security_id}): {field} must be numeric")
    if parsed <= 0:
        raise ValueError(f"transaction row {row_number} ({security_id}): {field} must be greater than zero")
    return parsed


def _stringify_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        pass
    for date_format in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, date_format).date().isoformat()
        except ValueError:
            continue
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
