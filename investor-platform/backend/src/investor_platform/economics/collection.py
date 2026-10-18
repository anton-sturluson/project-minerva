"""Bounded public-source collection with durable scheduling and immutable raw files."""

import argparse
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from urllib.request import Request, urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE, make_engine
from investor_platform.economics.macro import (
    BEA_SECTION1,
    BEA_SECTION2,
    FED_EQUITY_URL,
    FED_H15_URL,
    FED_TARGET_URL,
    FREDDIE_URL,
    SHILLER_URL,
    parse_bea,
    parse_fed_equity,
    parse_fed_h15,
    parse_fed_targets,
    parse_freddie,
    parse_shiller,
    shiller_workbook_url,
)
from investor_platform.economics.parsers import Fact, parse_bls, parse_eia, parse_usda, validate
from investor_platform.economics.registry import BLS_URL, SERIES, SOURCES, USDA_URL
from investor_platform.models import EconomicObservation, EconomicRefreshState

LOGGER: logging.Logger = logging.getLogger(__name__)
PARSER_VERSION: str = "1"
MAX_BYTES: int = 16 * 1024 * 1024


@dataclass(frozen=True)
class Payload:
    """Validated source bytes and their exact retrieval location."""

    url: str
    body: bytes
    facts: list[Fact]
    imported: bool = False


