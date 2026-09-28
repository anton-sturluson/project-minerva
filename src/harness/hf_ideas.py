"""Fetch, validate, and summarize HF Best Ideas weekly issues.

The source newsletter roster is authoritative. Every roster row is retained, rows for
the same company/listing are grouped, and no portfolio database is consulted.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

FEED_URL = "https://hfbestideas.substack.com/feed"
STOCK_URL = "https://www.hfbestideas.com/stock/{ticker}"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)
SAFE_URL_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,19}$")
DATE_TEXT = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{4}"
)
NON_STOCK_NAMES = {"qv investors"}
ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class FetchResult:
    """Result of parsing and optionally archiving one weekly issue."""

    output_dir: Path
    issue_title: str
    issue_date: str
    pitches: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    analysis_count: int
    manifest: dict[str, Any] | None = None


def get(url: str, timeout: int = 40) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_html(raw: str) -> str:
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n\n", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"[ \t\u00a0]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*\n+", "\n\n", txt)
    return txt.strip()


def parse_feed(xml: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", raw, re.S)
        link = re.search(r"<link>(.*?)</link>", raw, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
        body = re.search(
            r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", raw, re.S
        )
        if not (title and body):
            continue
        try:
            dt = parsedate_to_datetime(pub.group(1)).astimezone(timezone.utc) if pub else datetime.now(timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
        out.append(
            {
                "title": title.group(1).strip(),
                "link": link.group(1).strip() if link else "",
                "date": dt,
                "html": body.group(1),
                "text": strip_html(body.group(1)),
            }
        )
    return out


def pick_issue(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the latest roster-style issue, without imposing a body-length guess."""
    ranked = sorted(items, key=lambda item: item["date"], reverse=True)
    for item in ranked:
        if len(re.findall(r"^\s*🔹", item["text"], re.M)) >= 2:
            return item
    return None


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", normalized(value)).strip("-")
    return result or "unnamed"


EXCHANGE_CODE = re.compile(r"[A-Z]{2,3}")


def split_symbol(symbol: str) -> tuple[str, str]:
    """Split a published symbol into ticker and exchange.

    The roster publishes Bloomberg-style ``"AAPL US"``. When the publisher is
    unsure it writes its own marker instead of a code (observed: ``"INOXCVA
    IN? N/A"``). Treat anything that is not a 2-3 letter code as unknown rather
    than letting it leak into the exchange field and the derived company_id.
    ``symbol_as_published`` retains the original text either way.
    """
    parts = symbol.split()
    if not parts:
        return "", ""
    ticker = parts[0].upper()
    if len(parts) == 1:
        return ticker, ""
    candidate = " ".join(parts[1:]).upper()
    if not EXCHANGE_CODE.fullmatch(candidate):
        return ticker, ""
    return ticker, candidate


def entity_kind(company: str, ticker: str) -> str:
    if not ticker and normalized(company) in NON_STOCK_NAMES:
        return "non-stock"
    return "equity"


def company_id_for(company: str, ticker: str, exchange: str, kind: str) -> str:
    if kind == "non-stock":
        listing = "non-stock"
    elif ticker:
        listing = f"{ticker}-{exchange or 'no-exchange'}"
    else:
        listing = "no-symbol"
    return f"{slug(company)}--{slug(listing)}"


def parse_pitches(text: str) -> list[dict[str, Any]]:
    """Parse every roster bullet; do not deduplicate source rows."""
    rows: list[dict[str, Any]] = []
    occurrences: defaultdict[tuple[str, str], int] = defaultdict(int)
    pattern = re.compile(r"^\s*🔹\s*(?P<body>.+?)\s*$", re.M)
    for match in pattern.finditer(text):
        roster_line = f"🔹 {match.group('body').strip()}"
        body = match.group("body").strip()
        parsed = re.match(r"^(.*?)\s*\(([^)]+)\)\s*by\s+(.+)$", body)
        if parsed:
            company, symbol, fund = (part.strip() for part in parsed.groups())
        else:
            parsed_no_symbol = re.match(r"^(.*?)\s+by\s+(.+)$", body)
            if not parsed_no_symbol:
                raise ValueError(f"could not parse roster row: {roster_line}")
            company, fund = (part.strip() for part in parsed_no_symbol.groups())
            symbol = ""
        ticker, exchange = split_symbol(symbol)
        kind = entity_kind(company, ticker)
        company_id = company_id_for(company, ticker, exchange, kind)
        occurrence_key = (company_id, normalized(fund))
        occurrences[occurrence_key] += 1
        roster_id = (
            f"{company_id}--{slug(fund)}--{occurrences[occurrence_key]:02d}"
        )
        rows.append(
            {
                "roster_id": roster_id,
                "company_id": company_id,
                "company": company,
                "ticker": ticker,
                "exchange": exchange,
                "symbol_as_published": symbol,
                "fund": fund,
                "entity_type": kind,
                "issue_excerpt": roster_line,
            }
        )
    return rows


def analysis_key(company: str, ticker: str, exchange: str, fund: str) -> tuple[str, str, str, str]:
    return normalized(company), normalized(ticker), normalized(exchange), normalized(fund)


