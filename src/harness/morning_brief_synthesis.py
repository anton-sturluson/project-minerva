"""Post-ingest, two-pass OpenClaw synthesis for the daily morning brief.

The collection pipeline owns all network/tool work and SQLite ingestion. This
module starts at the resulting SQLite database and prepared evidence file,
then deterministically separates article choices from automatic events. It
runs two OpenClaw main-agent turns in one dedicated session: pass 1 chooses
only among collected articles and secondary ``market-news`` records; pass 2
receives evidence for those choices plus every automatically routed prepared
event.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from harness.news_store import (
    canonical_news_url,
    is_finnhub_summary_only_section,
)

DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING = "high"
MAX_ARTICLE_CONTENT_CHARS = 4_000
MAX_EVENT_DETAIL_CHARS = 2_000
MAX_SHORTLIST_IDS = 30
ROUTING_SELECTED_ARTICLE = "selected_article"
ROUTING_AUTO_PORTFOLIO = "auto_portfolio_watchlist"
ROUTING_AUTO_MARKET = "auto_market_move"
ROUTING_OTHER_AUTO = "other_auto_event"
PORTFOLIO_ROLES = frozenset({"holding", "watchlist"})
ARTICLE_EVENT_TYPES = frozenset({"market-news", "company-news"})
CORE_SOURCE_LABELS = (
    "Reuters",
    "Economist",
    "WSJ",
    "Company IR",
    "BLS/BEA/Fed",
)
PREFERRED_NEWS_SOURCE_LABELS = ("Reuters", "Yahoo", "CNBC", "Bloomberg")
SOURCE_COLLECTION_LINE_RE = re.compile(
    r"(?im)^\s*(?:(?:[•●▪◦-]|\*)\s+)?\*{0,2}Source\s+Collection\s*:\*{0,2}"
)
REPO_ROOT = Path(__file__).resolve().parents[2]

ModelCall = Callable[..., str]


class SynthesisError(RuntimeError):
    """Raised when deterministic synthesis prerequisites or outputs are invalid."""


@dataclass(frozen=True, slots=True)
class CandidateTitle:
    """One stable collected-article or prepared-event candidate."""

    id: str
    kind: str
    title: str
    source: str
    published: str
    article_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def title_record(self) -> dict[str, Any]:
        """Return the compact, summary-free article-choice record for pass 1."""
        summary_only = bool(self.metadata.get("summary_only"))
        if self.kind == "article":
            candidate_class = (
                "secondary_finnhub_summary_only"
                if summary_only
                else "collected_sqlite_article"
            )
        else:
            event_type = str(self.metadata.get("event_type") or "").casefold()
            candidate_class = (
                "secondary_prepared_company_news"
                if event_type == "company-news"
                else "secondary_prepared_market_news"
            )
        record: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "published": self.published,
            "title": self.title,
            "article_candidate_class": candidate_class,
        }
        if summary_only:
            record["evidence_depth"] = "summary_only"
        if self.article_key is not None:
            record["article_key"] = self.article_key
        for key in (
            "event_type",
            "security_id",
            "relationship",
            "portfolio_role",
            "group",
            "release_time",
        ):
            value = self.metadata.get(key)
            if value not in (None, ""):
                record[key] = value
        return record


@dataclass(frozen=True, slots=True)
class RoutedEvent:
    """A prepared event that bypasses pass 1 with an editorial routing class."""

    candidate: CandidateTitle
    routing_class: str


@dataclass(frozen=True, slots=True)
class RoutingPlan:
    """Deterministic pass-1 candidates and pass-2 automatic events."""

    article_candidates: tuple[CandidateTitle, ...]
    automatic_events: tuple[RoutedEvent, ...]


def query_fresh_article_titles(db_path: Path, run_date: date) -> list[CandidateTitle]:
    """Read every article first collected on ``run_date`` without reading its body.

    ``collected_at`` is canonical ISO text written by ``harness.news``. Its
    leading calendar date is the collection run's date even when the timestamp
    includes an offset, so a prefix comparison avoids silently shifting a local
    collection into another UTC date.
    """
    if not db_path.is_file():
        raise SynthesisError(f"news database does not exist: {db_path}")

    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise SynthesisError(f"could not open news database read-only: {exc}") from exc

    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT article_key, source, published_at, published_at_raw, title, url,
                   section
            FROM news
            WHERE substr(collected_at, 1, 10) = ?
            ORDER BY source COLLATE NOCASE,
                     published_at,
                     title COLLATE NOCASE,
                     article_key
            """,
            (run_date.isoformat(),),
        ).fetchall()
    except sqlite3.Error as exc:
        raise SynthesisError(f"could not query fresh news titles: {exc}") from exc
    finally:
        connection.close()

    candidates: list[CandidateTitle] = []
    for row in rows:
        article_key = str(row["article_key"])
        published_iso = _epoch_as_iso(row["published_at"])
        published_raw = str(row["published_at_raw"] or "").strip()
        candidates.append(
            CandidateTitle(
                id=f"article:{article_key}",
                kind="article",
                article_key=article_key,
                source=str(row["source"]),
                published=_publication_display(published_raw, published_iso),
                title=str(row["title"]),
                metadata={
                    "published_at": published_iso,
                    "published_at_raw": published_raw,
                    "url": str(row["url"] or "").strip(),
                    "section": str(row["section"] or "").strip(),
                    "summary_only": is_finnhub_summary_only_section(row["section"]),
                },
            )
        )
    return candidates