def next_regular(provider: str, now: datetime) -> datetime:
    """Choose our next check time, independent of the publisher's release cadence."""
    local: datetime = now.astimezone(ZoneInfo("America/New_York"))
    hour: int
    minute: int
    hour, minute = {
        "bls": (9, 0),
        "bls-macro": (9, 0),
        "usda": (14, 0),
        "eia": (10, 30),
        "bea": (10, 0),
        "fed": (17, 0),
        "fed-equity": (17, 0),
        "freddie": (13, 0),
        "shiller": (14, 0),
    }[provider]
    candidate: datetime = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    allowed_days: set[int] = {
        "eia": {1, 2},
        "freddie": {2, 3},
        "shiller": {0},
        "fed-equity": {0},
    }.get(provider, set(range(5)))
    while candidate.weekday() not in allowed_days:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def download(url: str, body: bytes | None = None) -> bytes:
    """Fetch only fixed public publisher URLs with bounded time and response size."""
    request: Request = Request(
        url,
        data=body,
        headers={
            "User-Agent": "Minerva economic research (public data)",
            "Content-Type": "application/json" if body is not None else "application/octet-stream",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload: bytes = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Publisher payload exceeds supported size")
    return payload


def bls_macro_windows(year: int, *, full_history: bool) -> list[tuple[int, int, dict[str, str]]]:
    """Plan nonoverlapping ten-year API windows within each native series' real coverage."""
    starts: dict[str, int] = {
        series.source_key: series.history_start_year
        for series in SERIES
        if series.source_id == "bls-macro"
        and not series.transform
        and series.history_start_year is not None
    }
    keys: dict[str, str] = {
        series.source_key: series.key
        for series in SERIES
        if series.source_id == "bls-macro" and not series.transform
    }
    if not full_history:
        return [(year - 6, year, keys)]
    boundaries: list[int] = sorted({*starts.values(), year + 1})
    windows: list[tuple[int, int, dict[str, str]]] = []
    first: int
    last: int
    for first, last in zip(boundaries, boundaries[1:]):
        identities: dict[str, str] = {
            native: keys[native]
            for native, history_start in starts.items()
            if history_start <= first
        }
        windows += [
            (start, min(start + 9, last - 1), identities) for start in range(first, last, 10)
        ]
    return windows


def collect_payloads(
    provider: str,
    now: datetime,
    *,
    initial: bool,
    import_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> list[Payload]:
    """Collect the three concrete supported formats; offline import uses the same parsers."""

    def read(name: str, url: str, body: bytes | None = None) -> bytes:
        """Use an explicitly selected local source snapshot or a fresh publisher request."""
        return (import_dir / name).read_bytes() if import_dir else download(url, body)

    if provider in {"bls", "bls-macro"}:
        expected: dict[str, str] = {
            series.source_key: series.key
            for series in SERIES
            if series.source_id == provider and not series.transform
        }
        if import_dir is not None:
            body: bytes = read(
                "bls-macro.json" if provider == "bls-macro" else "bls-api-2025-2026.json", BLS_URL
            )
            return [Payload(BLS_URL, body, parse_bls(body, expected), imported=True)]
        windows: list[tuple[int, int, dict[str, str]]] = (
            bls_macro_windows(now.year, full_history=initial)
            if provider == "bls-macro"
            else [(now.year - (6 if initial else 1), now.year, expected)]
        )
        payloads: list[Payload] = []
        start: int
        end: int
        for start, end, expected in windows:
            request: bytes = json.dumps(
                {"seriesid": list(expected), "startyear": str(start), "endyear": str(end)}
            ).encode()
            body = download(BLS_URL, request)
            facts: list[Fact] = parse_bls(body, expected)
            # Keep successful windows even if a later request reaches the publisher's quota.
            if raw_dir is not None:
                save_raw(body, raw_dir)
            payloads.append(Payload(BLS_URL, body, facts))
        return payloads
    if provider == "usda":
        body = read("usda-moderate-cost.xlsx", USDA_URL)
        return [Payload(USDA_URL, body, parse_usda(body), imported=import_dir is not None)]
    if provider == "eia":
        payloads: list[Payload] = []
        key: str
        for key in ("gasoline", "diesel"):
            url: str = next(s.source_url for s in SERIES if s.key == key)
            body = read(f"eia-{key}-weekly.xls", url)
            payloads.append(
                Payload(url, body, parse_eia(body, key), imported=import_dir is not None)
            )
        return payloads
    if provider == "bea":
        payloads = []
        section: int
        for section, url in ((1, BEA_SECTION1), (2, BEA_SECTION2)):
            body = read(f"bea-section{section}.xlsx", url)
            payloads.append(
                Payload(url, body, parse_bea(body, section), imported=import_dir is not None)
            )
        return payloads
    if provider == "fed":
        target_body: bytes = read("fed-target.csv", FED_TARGET_URL)
        yield_body: bytes = read("fed-h15.csv", FED_H15_URL)
        return [
            Payload(
                FED_TARGET_URL,
                target_body,
                parse_fed_targets(target_body),
                imported=import_dir is not None,
            ),
            Payload(
                FED_H15_URL, yield_body, parse_fed_h15(yield_body), imported=import_dir is not None
            ),
        ]
    if provider == "fed-equity":
        body = read("fed-z1-tables.zip", FED_EQUITY_URL)
        return [
            Payload(FED_EQUITY_URL, body, parse_fed_equity(body), imported=import_dir is not None)
        ]
    if provider == "freddie":
        body = read("freddie-history.xlsx", FREDDIE_URL)
        return [Payload(FREDDIE_URL, body, parse_freddie(body), imported=import_dir is not None)]
    if provider == "shiller":
        url = SHILLER_URL if import_dir else shiller_workbook_url(download(SHILLER_URL))
        body = read("shiller-current.xls", url)
        return [Payload(url, body, parse_shiller(body), imported=import_dir is not None)]
    raise ValueError("Unsupported economics publisher")


def save_raw(body: bytes, directory: Path) -> str:
    """Keep immutable content-addressed evidence outside the relational database."""
    digest: str = hashlib.sha256(body).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target: Path = directory / digest
    try:
        with target.open("xb") as handle:
            handle.write(body)
    except FileExistsError:
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Raw economics evidence hash mismatch") from None
    return digest


def admit(
    session: Session, workspace: UUID, payloads: list[Payload], now: datetime, raw_dir: Path
) -> int:
    """Append only changed facts; byte changes alone do not create redundant observations."""
    validate([fact for payload in payloads for fact in payload.facts])
    count: int = 0
    payload: Payload
    for payload in payloads:
        digest: str = save_raw(payload.body, raw_dir)
        keys: set[str] = {fact.series_key for fact in payload.facts}
        stored: list[EconomicObservation] = list(
            session.scalars(
                select(EconomicObservation)
                .where(
                    EconomicObservation.workspace_id == workspace,
                    EconomicObservation.series_key.in_(keys),
                )
                .order_by(EconomicObservation.id)
            )
        )
        latest: dict[tuple[str, date], EconomicObservation] = {
            (row.series_key, row.observation_date): row for row in stored
        }
        fact: Fact
        for fact in payload.facts:
            old: EconomicObservation | None = latest.get((fact.series_key, fact.date))
            provenance: dict = {
                "sha256": digest,
                "parser_version": PARSER_VERSION,
                "acquisition": "imported" if payload.imported else "publisher",
                "source_url": payload.url,
                "locator": fact.locator,
                "footnotes": fact.footnotes,
                "derived_from": fact.derived_from,
            }
            if (
                old is not None
                and old.value == fact.value
                and old.provenance.get("footnotes") == fact.footnotes
                and old.provenance.get("derived_from") == fact.derived_from
            ):
                continue
            session.add(
                EconomicObservation(
                    workspace_id=workspace,
                    series_key=fact.series_key,
                    observation_date=fact.date,
                    value=fact.value,
                    missing=fact.value is None,
                    provenance=provenance,
                    collected_at=now,
                )
            )
            count += 1
    return count


def refresh(
    engine: Engine,
    provider: str,
    *,
    workspace: UUID = LOCAL_WORKSPACE,
    now: datetime | None = None,
    force: bool = False,
    import_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> str:
    """Hold one session advisory lock across attempt, network I/O and atomic fact admission."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if provider not in {source.id for source in SOURCES if source.enabled}:
        raise ValueError("Publisher is not enabled")
    raw_dir = raw_dir or Path(os.environ.get("ECONOMICS_RAW_DIR", "data/economics"))
    lock: int = int.from_bytes(
        hashlib.sha256(f"economics:{workspace}:{provider}".encode()).digest()[:8], signed=True
    )
    with engine.connect() as connection:
        locked: bool = bool(
            connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock})
        )
        connection.commit()
        if not locked:
            return "running"
        try:
            with Session(connection) as session:
                state: EconomicRefreshState | None = session.get(
                    EconomicRefreshState, (workspace, provider)
                )
                if state is not None and state.next_due > now and not force:
                    return state.status
                if state is None:
                    state = EconomicRefreshState(
                        workspace_id=workspace,
                        provider=provider,
                        next_due=now,
                        status="not_run",
                        failures=0,
                    )
                    session.add(state)
                initial: bool = state.last_success is None
                if import_dir is not None and not initial:
                    raise ValueError("Saved snapshots may only initialize an uncollected publisher")
                if provider == "bls-macro":
                    coverage: dict[str, date] = dict(
                        session.execute(
                            select(
                                EconomicObservation.series_key,
                                func.min(EconomicObservation.observation_date),
                            )
                            .where(EconomicObservation.workspace_id == workspace)
                            .group_by(EconomicObservation.series_key)
                        ).all()
                    )
                    initial = initial or any(
                        series.key not in coverage
                        or coverage[series.key].year > series.history_start_year
                        for series in SERIES
                        if series.source_id == "bls-macro"
                        and not series.transform
                        and series.history_start_year is not None
                    )
                if state.last_attempt is None or state.last_attempt.date() != now.date():
                    state.failures = 0
                state.last_attempt = now
                # Count an attempt before I/O so repeated crashes also consume the daily budget.
                state.failures += 1
                state.status = "running"
                # Recover after a crash; a restarted worker never leaves this due forever.
                state.next_due = (
                    now + timedelta(minutes=30 * state.failures)
                    if state.failures < 3
                    else next_regular(provider, now)
                )
                session.commit()
                try:
                    payloads: list[Payload] = collect_payloads(
                        provider, now, initial=initial, import_dir=import_dir, raw_dir=raw_dir
                    )
                    admit(session, workspace, payloads, now, raw_dir)
                    state.last_success = now
                    state.status = "imported" if import_dir is not None else "complete"
                    state.error = None
                    state.failures = 0
                    state.next_due = next_regular(provider, now)
                    session.commit()
                except Exception as error:
                    session.rollback()
                    state = session.get(EconomicRefreshState, (workspace, provider))
                    assert state is not None
                    state.status = "failed"
                    # URLs, paths and response bodies can contain private data; expose none.
                    state.error = "Collection or validation failed; last good data retained."
                    state.next_due = (
                        now + timedelta(minutes=30 * state.failures)
                        if state.failures < 3
                        else next_regular(provider, now)
                    )
                    session.commit()
                    LOGGER.warning(
                        "Economics %s collection failed (%s)", provider, type(error).__name__
                    )
                return state.status
        finally:
            connection.rollback()
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock})
            connection.commit()


def run_worker(engine: Engine, stop: Event) -> None:
    """Check three persisted due times; interruptible waiting lets the API shut down."""
    while not stop.is_set():
        source: str
        for source in (item.id for item in SOURCES if item.enabled):
            if stop.is_set():
                return
            try:
                refresh(engine, source)
            except Exception:
                LOGGER.warning("Economics scheduler could not access refresh state")
        stop.wait(60)


def main() -> None:
    """Collect one or all supported sources into the explicitly configured database."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=["all"] + [source.id for source in SOURCES if source.enabled],
        default="all",
    )
    parser.add_argument("--import-dir", type=Path)
    parser.add_argument("--force", action="store_true")
    args: argparse.Namespace = parser.parse_args()
    engine: Engine = make_engine()
    try:
        providers: list[str] = (
            [source.id for source in SOURCES if source.enabled]
            if args.provider == "all"
            else [args.provider]
        )
        results: dict[str, str] = {
            provider: refresh(engine, provider, force=args.force, import_dir=args.import_dir)
            for provider in providers
        }
        print(json.dumps(results))
        if any(status == "failed" for status in results.values()):
            raise SystemExit(1)
    finally:
        engine.dispose()