def parse_issue_analyses(
    text: str,
) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    """Capture detailed issue sections using exact published company/listing/fund keys."""
    header = re.compile(
        r"^\s*(?!🔹)(?P<company>.+?)(?:\s+\(\$(?P<symbol>[^)]+)\))?\s+Fund:\s+(?P<fund>.+?)\s*$",
        re.M,
    )
    matches = []
    for match in header.finditer(text):
        lookahead = text[match.end() : match.end() + 500]
        if re.search(r"^\s*Thesis:\s+", lookahead, re.M):
            matches.append(match)
    analyses: defaultdict[
        tuple[str, str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for index, match in enumerate(matches):
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : block_end]
        thesis_match = re.search(r"^\s*Thesis:\s*(.+?)\s*$", block, re.M)
        analysis_match = re.search(r"^\s*Analysis:\s*(.*)$", block, re.M | re.S)
        thesis = thesis_match.group(1).strip() if thesis_match else ""
        analysis = analysis_match.group(1).strip() if analysis_match else ""
        analysis = re.split(
            r"^\s*(?:Access our full research database|🔓 Unlock|This post has bonus content)",
            analysis,
            maxsplit=1,
            flags=re.M,
        )[0].strip()
        symbol_parts = (match.group("symbol") or "").split()
        ticker = symbol_parts[0].upper() if symbol_parts else ""
        exchange = " ".join(symbol_parts[1:]).upper() if len(symbol_parts) > 1 else ""
        key = analysis_key(match.group("company"), ticker, exchange, match.group("fund"))
        analyses[key].append(
            {
                "company": match.group("company").strip(),
                "ticker": ticker,
                "exchange": exchange,
                "fund": match.group("fund").strip(),
                "thesis": thesis,
                "analysis": analysis,
            }
        )
    return dict(analyses)


def group_pitches(
    pitches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for pitch in pitches:
        key = (
            normalized(pitch["company"]),
            normalized(pitch["ticker"]),
            normalized(pitch["exchange"]),
            pitch["entity_type"],
        )
        group = by_identity.get(key)
        if group is None:
            group = {
                "company_id": pitch["company_id"],
                "company": pitch["company"],
                "ticker": pitch["ticker"],
                "exchange": pitch["exchange"],
                "entity_type": pitch["entity_type"],
                "roster_entries": [],
            }
            by_identity[key] = group
            groups.append(group)
        group["roster_entries"].append(pitch)
    return groups


def public_page_identity(body: str) -> tuple[str, str] | None:
    match = re.search(
        r"(?:^|\n)\s*(.+?)\s+\(([^)]+)\):\s+the hedge fund thesis,\s+in their own words",
        body,
        re.I,
    )
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def named_public_context(body: str, fund: str) -> list[str]:
    """Return bounded exact excerpts around the featured fund only."""
    excerpts: list[str] = []
    anchored = re.compile(
        rf"{re.escape(fund)}\s+(?P<date>{DATE_TEXT})\s+(?P<body>.{{0,1600}}?)"
        r"(?P<end>Read the (?:full thesis|letter)\s*→)",
        re.S,
    )
    for match in anchored.finditer(body):
        start = max(0, match.start() - 40)
        prefix = body[start : match.start()]
        status = re.search(
            r"(New position|Added|Holds|Trimmed|Exited|Mentioned|Bought|Sold)\s*$",
            prefix,
        )
        label = status.group(1) if status else "Public synopsis"
        excerpt = f"{label} — {fund} {match.group('date')} {match.group('body').strip()}"
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        if excerpt and excerpt not in excerpts:
            excerpts.append(excerpt)
    return excerpts


def fetch_public_sources(
    groups: list[dict[str, Any]],
    outdir: Path,
    *,
    getter: Callable[[str], str] = get,
    sleep_seconds: float = 1.0,
    progress: ProgressCallback | None = None,
) -> dict[str, dict[str, Any]]:
    raw_dir = outdir / "raw-public"
    readable_dir = outdir / "public"
    raw_dir.mkdir(parents=True, exist_ok=True)
    readable_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, Any]] = {}

    targets = [group for group in groups if group["entity_type"] == "equity" and group["ticker"]]
    target_number = 0
    for group in groups:
        company_id = group["company_id"]
        if group["entity_type"] == "non-stock":
            records[company_id] = {
                "status": "not-requested",
                "reason": "the source roster identifies this as a non-stock due-diligence item",
                "url": None,
                "named_context": {},
            }
            continue
        ticker = group["ticker"]
        if not ticker:
            records[company_id] = {
                "status": "not-requested",
                "reason": "the source roster provides no ticker; no /stock URL was guessed",
                "url": None,
                "named_context": {},
            }
            continue
        if not SAFE_URL_TICKER.fullmatch(ticker):
            records[company_id] = {
                "status": "not-requested",
                "reason": f"published ticker {ticker!r} is not safe to place in a stock-page URL",
                "url": None,
                "named_context": {},
            }
            continue

        target_number += 1
        url = STOCK_URL.format(ticker=urllib.parse.quote(ticker, safe=""))
        try:
            raw = getter(url)
            body = strip_html(raw)
            (raw_dir / f"{company_id}.html").write_text(raw, encoding="utf-8")
            identity = public_page_identity(body)
            identity_ok = bool(
                identity
                and normalized(identity[0]) == normalized(group["company"])
                and normalized(identity[1]) == normalized(ticker)
            )
            if identity_ok:
                status = "fetched"
                reason = "public page company and ticker exactly match the published roster identity"
            elif identity:
                status = "identity-mismatch"
                reason = (
                    f"requested {group['company']} ({ticker}); public page identified itself as "
                    f"{identity[0]} ({identity[1]}); excluded from extraction"
                )
            else:
                status = "identity-unverified"
                reason = "public page did not expose a verifiable company/ticker heading; excluded from extraction"
            contexts = {
                entry["roster_id"]: named_public_context(body, entry["fund"])
                for entry in group["roster_entries"]
            }
            readable = (
                f"# Public stock-page archive: {group['company']}\n\n"
                f"- Requested source identity: {group['company']} ({ticker} {group['exchange']})\n"
                f"- URL: {url}\n- Validation status: {status}\n- Validation note: {reason}\n\n"
                f"---\n\n{body}\n"
            )
            (readable_dir / f"{company_id}.md").write_text(readable, encoding="utf-8")
            records[company_id] = {
                "status": status,
                "reason": reason,
                "url": url,
                "raw_file": f"raw-public/{company_id}.html",
                "readable_file": f"public/{company_id}.md",
                "chars": len(body),
                "page_company": identity[0] if identity else None,
                "page_ticker": identity[1] if identity else None,
                "named_context": contexts,
            }
            if progress:
                progress(f"  [{target_number}/{len(targets)}] {ticker:<8} {status}")
        except urllib.error.HTTPError as exc:
            reason = f"HTTP {exc.code} for the exact published ticker at {url}"
            records[company_id] = {
                "status": "http-error",
                "reason": reason,
                "url": url,
                "named_context": {},
            }
            if progress:
                progress(f"  [{target_number}/{len(targets)}] {ticker:<8} HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - preserve a per-source operational reason
            reason = f"{type(exc).__name__}: {str(exc)[:160]}"
            records[company_id] = {
                "status": "request-error",
                "reason": reason,
                "url": url,
                "named_context": {},
            }
            if progress:
                progress(f"  [{target_number}/{len(targets)}] {ticker:<8} {reason}")
        if sleep_seconds and target_number < len(targets):
            time.sleep(sleep_seconds)
    return records


def find_issue_analysis(
    entry: dict[str, Any],
    analyses: dict[tuple[str, str, str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    key = analysis_key(entry["company"], entry["ticker"], entry["exchange"], entry["fund"])
    matches = analyses.get(key, [])
    return matches[0] if matches else None


def render_source_document(
    group: dict[str, Any],
    analyses: dict[tuple[str, str, str, str], list[dict[str, Any]]],
    public: dict[str, Any],
    *,
    issue_title: str,
    issue_url: str,
    issue_date: str,
) -> str:
    symbol = " ".join(part for part in [group["ticker"], group["exchange"]] if part) or "no ticker published"
    lines = [
        f"# Weekly idea extraction source: {group['company']}",
        "",
        "## Authoritative identity",
        f"- Company ID: `{group['company_id']}`",
        f"- Company as published: {group['company']}",
        f"- Listing as published: {symbol}",
        f"- Entity type: {group['entity_type']}",
        f"- Issue: [{issue_title}]({issue_url})",
        f"- Issue publication date (not necessarily the commentary date): {issue_date}",
        "",
        "## Source-use rules",
        "The featured roster fund is authoritative. Use its matching issue analysis first. A public stock-page excerpt is secondary and may be only a one-line synopsis or a truncated comment, not proof of full-letter access. Do not substitute another fund's history, infer a missing ticker, or infer a risk, valuation, stance, or commentary date that is not stated.",
        "",
        "## Featured roster entries",
    ]
    for entry in group["roster_entries"]:
        issue_analysis = find_issue_analysis(entry, analyses)
        contexts = public.get("named_context", {}).get(entry["roster_id"], [])
        lines.extend(
            [
                "",
                f"### {entry['fund']}",
                f"- Roster ID: `{entry['roster_id']}`",
                f"- Exact issue roster excerpt: {entry['issue_excerpt']}",
                "",
                "#### Matching analysis in this issue (primary)",
            ]
        )
        if issue_analysis:
            lines.append(f"- Published thesis: {issue_analysis['thesis']}")
            lines.append("")
            lines.append(issue_analysis["analysis"] or "No additional analysis text was published.")
        else:
            lines.append(
                "No detailed matching analysis was present in the fetched issue body. "
                "The publisher may have truncated the issue, or this roster item may only be listed."
            )
        lines.extend(["", "#### Exact named-fund text on the public stock page (secondary)"])
        if public.get("status") == "fetched" and contexts:
            lines.extend(f"- {context}" for context in contexts)
        elif public.get("status") == "fetched":
            lines.append(
                f"The public page was fetched and identity-validated, but no bounded excerpt for the exact featured fund {entry['fund']} was located."
            )
        else:
            lines.append(f"Unavailable: {public.get('reason', 'no public source result')}")
    lines.extend(
        [
            "",
            "## Public source resolution",
            f"- Status: {public.get('status', 'unavailable')}",
            f"- URL: {public.get('url') or 'not requested'}",
            f"- Reason: {public.get('reason', 'not recorded')}",
        ]
    )
    if public.get("readable_file"):
        lines.append(f"- Full readable public-page archive: ../{public['readable_file']}")
        lines.append(f"- Raw public HTML archive: ../{public['raw_file']}")
    return "\n".join(lines) + "\n"


def backup_and_clear_generated(outdir: Path) -> Path | None:
    generated = [
        "issue.md",
        "issue.raw.html",
        "manifest.json",
        "extraction-files.txt",
        "content",
        "public",
        "raw-public",
        "extractions",
        "summary.md",
        "INDEX.md",
        "coverage.json",
        "PIPELINE_FAILED.md",
    ]
    existing = [outdir / name for name in generated if (outdir / name).exists()]
    if not existing:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = outdir / ".backups" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    for source in existing:
        target = backup / source.name
        if source.is_dir():
            shutil.copytree(source, target)
            shutil.rmtree(source)
        else:
            shutil.copy2(source, target)
            source.unlink()
    return backup


def write_issue_outputs(
    issue: dict[str, Any],
    pitches: list[dict[str, Any]],
    analyses: dict[tuple[str, str, str, str], list[dict[str, Any]]],
    outdir: Path,
    sleep_seconds: float,
    *,
    getter: Callable[[str], str] = get,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    backup = backup_and_clear_generated(outdir)
    content_dir = outdir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)
    groups = group_pitches(pitches)

    issue_date = issue["date"].date().isoformat()
    issue_md = (
        f"# {issue['title']}\n\n- Source: {issue['link']}\n"
        f"- Published: {issue['date'].isoformat()}\n"
        f"- Paywalled: {'paid subscribers' in issue['text']}\n\n---\n\n{issue['text']}\n"
    )
    (outdir / "issue.md").write_text(issue_md, encoding="utf-8")
    (outdir / "issue.raw.html").write_text(issue["html"], encoding="utf-8")

    target_count = sum(
        bool(group["ticker"]) and group["entity_type"] == "equity" for group in groups
    )
    if progress:
        progress(f"→ requesting public pages for {target_count} exact published tickers")
    public_sources = fetch_public_sources(
        groups,
        outdir,
        getter=getter,
        sleep_seconds=sleep_seconds,
        progress=progress,
    )

    analysis_count = 0
    for group in groups:
        for entry in group["roster_entries"]:
            has_analysis = find_issue_analysis(entry, analyses) is not None
            entry["issue_analysis"] = has_analysis
            analysis_count += int(has_analysis)
        source = render_source_document(
            group,
            analyses,
            public_sources[group["company_id"]],
            issue_title=issue["title"],
            issue_url=issue["link"],
            issue_date=issue_date,
        )
        (content_dir / f"{group['company_id']}.md").write_text(source, encoding="utf-8")

    files_from = outdir / "extraction-files.txt"
    files_from.write_text(
        "# One extraction input per exact company/listing identity; together these cover every roster row.\n"
        + "\n".join(f"content/{group['company_id']}.md" for group in groups)
        + "\n",
        encoding="utf-8",
    )
    paywalled = "paid subscribers" in issue["text"]
    manifest = {
        "schema_version": 2,
        "issue_title": issue["title"],
        "issue_url": issue["link"],
        "issue_date": issue["date"].isoformat(),
        "paywalled": paywalled,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "scope": "all-source-roster-entries",
        "pitch_count": len(pitches),
        "company_count": len(groups),
        "issue_analysis_count": analysis_count,
        "backup": str(backup) if backup else None,
        "pitches": pitches,
        "companies": groups,
        "public_sources": public_sources,
        "extraction_files": [f"content/{group['company_id']}.md" for group in groups],
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def fetch_latest_issue(
    output_root: Path,
    *,
    dry_run: bool = False,
    sleep_seconds: float = 1.0,
    getter: Callable[[str], str] = get,
    progress: ProgressCallback | None = None,
) -> FetchResult:
    """Fetch and parse the latest roster issue, optionally archiving its sources."""
    if sleep_seconds < 0:
        raise PipelineError("sleep duration must be non-negative")
    if progress:
        progress("→ fetching feed")
    try:
        items = parse_feed(getter(FEED_URL))
    except Exception as exc:  # noqa: BLE001 - preserve the network failure detail
        raise PipelineError(f"feed fetch failed: {type(exc).__name__}: {exc}") from exc
    issue = pick_issue(items)
    if issue is None:
        raise PipelineError("no roster-style issue found")
    try:
        pitches = parse_pitches(issue["text"])
        analyses = parse_issue_analyses(issue["text"])
    except ValueError as exc:
        raise PipelineError(f"roster parse failed: {exc}") from exc
    if not pitches:
        raise PipelineError("issue contained no parseable roster rows")

    issue_date = issue["date"].date().isoformat()
    output_dir = output_root.expanduser().resolve() / issue_date
    groups = group_pitches(pitches)
    analysis_count = sum(len(items) for items in analyses.values())
    if progress:
        progress(f"→ issue: {issue['title'][:72]} ({issue_date})")
        progress(
            "→ roster reconciliation: "
            f"{len(pitches)} rows, {len(groups)} company/listing identities, "
            f"{analysis_count} detailed issue analyses"
        )
    if dry_run:
        return FetchResult(
            output_dir=output_dir,
            issue_title=issue["title"],
            issue_date=issue_date,
            pitches=pitches,
            groups=groups,
            analysis_count=analysis_count,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        manifest = write_issue_outputs(
            issue,
            pitches,
            analyses,
            output_dir,
            sleep_seconds,
            getter=getter,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001 - add stage context to operational failures
        raise PipelineError(f"fetch preparation failed: {type(exc).__name__}: {exc}") from exc
    return FetchResult(
        output_dir=output_dir,
        issue_title=issue["title"],
        issue_date=issue_date,
        pitches=pitches,
        groups=groups,
        analysis_count=analysis_count,
        manifest=manifest,
    )


STANCE_VALUES = {"bull", "bear", "neutral", "unclear"}
BASIS_VALUES = {
    "issue",
    "full comment",
    "public synopsis",
    "informational",
    "unavailable",
    "non-stock",
}
REQUIRED_TOP = {
    "schema_version",
    "company_id",
    "company",
    "ticker",
    "exchange",
    "entity_type",
    "company_summary",
    "fund_views",
}
REQUIRED_VIEW = {
    "roster_id",
    "featured_fund",
    "commentary_date",
    "stance",
    "core_thesis",
    "source_basis",
    "source_url",
    "supporting_quote",
    "unresolved_reason",
}


class PipelineError(ValueError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"malformed JSON in {path}: {exc}") from exc


def parse_extraction_json(
    text: str, *, source_name: str = "extraction"
) -> dict[str, Any]:
    """Accept direct JSON or one JSON object in a markdown wrapper; reject legacy prose."""
    if not text.strip():
        raise PipelineError(f"{source_name}: extraction is empty")

    fences = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fences:
        if len(fences) != 1:
            raise PipelineError(f"{source_name}: expected one JSON fence, found {len(fences)}")
        try:
            value = json.loads(fences[0].strip())
        except json.JSONDecodeError as exc:
            raise PipelineError(f"{source_name}: malformed fenced JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise PipelineError(f"{source_name}: top-level JSON must be an object")
        return value

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {"schema_version", "company_id"} <= set(value):
            candidates.append(value)
    if len(candidates) != 1:
        if not candidates:
            raise PipelineError(
                f"{source_name}: no structured extraction JSON found (legacy headings/bold prose are not accepted)"
            )
        raise PipelineError(f"{source_name}: expected one extraction JSON object, found {len(candidates)}")
    return candidates[0]


def normalized_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def sentence_count(value: str) -> int:
    protected = value
    for abbreviation in ("Inc.", "Co.", "Corp.", "Ltd.", "U.S.", "U.K.", "e.g.", "i.e."):
        protected = protected.replace(abbreviation, abbreviation[:-1] + "∯")
    return len(re.findall(r"[.!?](?=\s|$)", protected))


def archived_source_urls(manifest: dict[str, Any]) -> set[str]:
    """Every URL this run actually fetched and archived on disk.

    Used only to tell a misrouted-but-real citation apart from an invented one.
    A URL absent from this set is never accepted.
    """
    urls: set[str] = set()
    issue_url = manifest.get("issue_url")
    if isinstance(issue_url, str) and issue_url:
        urls.add(issue_url)
    for public in manifest.get("public_sources", {}).values():
        if not isinstance(public, dict):
            continue
        if public.get("status") != "fetched":
            continue
        url = public.get("url")
        if isinstance(url, str) and url:
            urls.add(url)
    return urls


def source_rules(
    entry: dict[str, Any],
    group: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[set[str], set[str | None]]:
    public = manifest["public_sources"][group["company_id"]]
    if group["entity_type"] == "non-stock":
        return {"non-stock"}, {manifest["issue_url"], None}
    if entry.get("issue_analysis"):
        return {"issue"}, {manifest["issue_url"]}
    contexts = public.get("named_context", {}).get(entry["roster_id"], [])
    if public.get("status") == "fetched" and contexts:
        return {"public synopsis", "informational"}, {public.get("url")}
    if public.get("status") == "fetched":
        return {"informational", "unavailable"}, {public.get("url"), manifest["issue_url"], None}
    return {"unavailable"}, {manifest["issue_url"], public.get("url"), None}


def normalize_ticker_exchange(
    data: dict[str, Any],
    group: dict[str, Any],
    path: Path,
    warning_list: list[str],
) -> None:
    """Repair extractions that merge ticker and exchange into the ticker field.

    Models commonly return the roster's display form (``"APH US"``) for ticker
    and leave exchange blank, instead of the split form (``"APH"`` / ``"US"``).
    Only rewrite when the merged value reconstructs the expected pair exactly;
    any other mismatch still raises downstream so real attribution errors are
    never silently accepted.
    """
    expected_ticker = group.get("ticker")
    expected_exchange = group.get("exchange")
    if not isinstance(expected_ticker, str) or not isinstance(expected_exchange, str):
        return
    if not expected_ticker or not expected_exchange:
        return
    actual_ticker = data.get("ticker")
    if not isinstance(actual_ticker, str):
        return
    if actual_ticker == expected_ticker:
        return
    actual_exchange = data.get("exchange")
    if isinstance(actual_exchange, str) and actual_exchange.strip():
        return
    if normalized_space(actual_ticker) != normalized_space(f"{expected_ticker} {expected_exchange}"):
        return
    data["ticker"] = expected_ticker
    data["exchange"] = expected_exchange
    warning_list.append(
        f"{path}: normalized merged ticker {actual_ticker!r} into "
        f"ticker {expected_ticker!r} + exchange {expected_exchange!r}"
    )


def validate_extraction(
    data: dict[str, Any],
    group: dict[str, Any],
    manifest: dict[str, Any],
    source_text: str,
    path: Path,
    *,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    warning_list = warnings if warnings is not None else []
    missing = REQUIRED_TOP - set(data)
    if missing:
        raise PipelineError(f"{path}: missing top-level fields: {', '.join(sorted(missing))}")
    normalize_ticker_exchange(data, group, path, warning_list)
    expected_metadata = {
        "schema_version": 1,
        "company_id": group["company_id"],
        "company": group["company"],
        "ticker": group["ticker"],
        "exchange": group["exchange"],
        "entity_type": group["entity_type"],
    }
    for field, expected in expected_metadata.items():
        if data[field] != expected:
            raise PipelineError(f"{path}: {field} must be {expected!r}, got {data[field]!r}")
    summary = data["company_summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise PipelineError(f"{path}: company_summary is blank")
    if "\n" in summary.strip():
        warning_list.append(f"{path}: company_summary contains newlines; expected one paragraph")

    views = data["fund_views"]
    if not isinstance(views, list):
        raise PipelineError(f"{path}: fund_views must be an array")
    expected_entries = group["roster_entries"]
    if len(views) != len(expected_entries):
        raise PipelineError(
            f"{path}: fund coverage mismatch: expected {len(expected_entries)} views, got {len(views)}"
        )

    for position, (view, entry) in enumerate(zip(views, expected_entries, strict=True), 1):
        if not isinstance(view, dict):
            raise PipelineError(f"{path}: fund_views[{position}] must be an object")
        missing_view = REQUIRED_VIEW - set(view)
        if missing_view:
            raise PipelineError(
                f"{path}: fund_views[{position}] missing fields: {', '.join(sorted(missing_view))}"
            )
        if view["roster_id"] != entry["roster_id"]:
            raise PipelineError(
                f"{path}: fund_views[{position}] roster_id attribution mismatch; expected {entry['roster_id']!r}"
            )
        if view["featured_fund"] != entry["fund"]:
            raise PipelineError(
                f"{path}: fund_views[{position}] fund attribution mismatch; expected {entry['fund']!r}"
            )
        if view["stance"] not in STANCE_VALUES:
            raise PipelineError(f"{path}: invalid stance {view['stance']!r}")
        if view["source_basis"] not in BASIS_VALUES:
            raise PipelineError(f"{path}: invalid source_basis {view['source_basis']!r}")
        if view["source_basis"] in {"unavailable", "non-stock"} and view["stance"] != "unclear":
            raise PipelineError(
                f"{path}: {entry['fund']} must use stance 'unclear' when source_basis is {view['source_basis']!r}"
            )
        allowed_basis, allowed_urls = source_rules(entry, group, manifest)
        if view["source_basis"] not in allowed_basis:
            raise PipelineError(
                f"{path}: {entry['fund']} source_basis {view['source_basis']!r} conflicts with available named-fund sources; allowed: {sorted(allowed_basis)}"
            )
        if view["source_url"] not in allowed_urls:
            archived_urls = archived_source_urls(manifest)
            concrete_allowed = sorted(url for url in allowed_urls if url)
            if view["source_url"] in archived_urls and len(concrete_allowed) == 1:
                # The cited link is a real artifact this run archived, just not the
                # one matching this basis. Repoint it; never invent a URL.
                warning_list.append(
                    f"{path}: {entry['fund']} cited archived source {view['source_url']!r} "
                    f"but basis {view['source_basis']!r} expects {concrete_allowed[0]!r}; repointed"
                )
                view["source_url"] = concrete_allowed[0]
            else:
                raise PipelineError(
                    f"{path}: {entry['fund']} source_url {view['source_url']!r} is not an archived supporting source"
                )
        date = view["commentary_date"]
        if date is not None and (
            not isinstance(date, str)
            or not re.fullmatch(
                r"(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|[A-Za-z]+\s+\d{4}|Q[1-4]\s+\d{4})",
                date,
            )
        ):
            warning_list.append(f"{path}: unexpected commentary_date format {date!r}")
        thesis = view["core_thesis"]
        if not isinstance(thesis, str) or not thesis.strip():
            raise PipelineError(f"{path}: {entry['fund']} core_thesis is blank")
        if view["source_basis"] in {"issue", "public synopsis", "full comment"}:
            count = sentence_count(thesis)
            if not 2 <= count <= 4:
                warning_list.append(
                    f"{path}: {entry['fund']} supported core_thesis should contain 2-4 sentences (found {count})"
                )
        quote = view["supporting_quote"]
        if not isinstance(quote, str):
            raise PipelineError(f"{path}: supporting_quote must be a string")
        if view["source_basis"] in {"issue", "public synopsis", "full comment"} and not quote.strip():
            raise PipelineError(f"{path}: {entry['fund']} supported thesis requires an exact supporting quote")
        if len(quote) > 500:
            warning_list.append(
                f"{path}: {entry['fund']} supporting_quote is over 500 characters"
            )
        if quote.strip() and normalized_space(quote.strip().strip('"“”')) not in normalized_space(source_text):
            raise PipelineError(f"{path}: {entry['fund']} supporting_quote is not an exact excerpt from its input")
        reason = view["unresolved_reason"]
        if not isinstance(reason, str):
            raise PipelineError(f"{path}: unresolved_reason must be a string")
        if view["source_basis"] in {"unavailable", "informational", "non-stock"} and not reason.strip():
            raise PipelineError(f"{path}: {entry['fund']} requires a visible unresolved/source-limit reason")
    return views


def validate_manifest(
    manifest: dict[str, Any], folder: Path
) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != 2:
        raise PipelineError(
            "fetch manifest is not schema_version 2; rerun `minerva ideas fetch` before extraction"
        )
    pitches = manifest.get("pitches")
    groups = manifest.get("companies")
    if not isinstance(pitches, list) or len(pitches) != manifest.get("pitch_count"):
        raise PipelineError("fetch manifest pitch reconciliation failed")
    if not isinstance(groups, list) or len(groups) != manifest.get("company_count"):
        raise PipelineError("fetch manifest company reconciliation failed")
    roster_ids = [pitch.get("roster_id") for pitch in pitches]
    grouped_ids = [entry.get("roster_id") for group in groups for entry in group.get("roster_entries", [])]
    if len(roster_ids) != len(set(roster_ids)):
        raise PipelineError("fetch manifest contains duplicate roster IDs")
    if roster_ids != grouped_ids:
        raise PipelineError("grouped companies do not preserve every roster entry in source order")
    expected_files = [f"content/{group['company_id']}.md" for group in groups]
    if manifest.get("extraction_files") != expected_files:
        raise PipelineError("manifest extraction_files do not cover every company group in source order")
    listed = [
        line.strip()
        for line in (folder / "extraction-files.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if listed != expected_files:
        raise PipelineError("extraction-files.txt does not exactly match the manifest company coverage")
    for relative in expected_files:
        if not (folder / relative).is_file():
            raise PipelineError(f"missing extraction input: {relative}")
    return groups


def validate_extraction_manifest(
    folder: Path, expected_inputs: list[Path]
) -> dict[str, Any]:
    extraction_manifest = load_json(folder / "extractions" / "manifest.json")
    entries = extraction_manifest.get("entries")
    if not isinstance(entries, list):
        raise PipelineError("extractions/manifest.json has no entries array")
    expected = {path.resolve() for path in expected_inputs}
    actual: set[Path] = set()
    for entry in entries:
        if entry.get("status") != "ok":
            raise PipelineError(
                f"minerva extraction failed for {entry.get('source')}: {entry.get('error') or entry.get('status')}"
            )
        actual.add(Path(entry.get("source", "")).resolve())
        output = Path(entry.get("output", ""))
        if not output.is_file():
            raise PipelineError(f"minerva reports success but output is missing: {output}")
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        raise PipelineError(
            f"minerva manifest input coverage mismatch: {len(missing)} missing, {len(extra)} unexpected"
        )
    return extraction_manifest


def markdown_label(group: dict[str, Any]) -> str:
    symbol = " ".join(part for part in [group["ticker"], group["exchange"]] if part)
    if group["entity_type"] == "non-stock":
        return f"{group['company']} (non-stock)"
    return f"{group['company']} ({symbol})" if symbol else f"{group['company']} (no ticker published)"


def escape_markdown(value: str) -> str:
    return value.replace("|", "/").replace("[", "\\[").replace("]", "\\]")


def build_report(folder: Path) -> dict[str, Any]:
    manifest = load_json(folder / "manifest.json")
    groups = validate_manifest(manifest, folder)
    expected_inputs = [folder / relative for relative in manifest["extraction_files"]]
    validate_extraction_manifest(folder, expected_inputs)

    validated: list[
        tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], Path]
    ] = []
    all_roster_ids: list[str] = []
    warnings: list[str] = []
    for group in groups:
        extraction_path = folder / "extractions" / f"{group['company_id']}.md"
        try:
            raw = extraction_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PipelineError(f"missing extraction output: {extraction_path}") from exc
        data = parse_extraction_json(raw, source_name=str(extraction_path))
        source_text = (folder / "content" / f"{group['company_id']}.md").read_text(encoding="utf-8")
        views = validate_extraction(
            data,
            group,
            manifest,
            source_text,
            extraction_path,
            warnings=warnings,
        )
        validated.append((group, data, views, extraction_path))
        all_roster_ids.extend(view["roster_id"] for view in views)

    expected_roster_ids = [pitch["roster_id"] for pitch in manifest["pitches"]]
    if all_roster_ids != expected_roster_ids:
        raise PipelineError("validated extraction views do not reconcile to the complete source roster")

    basis_counts = {basis: 0 for basis in BASIS_VALUES}
    stance_counts = {stance: 0 for stance in STANCE_VALUES}
    for _, _, views, _ in validated:
        for view in views:
            basis_counts[view["source_basis"]] += 1
            stance_counts[view["stance"]] += 1
    gap_count = basis_counts["unavailable"] + basis_counts["informational"] + basis_counts["non-stock"]
    issue_date = manifest["issue_date"][:10]
    lines = [
        f"# HF Best Ideas — week of {issue_date}",
        "",
        f"*{manifest['issue_title']}*",
        "",
        f"- Source: [{manifest['issue_url']}]({manifest['issue_url']})",
        f"- Published: {issue_date}",
        f"- Coverage reconciliation: **{len(all_roster_ids)}/{manifest['pitch_count']} roster entries** across **{len(validated)}/{manifest['company_count']} company/listing identities**",
        f"- Evidence: **{basis_counts['issue']} issue analyses**, **{basis_counts['public synopsis']} public synopses**, **{basis_counts['informational']} informational-only**, **{basis_counts['unavailable']} unavailable**, **{basis_counts['non-stock']} non-stock**",
        f"- Stances: **{stance_counts['bull']} bull**, **{stance_counts['bear']} bear**, **{stance_counts['neutral']} neutral**, **{stance_counts['unclear']} unclear**",
        f"- Publisher paywall in fetched issue: {'yes; each truncated/missing source is handled individually' if manifest['paywalled'] else 'no indication detected'}",
        "",
        "## Company ideas",
        "",
    ]

    used_public_urls: dict[str, str] = {}
    for group, data, views, extraction_path in validated:
        lines.append(f"### {markdown_label(group)}")
        metadata = "; ".join(
            f"{escape_markdown(view['featured_fund'])} — {view['stance']}, "
            f"{view['commentary_date'] or 'date not stated'}, {view['source_basis']}"
            for view in views
        )
        source_links = [
            f"[issue]({manifest['issue_url']})",
            f"[source file](./content/{group['company_id']}.md)",
            f"[extraction](./extractions/{group['company_id']}.md)",
        ]
        public = manifest["public_sources"][group["company_id"]]
        if public.get("status") == "fetched" and public.get("url"):
            source_links.insert(1, f"[public stock page]({public['url']})")
            used_public_urls[public["url"]] = group["company"]
        quote = next((view["supporting_quote"].strip() for view in views if view["supporting_quote"].strip()), "")
        quote_text = f" Supporting quote: “{quote.strip().strip(chr(34)).strip('“”')}”" if quote else ""
        lines.append(
            f"**Featured fund view(s):** {metadata}. {data['company_summary'].strip()}{quote_text} "
            f"({' · '.join(source_links)})"
        )
        lines.append("")

    lines.extend(
        [
            "## Coverage reconciliation",
            "",
            f"All **{manifest['pitch_count']}** source roster entries are represented exactly once in the validated fund views. They reconcile to **{manifest['company_count']}** company/listing identities; repeated companies are grouped without dropping their featured funds. **{gap_count}** entries are retained as explicit informational, unavailable, or non-stock gaps rather than silently omitted.",
            "",
            "## References",
            "",
            "### Newsletter issue",
            f"- [{manifest['issue_title']}]({manifest['issue_url']}) — source roster and the detailed analyses exposed in the fetched issue body.",
        ]
    )
    if used_public_urls:
        lines.extend(["", "### Public company pages"])
        for url, company in sorted(used_public_urls.items(), key=lambda item: item[1].casefold()):
            lines.append(f"- [{company}]({url}) — public stock-page text; treated as partial evidence, not full-letter access.")

    coverage = {
        "issue_date": issue_date,
        "roster_expected": manifest["pitch_count"],
        "roster_validated": len(all_roster_ids),
        "companies_expected": manifest["company_count"],
        "companies_validated": len(validated),
        "basis_counts": basis_counts,
        "stance_counts": stance_counts,
        "gap_count": gap_count,
        "warnings": warnings,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    (folder / "coverage.json").write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (folder / "PIPELINE_FAILED.md").unlink(missing_ok=True)

    index_lines = [
        f"# Weekly Ideas {issue_date}",
        "",
        f"HF Best Ideas issue for {issue_date}, archived with complete source-roster coverage and strictly validated featured-fund extractions.",
        "",
        "| Name | Type | Notes |",
        "| --- | --- | --- |",
        "| [summary.md](./summary.md) | file | Compact validated digest — start here. |",
        "| [issue.md](./issue.md) | file | Readable newsletter text from the feed. |",
        "| [issue.raw.html](./issue.raw.html) | file | Original newsletter HTML body. |",
        "| [content/](./content/) | folder | Extraction inputs covering every roster entry. |",
        "| [public/](./public/) | folder | Readable public stock-page archives where requested. |",
        "| [raw-public/](./raw-public/) | folder | Raw fetched public stock-page HTML. |",
        "| [extractions/](./extractions/) | folder | Structured per-company JSON extractions in markdown wrappers. |",
        "| [manifest.json](./manifest.json) | file | Identities, roster mapping, source resolution, and fetch record. |",
        "| [extraction-files.txt](./extraction-files.txt) | file | Explicit complete input list for `minerva extract-files`. |",
        "| [coverage.json](./coverage.json) | file | Final validation and reconciliation counts. |",
        "",
        "## Notes",
        f"- {coverage['roster_validated']}/{coverage['roster_expected']} roster entries and {coverage['companies_validated']}/{coverage['companies_expected']} companies validated.",
        "- Public-source failures are recorded per exact published identity; no exchange-wide availability claim is inferred.",
        "- Prior generated outputs are recoverably archived under `.backups/` when a dated issue is rerun.",
    ]
    (folder / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    update_parent_index(folder.parent)
    return coverage


def update_parent_index(parent: Path) -> None:
    rows: list[str] = []
    for child in sorted((path for path in parent.iterdir() if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)), reverse=True):
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        pitches = manifest.get("pitch_count", len(manifest.get("pitches", [])))
        companies = manifest.get("company_count")
        coverage_path = child / "coverage.json"
        if coverage_path.exists():
            try:
                coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
                note = f"{coverage['roster_validated']}/{coverage['roster_expected']} roster entries validated across {coverage['companies_validated']} companies."
            except (json.JSONDecodeError, KeyError):
                note = f"{pitches} roster entries; validation record unreadable."
        elif companies is not None:
            note = f"{pitches} roster entries across {companies} companies; summary not yet validated."
        else:
            note = f"Legacy run with {pitches} roster entries."
        rows.append(f"| [{child.name}/](./{child.name}/INDEX.md) | folder | {note} |")
    text = [
        "# 05-weekly-ideas",
        "",
        "Weekly HF Best Ideas runs. Each dated folder retains the raw issue, readable and raw public sources, complete per-company extraction inputs, strict structured extractions, and a compact validated summary.",
        "",
        "| Name | Type | Notes |",
        "| --- | --- | --- |",
        *rows,
        "",
        "## Notes",
        "",
        "- Folder date is the newsletter publication date, not the fetch date.",
        "- The source newsletter roster is authoritative: there is no `invest.db` gating and no arbitrary stock-page limit.",
        "- Missing tickers, foreign listings, source failures, and the explicit non-stock item remain in coverage with per-identity reasons.",
        "- The reusable pipeline is available through `minerva ideas`.",
    ]
    (parent / "INDEX.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def write_failure_marker(folder: Path, message: str) -> None:
    if not folder.exists():
        return
    marker = (
        "# Weekly ideas pipeline failed\n\n"
        f"- Time: {datetime.now(timezone.utc).isoformat()}\n"
        f"- Error: {message}\n\n"
        "`summary.md` was not regenerated. Fix or rerun extraction; do not treat prior generated output as current success.\n"
    )
    (folder / "PIPELINE_FAILED.md").write_text(marker, encoding="utf-8")
