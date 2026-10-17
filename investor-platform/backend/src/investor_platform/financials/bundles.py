"""Validate annual source bundles and disclosed capital-spending components."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker

from investor_platform.financials.types import Json, Record, record, records, unique_object

SCHEMA: Path = Path(__file__).with_name("annual_financial_bundle.schema.json")


def validate_capital_spending(bundle: Record) -> None:
    """Require compatible reported components with resolved sources and no duplicated subtotal."""
    if bundle.get("capital_spending") is None:
        return
    spending: Record = record(bundle["capital_spending"])
    schema: Record = cast(Record, json.loads(SCHEMA.read_text()))
    Draft202012Validator(
        {"$ref": "#/$defs/capital_spending", "$defs": schema["$defs"]},
        format_checker=FormatChecker(),
    ).validate(spending)
    components: Record = record(spending["components"])
    keys: set[str] = set(components)
    if (
        "property_equipment_software" in keys
        and len(keys) > 1
        or (
            "ppe" in keys
            and keys & {"equipment", "leasehold_improvements", "other_capital_investments"}
        )
    ):
        raise ValueError("Capital spending subtotal overlaps components; select disjoint cash rows")
    sources: dict[str, Record] = {str(s["source_id"]): s for s in records(bundle["sources"])}
    locations: set[tuple[str, str, str, str, str]] = set()
    tags: set[tuple[str, str, str]] = set()
    key: str
    raw: Json
    for key, raw in components.items():
        fact: Record = record(raw)
        source: Record | None = sources.get(str(fact["source_id"]))
        if source is None:
            raise ValueError(
                f"Unresolved capital spending source for {key}; add its document source"
            )
        locator: Record = record(fact["locator"])
        location: tuple[str, str, str, str, str] = (
            str(source["document_id"]),
            str(source["content_sha256"]),
            str(locator["statement"]).strip().casefold(),
            str(locator["row"]).strip().casefold(),
            str(locator["column"]).strip().casefold(),
        )
        tag: tuple[str, str, str] = (
            str(source["document_id"]),
            str(source["content_sha256"]),
            str(locator.get("xbrl_tag", "")).strip().casefold(),
        )
        if location in locations or tag[2] and tag in tags:
            raise ValueError(
                "Duplicate capital spending source locator/tag; do not count a cash row twice"
            )
        locations.add(location)
        if tag[2]:
            tags.add(tag)


def validate(path: Path, source_dir: Path | None = None) -> Record:
    """Check structure, semantic boundaries and original downloaded document hashes."""
    bundle: Record = record(
        cast(Json, json.loads(path.read_text(), object_pairs_hook=unique_object))
    )
    schema: Record = record(cast(Json, json.loads(SCHEMA.read_text())))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(bundle)
    period: Record = record(bundle["period"])
    start: date = date.fromisoformat(str(period["start"]))
    end: date = date.fromisoformat(str(period["end"]))
    if not 350 <= (end - start).days + 1 <= 380:
        raise ValueError(
            "Unsupported annual dates; supply a full year. "
            "Transition periods need an explicit policy"
        )
    sources: list[Record] = records(bundle["sources"])
    by_id: dict[str, Record] = {str(source["source_id"]): source for source in sources}
    if len(by_id) != len(sources):
        raise ValueError("Duplicate source IDs; give each document version a unique source ID")
    hashes: set[str] = set()
    folder: Path = (source_dir or path.parent).resolve()
    file: Path
    for file in folder.rglob("*"):
        if file.is_file() and not file.is_symlink():
            hashes.add(hashlib.sha256(file.read_bytes()).hexdigest())
    source: Record
    for source in sources:
        published: date = date.fromisoformat(str(source["published_on"]))
        retrieved: datetime = datetime.fromisoformat(
            str(source["retrieved_at"]).replace("Z", "+00:00")
        )
        if published < end or retrieved.date() < published:
            raise ValueError(
                "Invalid source chronology; use the document's actual publication date"
            )
        if source["content_sha256"] not in hashes:
            raise ValueError(
                "Source bytes missing or hash differs; save original bytes in --source-dir"
            )
    key: str
    raw: Json
    for key, raw in record(bundle["facts"]).items():
        fact: Record = record(raw)
        sid: str = str(fact.get("source_id", ""))
        if sid and sid not in by_id:
            raise ValueError(f"Unresolved source for {key}; reference a source in this bundle")
        if fact["status"] in {"not_disclosed", "not_applicable"} and not sid:
            raise ValueError(f"Missing absence evidence for {key}; add a source and locator")
        if "share_basis" in fact:
            basis: Record = record(fact["share_basis"])
            if not sid or str(basis["split_adjusted_through"]) > str(by_id[sid]["published_on"]):
                raise ValueError(
                    f"Unsupported split basis for {key}; use the source's reported basis"
                )
    validate_capital_spending(bundle)
    return bundle
