"""JSON boundaries and content identities for financial evidence."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

type Json = str | int | float | bool | None | list[Json] | dict[str, Json]


type Record = dict[str, Json]


type Value = Json | Decimal | date | datetime | UUID


type Row = dict[str, Value]


def record(value: Json) -> Record:
    """Require a JSON object before accessing its fields."""
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object; use the annual financial bundle schema")
    return value


def records(value: Json) -> list[Record]:
    """Read an array of JSON objects."""
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array; use the annual financial bundle schema")
    return [record(item) for item in value]


def digest(bundle: Record) -> str:
    """Identify exact bundle content independent of JSON key order or whitespace."""
    return hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()


def unique_object(pairs: list[tuple[str, Json]]) -> Record:
    """Reject duplicate JSON keys instead of silently discarding evidence components."""
    result: Record = {}
    key: str
    value: Json
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key}; retain each component only once")
        result[key] = value
    return result