def load_prepared_event_titles(
    prepared_path: Path, run_date: date
) -> list[CandidateTitle]:
    """Load compact prepared-evidence headlines and assign deterministic IDs."""
    if not prepared_path.is_file():
        raise SynthesisError(f"prepared evidence does not exist: {prepared_path}")
    try:
        payload = json.loads(prepared_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SynthesisError(f"could not read prepared evidence: {exc}") from exc
    if not isinstance(payload, dict):
        raise SynthesisError("prepared evidence must be a JSON object")

    universe_roles = _universe_role_map(payload.get("universe"))
    events = payload.get("events", [])
    if not isinstance(events, list):
        raise SynthesisError("prepared evidence `events` must be a list")

    candidates: list[CandidateTitle] = []
    seen_ids: set[str] = set()
    for raw_event in events:
        if not isinstance(raw_event, dict):
            continue
        title = str(raw_event.get("headline") or raw_event.get("title") or "").strip()
        event_date = str(raw_event.get("event_date") or run_date.isoformat()).strip()
        if not title or event_date not in {"", run_date.isoformat()}:
            continue
        source = str(
            raw_event.get("source_name")
            or raw_event.get("source")
            or "prepared-evidence"
        ).strip()
        security_id = str(
            raw_event.get("security_id") or raw_event.get("ticker") or ""
        ).strip()
        event_type = str(raw_event.get("event_type") or "").strip().casefold()
        stable_identity: list[str] = [source, security_id, title, event_date]
        if event_type in ARTICLE_EVENT_TYPES:
            stable_identity.extend(
                (
                    event_type,
                    str(raw_event.get("persisted_article_key") or "").strip(),
                    canonical_news_url(
                        raw_event.get("reference_url")
                        or raw_event.get("source_url")
                        or _nested_value(raw_event, "metadata", "url")
                    ),
                    _prepared_news_source_label(raw_event),
                )
            )
        stable_key = "|".join(stable_identity)
        candidate_id = f"event:{hashlib.sha256(stable_key.encode('utf-8')).hexdigest()}"
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        metadata = dict(raw_event)
        role = universe_roles.get(security_id.upper())
        if role:
            metadata["portfolio_role"] = role
        candidates.append(
            CandidateTitle(
                id=candidate_id,
                kind="event",
                source=source,
                published=event_date or run_date.isoformat(),
                title=title,
                metadata=metadata,
            )
        )

    return sorted(
        candidates,
        key=lambda item: (
            item.source.casefold(),
            item.published,
            item.title.casefold(),
            item.id,
        ),
    )


def build_title_universe(
    db_path: Path, prepared_path: Path, run_date: date
) -> list[CandidateTitle]:
    """Build one candidate per article plus unmatched prepared events.

    A Finnhub article is represented in both SQLite and prepared evidence. The
    SQLite candidate is the durable record (and may itself be summary-only),
    while the prepared event contributes ticker/portfolio routing metadata.
    """
    articles = query_fresh_article_titles(db_path, run_date)
    prepared_events = load_prepared_event_titles(prepared_path, run_date)
    article_by_record = {
        _article_record_key(article, _collected_source_label(article.source)): article
        for article in articles
    }
    article_by_key = {
        article.article_key: article
        for article in articles
        if article.article_key is not None
    }
    merged_by_id = {article.id: article for article in articles}
    unmatched_events: list[CandidateTitle] = []

    for event in prepared_events:
        event_type = str(event.metadata.get("event_type") or "").strip().casefold()
        if event_type not in ARTICLE_EVENT_TYPES:
            unmatched_events.append(event)
            continue
        source_label = _prepared_news_source_label(event.metadata)
        persisted_key = str(
            event.metadata.get("persisted_article_key") or ""
        ).strip()
        matching_article = article_by_key.get(persisted_key)
        if matching_article is None:
            matching_article = article_by_record.get(
                _article_record_key(event, source_label)
            )
        if matching_article is None:
            unmatched_events.append(event)
            continue
        current = merged_by_id[matching_article.id]
        merged_by_id[matching_article.id] = _merge_article_with_prepared_event(
            current, event
        )

    merged_articles = [merged_by_id[article.id] for article in articles]
    return [*merged_articles, *unmatched_events]


def _merge_article_with_prepared_event(
    article: CandidateTitle, event: CandidateTitle
) -> CandidateTitle:
    durable_metadata = {
        key: article.metadata.get(key)
        for key in (
            "url",
            "published_at",
            "published_at_raw",
            "section",
            "summary_only",
        )
    }
    metadata = dict(article.metadata)
    contexts = [
        dict(context)
        for context in metadata.get("prepared_event_contexts", [])
        if isinstance(context, dict)
    ]
    existing_rank = int(metadata.get("_prepared_routing_rank") or 0)
    event_rank = _prepared_event_routing_rank(event)
    if event_rank > existing_rank:
        metadata.update(event.metadata)
    else:
        for key, value in event.metadata.items():
            if value not in (None, "", [], {}):
                metadata.setdefault(key, value)
    metadata.update(durable_metadata)
    context = _prepared_event_context(event)
    context_identity = json.dumps(context, ensure_ascii=False, sort_keys=True)
    existing_context_identities = {
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in contexts
    }
    if context_identity not in existing_context_identities:
        contexts.append(context)
    metadata["prepared_event_contexts"] = contexts
    metadata["_prepared_routing_rank"] = max(existing_rank, event_rank)
    prepared_event_ids = [
        str(item)
        for item in metadata.get("persisted_prepared_event_ids", [])
        if str(item)
    ]
    if event.id not in prepared_event_ids:
        prepared_event_ids.append(event.id)
    metadata["persisted_prepared_event_ids"] = prepared_event_ids
    return CandidateTitle(
        id=article.id,
        kind="article",
        title=article.title,
        source=article.source,
        published=article.published,
        article_key=article.article_key,
        metadata=metadata,
    )


def _prepared_event_routing_rank(candidate: CandidateTitle) -> int:
    role = str(candidate.metadata.get("portfolio_role") or "").strip().casefold()
    if role in PORTFOLIO_ROLES:
        return 3
    event_type = str(candidate.metadata.get("event_type") or "").strip().casefold()
    return 2 if event_type == "company-news" else 1


def _prepared_event_context(candidate: CandidateTitle) -> dict[str, Any]:
    event = candidate.metadata
    context = _compact_event_details(event)
    context["prepared_event_id"] = candidate.id
    context["title"] = candidate.title
    source = _prepared_news_source_label(event)
    if source != "Unknown":
        context["news_source"] = source
    url = str(event.get("reference_url") or event.get("source_url") or "").strip()
    if url:
        context["url"] = url
    return context


def partition_candidates(candidates: Sequence[CandidateTitle]) -> RoutingPlan:
    """Partition candidates before pass 1 using the approved routing hierarchy.

    SQLite articles normally compete in pass 1. An article enriched from its
    matching prepared event retains holding/watchlist routing and bypasses pass
    1; otherwise market moves bypass, unlinked ``market-news`` records compete
    as secondary article candidates, and every remaining prepared event advances
    as an ``other_auto_event``.
    """
    article_candidates: list[CandidateTitle] = []
    automatic_events: list[RoutedEvent] = []
    for candidate in candidates:
        event_type = str(candidate.metadata.get("event_type") or "").strip().casefold()
        portfolio_role = (
            str(candidate.metadata.get("portfolio_role") or "").strip().casefold()
        )
        if portfolio_role in PORTFOLIO_ROLES:
            routing_class = ROUTING_AUTO_PORTFOLIO
        elif candidate.kind == "article":
            article_candidates.append(candidate)
            continue
        elif event_type == "market":
            routing_class = ROUTING_AUTO_MARKET
        elif event_type == "market-news":
            article_candidates.append(candidate)
            continue
        else:
            routing_class = ROUTING_OTHER_AUTO
        automatic_events.append(RoutedEvent(candidate, routing_class))

    return RoutingPlan(tuple(article_candidates), tuple(automatic_events))


def build_source_collection_line(candidates: Sequence[CandidateTitle]) -> str:
    """Count the run's article records and market observations deterministically.

    Fresh SQLite rows and prepared ``market-news``/``company-news`` events are
    article records. Prepared ``market`` events are observations instead. Exact
    repeated records are counted once, with richer SQLite records taking
    precedence over prepared news records.
    """
    counts = {label: 0 for label in CORE_SOURCE_LABELS}
    prepared_labels: set[str] = set()
    collected_labels: set[str] = set()
    seen_candidate_ids: set[str] = set()
    seen_article_records: set[tuple[str, ...]] = set()
    seen_market_observations: set[tuple[str, str, str]] = set()
    article_record_count = 0
    market_price_observations = 0

    # SQLite rows contain richer evidence and win when the same article also
    # appears as a prepared Finnhub-style news event.
    ordered_candidates = sorted(candidates, key=lambda item: item.kind != "article")
    for candidate in ordered_candidates:
        event_type = str(candidate.metadata.get("event_type") or "").strip().casefold()
        if candidate.kind == "event" and event_type == "market":
            observation_key = (
                str(
                    candidate.metadata.get("security_id")
                    or candidate.metadata.get("ticker")
                    or ""
                )
                .strip()
                .casefold(),
                candidate.published,
                _normalized_title(candidate.title),
            )
            if observation_key not in seen_market_observations:
                seen_market_observations.add(observation_key)
                market_price_observations += 1
            continue

        if candidate.kind == "article":
            source_label = _collected_source_label(candidate.source)
            source_kind = "collected"
        elif candidate.kind == "event" and event_type in ARTICLE_EVENT_TYPES:
            source_label = _prepared_news_source_label(candidate.metadata)
            source_kind = "prepared"
        else:
            continue

        record_key = _article_record_key(candidate, source_label)
        if candidate.id in seen_candidate_ids:
            continue
        # Every fresh SQLite row is an available article record. Prepared news
        # is the secondary representation and is suppressed when that article
        # was already counted from SQLite or an earlier prepared event.
        if candidate.kind == "event" and record_key in seen_article_records:
            continue

        seen_candidate_ids.add(candidate.id)
        seen_article_records.add(record_key)
        counts[source_label] = counts.get(source_label, 0) + 1
        article_record_count += 1
        if source_kind == "prepared":
            prepared_labels.add(source_label)
        else:
            collected_labels.add(source_label)

    source_labels = _ordered_source_labels(
        counts,
        prepared_labels=prepared_labels,
        collected_labels=collected_labels,
    )
    source_counts = " · ".join(
        f"{label} {counts[label]}" for label in source_labels
    )
    article_noun = "article record" if article_record_count == 1 else "article records"
    observation_noun = (
        "market-price observation"
        if market_price_observations == 1
        else "market-price observations"
    )
    return (
        f"*Source Collection:* {article_record_count} {article_noun} — {source_counts}; "
        f"plus {market_price_observations} {observation_noun}."
    )


def build_shortlist_prompt(candidates: Sequence[CandidateTitle], run_date: date) -> str:
    """Render pass 1 with only article-choice titles and no evidence bodies."""
    payload = {
        "run_date": run_date.isoformat(),
        "candidate_count": len(candidates),
        "candidates": [candidate.title_record() for candidate in candidates],
    }
    return (
        "You are Sol performing PASS 1 of a deterministic morning-brief workflow.\n"
        "For this turn, DO NOT use or call any tools. DO NOT browse, search, or fetch anything. "
        "DO NOT read, create, edit, or write any files. Work only from this message and reply "
        "directly. The JSON below is the complete ARTICLE-CHOICE title/headline universe for this "
        "run. Portfolio/watchlist events, market moves, and other non-article events have already "
        "been routed automatically and must not compete in this pass.\n\n"
        "Select a focused but broad shortlist for a long-only investor, targeting 15-25 choices "
        "when the candidate quality supports it. HARD MAXIMUM: select no more than 30 IDs. Retain "
        "stories that are plausibly market-moving, company-specific, useful as an investor "
        "read-through, or materially economic, political, or geopolitical. Reject lifestyle, "
        "sports, celebrity, and other non-investor fluff. Semantically deduplicate overlapping "
        "headlines: select one representative of the same development, preferring a "
        "collected_sqlite_article over secondary_finnhub_summary_only or "
        "secondary_prepared_market_news because only collected_sqlite_article represents richer "
        "crawler-collected reporting. Finnhub summary-only rows contain only a provider summary "
        "despite being stored in SQLite. A secondary record may be selected when it is the only "
        "coverage or is materially distinct. Rank and balance sources on merit, not quotas. "
        "Do not draft the brief, summarize unsupported details, or invent IDs.\n\n"
        "Return exactly one strict JSON object and no markdown or commentary. Include exactly one "
        "concise editorial reason with every selected ID:\n"
        '{"selections":[{"id":"exact-stable-id","reason":"concise reason"}]}\n\n'
        "TITLE_UNIVERSE_JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def parse_shortlist_output(raw: str) -> list[str]:
    """Parse common harmless wrappers around the required strict shortlist JSON."""
    text = raw.strip()
    if not text:
        raise SynthesisError("pass 1 returned an empty response")

    decoded_values: list[Any] = []
    unwrapped = _strip_outer_code_fence(text)
    for candidate_text in (unwrapped, text):
        try:
            decoded_values.append(json.loads(candidate_text))
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        decoded_values.append(value)

    for value in decoded_values:
        extracted = _extract_id_list(value)
        if extracted is None:
            continue
        unique: list[str] = []
        seen: set[str] = set()
        for item in extracted:
            identifier = ""
            if isinstance(item, str):
                identifier = item.strip()
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                identifier = item["id"].strip()
            if identifier and identifier not in seen:
                seen.add(identifier)
                unique.append(identifier)
        return unique

    raise SynthesisError(
        "pass 1 did not return a JSON shortlist with a `selections` or `ids` array"
    )


def validate_shortlist_ids(
    requested_ids: Sequence[str], candidates: Sequence[CandidateTitle]
) -> list[str]:
    """Return valid IDs in stable universe order and reject an oversized shortlist."""
    requested = set(requested_ids)
    valid = [candidate.id for candidate in candidates if candidate.id in requested]
    if candidates and not valid:
        raise SynthesisError(
            "pass 1 returned no valid IDs from the non-empty title universe"
        )
    if len(valid) > MAX_SHORTLIST_IDS:
        raise SynthesisError(
            f"pass 1 returned {len(valid)} valid IDs; hard maximum is "
            f"{MAX_SHORTLIST_IDS}"
        )
    return valid


def query_shortlisted_evidence(
    db_path: Path,
    candidates: Sequence[CandidateTitle],
    shortlist_ids: Sequence[str],
    *,
    max_content_chars: int = MAX_ARTICLE_CONTENT_CHARS,
) -> list[dict[str, Any]]:
    """Fetch evidence only for validated pass-1 article choices."""
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    selected = [candidate_by_id[item_id] for item_id in shortlist_ids]
    selected_article_keys = [
        candidate.article_key
        for candidate in selected
        if candidate.kind == "article" and candidate.article_key is not None
    ]
    article_rows = _query_article_evidence(db_path, selected_article_keys)

    evidence: list[dict[str, Any]] = []
    for candidate in selected:
        if candidate.kind == "article":
            row = article_rows.get(candidate.article_key or "")
            if row is None:
                raise SynthesisError(
                    f"shortlisted article disappeared from SQLite: {candidate.id}"
                )
            evidence.append(
                _article_evidence(
                    candidate,
                    row,
                    routing_class=ROUTING_SELECTED_ARTICLE,
                    max_content_chars=max_content_chars,
                )
            )
        else:
            evidence.append(
                _event_evidence(candidate, routing_class=ROUTING_SELECTED_ARTICLE)
            )
    return evidence


def query_automatic_evidence(
    db_path: Path,
    routed_events: Sequence[RoutedEvent],
    *,
    max_content_chars: int = MAX_ARTICLE_CONTENT_CHARS,
) -> list[dict[str, Any]]:
    """Load SQLite evidence for persisted automatic articles when available."""
    article_keys = [
        item.candidate.article_key
        for item in routed_events
        if item.candidate.kind == "article"
        and item.candidate.article_key is not None
    ]
    article_rows = _query_article_evidence(db_path, article_keys)
    evidence: list[dict[str, Any]] = []
    for item in routed_events:
        candidate = item.candidate
        if candidate.kind == "article":
            row = article_rows.get(candidate.article_key or "")
            if row is None:
                raise SynthesisError(
                    f"automatically routed article disappeared from SQLite: {candidate.id}"
                )
            evidence.append(
                _article_evidence(
                    candidate,
                    row,
                    routing_class=item.routing_class,
                    max_content_chars=max_content_chars,
                )
            )
        else:
            evidence.append(
                _event_evidence(candidate, routing_class=item.routing_class)
            )
    return evidence


def build_final_prompt(
    evidence: Sequence[dict[str, Any]],
    run_date: date,
    *,
    shortlisted_count: int | None = None,
    automatic_event_count: int | None = None,
) -> str:
    """Render pass 2 with selected-article and automatic-event evidence."""
    selected_count = (
        shortlisted_count
        if shortlisted_count is not None
        else sum(
            item.get("routing_class") == ROUTING_SELECTED_ARTICLE for item in evidence
        )
    )
    automatic_count = (
        automatic_event_count
        if automatic_event_count is not None
        else len(evidence) - selected_count
    )
    payload = {
        "run_date": run_date.isoformat(),
        "shortlisted_count": selected_count,
        "automatic_event_count": automatic_count,
        "evidence_count": len(evidence),
        "evidence": list(evidence),
    }
    return (
        "You are Sol performing PASS 2 of a deterministic morning-brief workflow.\n"
        "For this turn, DO NOT use or call any tools. DO NOT browse, search, or fetch anything. "
        "DO NOT read, create, edit, or write any files. Work only from this message and reply "
        "directly. Even though the prior pass is visible in this session, the JSON below is the "
        "complete closed evidence set. Use no outside facts, tools, files, or prior-pass titles that "
        "are absent from this evidence. Never fabricate a fact, link, date, portfolio relationship, "
        "or event.\n\n"
        "Every evidence record has an explicit routing_class. Apply this hierarchy exactly:\n"
        "- selected_article: editorially rank the strongest items as concise bullets in *Worth "
        "Knowing Today*. Semantically deduplicate overlapping stories and do not repeat one "
        "development from multiple outlets. Only collected_sqlite_article records represent richer "
        "crawler-collected reporting. secondary_finnhub_summary_only, "
        "secondary_prepared_market_news, and secondary_prepared_company_news records retain only "
        "a provider/prepared summary and URL; do not treat any as full-text reporting merely "
        "because one is stored in SQLite.\n"
        "- auto_portfolio_watchlist: represent EVERY record in *Portfolio / Watchlist Events*. "
        "When one persisted article has multiple prepared_event_contexts, represent every listed "
        "security association while consolidating the article into one coherent bullet. Consolidate "
        "overlapping records by ticker rather than producing one bullet per record. Do not drop a "
        "record merely because it seems less newsworthy. Emit "
        "this section if and only if auto_portfolio_watchlist evidence exists.\n"
        "- auto_market_move: represent ALL such records in exactly ONE compact bullet/line under "
        "*Market Snapshot*. Never emit multiple market-move bullets. Emit this section if and only "
        "if auto_market_move evidence exists.\n"
        "- other_auto_event: include EVERY record appropriately and concisely, consolidating true "
        "duplicates; use *Other Events* when a separate section is clearest.\n\n"
        "Return ONLY the final Slack-formatted daily-news brief body as plain text (Slack mrkdwn), "
        "with no JSON, code fence, preamble, postscript, or file instructions. Do not write a Source "
        "Collection line or any source counts; deterministic code will prepend that line after this "
        "turn. Use section order: *Market "
        "Snapshot* first when its routed evidence exists, then *Portfolio / Watchlist Events* when "
        "its routed evidence exists, then *Worth Knowing Today* (required), and finally *Other "
        "Events* when its routed evidence exists. Preserve supplied URLs when representing "
        "their evidence, using Slack links such as <https://example.com|Source>; never replace or "
        "invent a link. Use concise source labels such as Reuters, WSJ, Economist, or TICKER IR rather "
        "than internal IDs. Rank and balance selected articles on merit, not quotas. If selected-article "
        "evidence is thin, say so briefly rather than padding Worth Knowing Today, while still "
        "representing every automatic event as directed.\n\n"
        "SHORTLISTED_EVIDENCE_JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def normalize_final_brief(
    raw: str,
    *,
    has_market_move_evidence: bool | None = None,
    has_portfolio_watchlist_evidence: bool | None = None,
) -> str:
    """Normalize pass 2 and validate its evidence-aware Slack section order.

    Evidence-presence checks are optional for standalone callers; the synthesis
    workflow always supplies them from the deterministic automatic routes.
    """
    brief = _strip_outer_code_fence(raw.strip()).strip()
    if not brief:
        raise SynthesisError("pass 2 returned an empty brief")
    if "```" in brief:
        raise SynthesisError("pass 2 returned a code fence instead of plain Slack text")
    try:
        decoded = json.loads(brief)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, (dict, list)):
        raise SynthesisError("pass 2 returned JSON instead of a text-only Slack brief")
    if SOURCE_COLLECTION_LINE_RE.search(brief):
        raise SynthesisError(
            "pass 2 returned a Source Collection line that deterministic code owns"
        )

    section_positions = {
        "Market Snapshot": _section_heading_position(brief, "Market Snapshot"),
        "Portfolio / Watchlist Events": _section_heading_position(
            brief, "Portfolio / Watchlist Events"
        ),
        "Worth Knowing Today": _section_heading_position(brief, "Worth Knowing Today"),
    }
    if section_positions["Worth Knowing Today"] is None:
        raise SynthesisError("pass 2 omitted required Worth Knowing Today section")

    _validate_evidence_section_presence(
        section_positions,
        "Market Snapshot",
        has_evidence=has_market_move_evidence,
        routing_class=ROUTING_AUTO_MARKET,
    )
    _validate_evidence_section_presence(
        section_positions,
        "Portfolio / Watchlist Events",
        has_evidence=has_portfolio_watchlist_evidence,
        routing_class=ROUTING_AUTO_PORTFOLIO,
    )

    present_positions = [
        position for position in section_positions.values() if position is not None
    ]
    if present_positions != sorted(present_positions):
        raise SynthesisError(
            "pass 2 returned sections out of order; expected Market Snapshot, "
            "Portfolio / Watchlist Events, then Worth Knowing Today"
        )
    if not present_positions or present_positions[0] != 0:
        raise SynthesisError("pass 2 returned text before its first Slack section")
    return brief


def synthesize_morning_brief(
    *,
    db_path: Path,
    prepared_path: Path,
    run_date: date,
    model_call: ModelCall | None = None,
    model: str = DEFAULT_MODEL,
    reasoning: str = DEFAULT_REASONING,
    session_key: str | None = None,
    output_path: Path | None = None,
    retry_count: int = 1,
) -> str:
    """Run both OpenClaw turns in one session and persist the final artifact."""
    all_candidates = build_title_universe(db_path, prepared_path, run_date)
    source_collection_line = build_source_collection_line(all_candidates)
    routing_plan = partition_candidates(all_candidates)
    candidates = routing_plan.article_candidates
    call_model = model_call or _default_model_call
    active_session_key = _resolve_session_key(session_key, run_date)
    pass_1_prompt = build_shortlist_prompt(candidates, run_date)

    shortlist_ids = _with_retries(
        lambda: validate_shortlist_ids(
            parse_shortlist_output(
                call_model(
                    prompt=pass_1_prompt,
                    model=model,
                    reasoning=reasoning,
                    session_key=active_session_key,
                )
            ),
            candidates,
        ),
        attempts=retry_count + 1,
        stage="pass 1 shortlist",
    )
    selected_evidence = query_shortlisted_evidence(db_path, candidates, shortlist_ids)
    automatic_evidence = query_automatic_evidence(
        db_path, routing_plan.automatic_events
    )
    evidence = [*selected_evidence, *automatic_evidence]
    pass_2_prompt = build_final_prompt(
        evidence,
        run_date,
        shortlisted_count=len(selected_evidence),
        automatic_event_count=len(automatic_evidence),
    )
    has_market_move_evidence = any(
        item.get("routing_class") == ROUTING_AUTO_MARKET
        for item in automatic_evidence
    )
    has_portfolio_watchlist_evidence = any(
        item.get("routing_class") == ROUTING_AUTO_PORTFOLIO
        for item in automatic_evidence
    )
    synthesized_body = _with_retries(
        lambda: normalize_final_brief(
            call_model(
                prompt=pass_2_prompt,
                model=model,
                reasoning=reasoning,
                session_key=active_session_key,
            ),
            has_market_move_evidence=has_market_move_evidence,
            has_portfolio_watchlist_evidence=has_portfolio_watchlist_evidence,
        ),
        attempts=retry_count + 1,
        stage="pass 2 synthesis",
    )
    brief = f"{source_collection_line}\n{synthesized_body}"

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{brief}\n", encoding="utf-8")
    return brief


def _resolve_session_key(session_key: str | None, run_date: date) -> str:
    if session_key is None:
        return f"daily-news-sol-{run_date.isoformat()}-{uuid.uuid4().hex[:12]}"
    resolved = session_key.strip()
    if not resolved:
        raise SynthesisError("--session-key must not be empty")
    return resolved


def _default_model_call(
    *, prompt: str, model: str, reasoning: str, session_key: str
) -> str:
    command = [
        "openclaw",
        "agent",
        "--agent",
        "main",
        "--model",
        model,
        "--thinking",
        reasoning,
        "--json",
        "--session-key",
        session_key,
        "--message",
        prompt,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise SynthesisError(f"could not start OpenClaw agent command: {exc}") from exc

    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or completed.stdout.strip()
        if diagnostic:
            diagnostic = _bounded_text(diagnostic, 2_000)
            detail = f": {diagnostic}"
        else:
            detail = " (no diagnostic output)"
        raise SynthesisError(
            f"OpenClaw agent command exited with status {completed.returncode}{detail}"
        )
    return parse_openclaw_json_output(completed.stdout)


def parse_openclaw_json_output(raw: str) -> str:
    """Extract visible assistant text from top-level or Gateway-nested payloads."""
    if not raw.strip():
        raise SynthesisError("OpenClaw agent returned empty JSON stdout")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SynthesisError(
            f"OpenClaw agent returned invalid JSON stdout at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(response, dict):
        raise SynthesisError("OpenClaw agent JSON stdout must be an object")

    result = response.get("result")
    result_object = result if isinstance(result, dict) else None
    for container in (response, result_object):
        if container is None:
            continue
        status = container.get("status")
        if isinstance(status, str) and status.casefold() not in {
            "ok",
            "success",
            "completed",
        }:
            detail = _openclaw_error_detail(response, result_object)
            suffix = f": {detail}" if detail else ""
            raise SynthesisError(f"OpenClaw agent returned status {status!r}{suffix}")

    if "payloads" in response:
        payloads = response["payloads"]
    elif result_object is not None and "payloads" in result_object:
        payloads = result_object["payloads"]
    else:
        detail = _openclaw_error_detail(response, result_object)
        suffix = f": {detail}" if detail else ""
        raise SynthesisError(f"OpenClaw agent JSON contained no payloads{suffix}")
    if not isinstance(payloads, list):
        raise SynthesisError("OpenClaw agent `payloads` must be a list")

    texts: list[str] = []
    for index, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            raise SynthesisError(
                f"OpenClaw agent payload {index} must be a JSON object"
            )
        text = payload.get("text")
        if payload.get("isError") is True:
            detail = text.strip() if isinstance(text, str) else "unknown agent error"
            raise SynthesisError(f"OpenClaw agent returned an error payload: {detail}")
        if payload.get("isReasoning") is True:
            continue
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    if not texts:
        raise SynthesisError("OpenClaw agent returned no visible text payload")
    return "\n\n".join(texts)


def _openclaw_error_detail(
    response: dict[str, Any], result: dict[str, Any] | None
) -> str:
    for container in (result, response):
        if container is None:
            continue
        for key in ("errorMessage", "error", "summary", "message"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return _bounded_text(value.strip(), 2_000)
            if isinstance(value, dict) and value:
                return _bounded_text(
                    json.dumps(value, ensure_ascii=False, sort_keys=True), 2_000
                )
    return ""


def _query_article_evidence(
    db_path: Path, article_keys: Sequence[str]
) -> dict[str, sqlite3.Row]:
    if not article_keys:
        return {}
    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise SynthesisError(f"could not open news database read-only: {exc}") from exc
    connection.row_factory = sqlite3.Row
    rows: dict[str, sqlite3.Row] = {}
    try:
        for start in range(0, len(article_keys), 500):
            chunk = article_keys[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            query = (
                "SELECT article_key, published_at, published_at_raw, title, content, summary, "
                f"source, url, section FROM news WHERE article_key IN ({placeholders})"
            )
            for row in connection.execute(query, tuple(chunk)):
                rows[str(row["article_key"])] = row
    except sqlite3.Error as exc:
        raise SynthesisError(
            f"could not query shortlisted news evidence: {exc}"
        ) from exc
    finally:
        connection.close()
    return rows


def _article_evidence(
    candidate: CandidateTitle,
    row: sqlite3.Row,
    *,
    routing_class: str,
    max_content_chars: int,
) -> dict[str, Any]:
    """Build evidence from the durable SQLite row for one article candidate."""
    summary = str(row["summary"] or "").strip()
    content = str(row["content"] or "").strip()
    summary_only = is_finnhub_summary_only_section(row["section"])
    if summary_only:
        evidence_text = _bounded_text(summary or content, max_content_chars)
        evidence_kind = "summary_only"
    elif summary:
        evidence_text = summary
        evidence_kind = "summary"
    else:
        evidence_text = _bounded_text(content, max_content_chars)
        evidence_kind = "bounded_content_fallback"
    published_raw = str(row["published_at_raw"] or "").strip()
    published_iso = _epoch_as_iso(row["published_at"])
    record: dict[str, Any] = {
        "id": candidate.id,
        "kind": "article",
        "article_key": candidate.article_key,
        "source": str(row["source"]),
        "published": _publication_display(published_raw, published_iso),
        "published_at_raw": published_raw,
        "title": str(row["title"]),
        "url": str(row["url"] or "").strip(),
        "section": str(row["section"] or "").strip(),
        "evidence_kind": evidence_kind,
        "routing_class": routing_class,
        "article_candidate_class": (
            "secondary_finnhub_summary_only"
            if summary_only
            else "collected_sqlite_article"
        ),
        "evidence_depth": "summary_only" if summary_only else "collected_article",
        "evidence": evidence_text,
    }
    details = _compact_event_details(candidate.metadata)
    if details:
        record["details"] = details
    return record


def _event_evidence(candidate: CandidateTitle, *, routing_class: str) -> dict[str, Any]:
    """Preserve one prepared event's own bounded summary and supplied URL."""
    event = candidate.metadata
    url = str(event.get("reference_url") or event.get("source_url") or "").strip()
    summary = _first_nonempty_text(
        event.get("summary"),
        event.get("description"),
        _nested_value(event, "metadata", "summary"),
        _nested_value(event, "metadata", "description"),
    )
    event_type = str(event.get("event_type") or "").strip().casefold()
    evidence_record = {
        "id": candidate.id,
        "kind": "event",
        "source": candidate.source,
        "published": candidate.published,
        "title": candidate.title,
        "url": url,
        "details": _compact_event_details(event),
        "evidence_kind": "prepared_event",
        "routing_class": routing_class,
        "evidence": _bounded_text(summary, MAX_EVENT_DETAIL_CHARS),
    }
    if event_type in ARTICLE_EVENT_TYPES:
        evidence_record["article_candidate_class"] = (
            "secondary_prepared_company_news"
            if event_type == "company-news"
            else "secondary_prepared_market_news"
        )
        evidence_record["evidence_depth"] = "summary_only"
    return evidence_record


def _compact_event_details(event: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for key in (
        "event_type",
        "security_id",
        "ticker",
        "relationship",
        "portfolio_role",
        "group",
        "status",
        "timing",
        "release_time",
        "category",
        "importance",
        "form",
        "change_pct",
        "material",
    ):
        value = event.get(key)
        if value not in (None, "", [], {}):
            details[key] = value
    contexts = event.get("prepared_event_contexts")
    if isinstance(contexts, list) and contexts:
        details["prepared_event_contexts"] = [
            dict(context) for context in contexts if isinstance(context, dict)
        ]
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "actual",
            "estimate",
            "previous",
            "period",
            "fiscal_period",
            "fiscal_year",
        ):
            value = metadata.get(key)
            if value not in (None, "", [], {}) and key not in details:
                details[key] = value
    return details


def _universe_role_map(raw_universe: Any) -> dict[str, str]:
    if not isinstance(raw_universe, list):
        return {}
    roles: dict[str, str] = {}
    for item in raw_universe:
        if not isinstance(item, dict):
            continue
        security_id = (
            str(item.get("security_id") or item.get("ticker") or "").strip().upper()
        )
        role = str(item.get("source_kind") or item.get("relationship") or "").strip()
        if security_id and role:
            roles[security_id] = role
    return roles


def _collected_source_label(raw_source: str) -> str:
    normalized = re.sub(r"[\s_]+", "-", raw_source.strip().casefold())
    if normalized.startswith("ir-") or normalized == "ir":
        return "Company IR"
    if normalized.startswith(("bls-", "bea-", "fed-")) or normalized in {
        "bls",
        "bea",
        "fed",
        "federal-reserve",
    }:
        return "BLS/BEA/Fed"
    return _canonical_news_source_label(raw_source)


def _prepared_news_source_label(event: dict[str, Any]) -> str:
    raw_source = _first_nonempty_text(
        event.get("news_source"),
        _nested_value(event, "metadata", "news_source"),
        _nested_value(event, "metadata", "source"),
    )
    return _canonical_news_source_label(raw_source)


def _canonical_news_source_label(raw_source: Any) -> str:
    display = re.sub(r"\s+", " ", str(raw_source or "").strip())
    if not display:
        return "Unknown"
    key = re.sub(r"[\s_-]+", " ", display.casefold()).strip()
    if key.startswith("reuters"):
        return "Reuters"
    if key in {"wsj", "wall street journal", "the wall street journal"} or key.startswith(
        ("wsj ", "wall street journal ", "the wall street journal ")
    ):
        return "WSJ"
    if key in {"economist", "the economist"} or key.startswith(
        ("economist ", "the economist ")
    ):
        return "Economist"
    if key.startswith("yahoo"):
        return "Yahoo"
    if key.startswith("cnbc"):
        return "CNBC"
    if key.startswith("bloomberg"):
        return "Bloomberg"
    if key in {"bls", "bea", "fed", "federal reserve"}:
        return "BLS/BEA/Fed"
    aliases = {
        "ap": "AP",
        "associated press": "AP",
        "ft": "FT",
        "financial times": "FT",
        "seekingalpha": "Seeking Alpha",
        "seeking alpha": "Seeking Alpha",
    }
    if key in aliases:
        return aliases[key]
    return display.title() if display.islower() else display


def _candidate_article_url(candidate: CandidateTitle) -> str:
    if candidate.kind == "article":
        raw_url = candidate.metadata.get("url")
    else:
        raw_url = _first_nonempty_text(
            candidate.metadata.get("reference_url"),
            candidate.metadata.get("source_url"),
            _nested_value(candidate.metadata, "metadata", "url"),
        )
    return canonical_news_url(raw_url)


def _article_record_key(
    candidate: CandidateTitle, source_label: str
) -> tuple[str, ...]:
    title = _normalized_title(candidate.title)
    url = _candidate_article_url(candidate)
    if url:
        return ("url", url)
    return (
        "fallback",
        _source_identity(candidate, source_label),
        title,
        _candidate_publication_day(candidate),
    )


def _candidate_publication_day(candidate: CandidateTitle) -> str:
    for value in (
        candidate.metadata.get("published_at"),
        candidate.metadata.get("event_date"),
        candidate.published,
    ):
        match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", str(value or ""))
        if match:
            return match.group(0)
    return candidate.published.strip().casefold()


def _normalized_title(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


def _source_identity(candidate: CandidateTitle, source_label: str) -> str:
    if candidate.kind == "article" and source_label in {"Company IR", "BLS/BEA/Fed"}:
        return f"{source_label}|{candidate.source}".casefold()
    return source_label.casefold()


def _ordered_source_labels(
    counts: dict[str, int],
    *,
    prepared_labels: set[str],
    collected_labels: set[str],
) -> list[str]:
    labels: list[str] = []

    def append(label: str) -> None:
        if label in counts and label not in labels:
            labels.append(label)

    # Prepared news feeds dominate volume, so show their familiar outlets
    # first. Reuters is also a configured full-text source and remains visible
    # at zero when neither collection path produced a record.
    append("Reuters")
    for label in PREFERRED_NEWS_SOURCE_LABELS[1:]:
        if counts.get(label, 0):
            append(label)
    for label in sorted(
        prepared_labels
        - set(PREFERRED_NEWS_SOURCE_LABELS)
        - set(CORE_SOURCE_LABELS),
        key=str.casefold,
    ):
        append(label)

    append("Economist")
    append("WSJ")
    for label in sorted(
        collected_labels - set(CORE_SOURCE_LABELS) - set(PREFERRED_NEWS_SOURCE_LABELS),
        key=str.casefold,
    ):
        append(label)
    append("Company IR")
    append("BLS/BEA/Fed")

    for label in sorted(set(counts) - set(labels), key=str.casefold):
        append(label)
    return labels


def _publication_display(published_raw: str, published_iso: str) -> str:
    """Prefer readable source dates while retaining numeric raw values elsewhere."""
    if published_raw and not re.fullmatch(r"\d+(?:\.\d+)?", published_raw):
        return published_raw
    return published_iso or published_raw


def _epoch_as_iso(raw_epoch: Any) -> str:
    try:
        epoch = int(raw_epoch)
        return (
            datetime.fromtimestamp(epoch, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _bounded_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}\n[content truncated deterministically]"


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _nested_value(payload: dict[str, Any], parent: str, child: str) -> Any:
    nested = payload.get(parent)
    return nested.get(child) if isinstance(nested, dict) else None


def _extract_id_list(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return None
    normalized = {
        str(key).casefold().replace("-", "_"): item for key, item in value.items()
    }
    for key in ("selections", "ids", "shortlist_ids", "selected_ids"):
        selected = normalized.get(key)
        if isinstance(selected, list):
            return selected

    split_ids: list[Any] = []
    found_split_list = False
    for key in ("article_ids", "event_ids"):
        selected = normalized.get(key)
        if isinstance(selected, list):
            found_split_list = True
            split_ids.extend(selected)
    return split_ids if found_split_list else None


def _strip_outer_code_fence(text: str) -> str:
    match = re.fullmatch(
        r"\s*```[^\n`]*\n(.*?)\n?```\s*",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else text


def _section_heading_position(text: str, heading: str) -> int | None:
    pattern = re.compile(
        rf"(?im)^\s*(?:#{{1,3}}\s*)?(?:\*{{1,2}})?{re.escape(heading)}"
        rf"(?:\*{{1,2}})?\s*:?\s*$"
    )
    match = pattern.search(text)
    return match.start() if match else None


def _validate_evidence_section_presence(
    section_positions: dict[str, int | None],
    heading: str,
    *,
    has_evidence: bool | None,
    routing_class: str,
) -> None:
    if has_evidence is None:
        return
    section_is_present = section_positions[heading] is not None
    if has_evidence and not section_is_present:
        raise SynthesisError(
            f"pass 2 omitted required {heading} section for {routing_class} evidence"
        )
    if not has_evidence and section_is_present:
        raise SynthesisError(
            f"pass 2 included {heading} section without {routing_class} evidence"
        )


def _with_retries(operation: Callable[[], Any], *, attempts: int, stage: str) -> Any:
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - retry model and validation failures
            last_error = exc
            if attempt < attempts:
                print(
                    f"morning-brief synthesis: {stage} attempt {attempt} failed; retrying once: {exc}",
                    file=sys.stderr,
                )
    assert last_error is not None
    raise SynthesisError(
        f"{stage} failed after {attempts} attempt{'s' if attempts != 1 else ''}: {last_error}"
    ) from last_error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", required=True, help="Morning-brief run date (YYYY-MM-DD)."
    )
    parser.add_argument("--db", type=Path, help="Path to invest.db.")
    parser.add_argument(
        "--prepared-evidence", type=Path, help="Path to prepared-evidence.json."
    )
    parser.add_argument("--output", type=Path, help="Final Slack brief output path.")
    parser.add_argument(
        "--workspace-root", type=Path, help="Minerva hard-disk workspace root."
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help="OpenClaw model override."
    )
    parser.add_argument(
        "--session-key",
        help=(
            "OpenClaw session key shared by both passes. By default, generate a unique "
            "daily-news-sol-<date>-... key."
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, model_call: ModelCall | None = None) -> int:
    """CLI entry point; stdout is reserved exclusively for the final Slack brief."""
    args = _build_parser().parse_args(argv)
    try:
        run_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"invalid --date value: {args.date!r}", file=sys.stderr)
        return 2

    workspace_root = (
        args.workspace_root
        or Path(os.getenv("MINERVA_WORKSPACE_ROOT", REPO_ROOT / "hard-disk"))
    ).resolve()
    db_path = (
        args.db
        or Path(
            os.getenv(
                "INVEST_DB", workspace_root / "data" / "04-database" / "invest.db"
            )
        )
    ).resolve()
    report_root = workspace_root / "reports" / "03-daily-news" / run_date.isoformat()
    prepared_path = (
        args.prepared_evidence
        or report_root / "data" / "structured" / "prepared-evidence.json"
    ).resolve()
    output_path = (args.output or report_root / "notes" / "slack-brief.md").resolve()

    try:
        brief = synthesize_morning_brief(
            db_path=db_path,
            prepared_path=prepared_path,
            run_date=run_date,
            model_call=model_call,
            model=args.model,
            session_key=args.session_key,
            output_path=output_path,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports all failures
        print(f"morning-brief synthesis failed: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(f"{brief}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
