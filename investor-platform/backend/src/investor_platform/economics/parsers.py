"""Strict parsers for the three verified public publisher formats."""

import calendar
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import cast

import openpyxl
import xlrd
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from investor_platform.economics.registry import SERIES, Series


@dataclass(frozen=True)
class Fact:
    """One validated observation before database admission."""

    series_key: str
    date: date
    value: Decimal | None
    locator: str
    footnotes: list[dict[str, str]] = field(default_factory=list)
    derived_from: list[dict[str, str]] = field(default_factory=list)


def number(value: str | float | int | None) -> Decimal | None:
    """Preserve missing markers and reject invalid or nonfinite prices."""
    if value is None or str(value).strip() in {"", "-", "NA", "N/A"}:
        return None
    result: Decimal = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid economics price")
    return result


def validate(facts: list[Fact]) -> list[Fact]:
    """Reject empty results and duplicate measurement dates."""
    seen: set[tuple[str, date]] = set()
    fact: Fact
    for fact in facts:
        key: tuple[str, date] = (fact.series_key, fact.date)
        if key in seen:
            raise ValueError("Duplicate observation date")
        seen.add(key)
    if not facts:
        raise ValueError("No observations in publisher response")
    return sorted(facts, key=lambda row: (row.series_key, row.date))


def parse_bls(payload: bytes) -> list[Fact]:
    """Read exact food IDs, dates, decimals and missing-value footnotes."""
    data: dict = json.loads(payload)
    expected: dict[str, str] = {s.source_key: s.key for s in SERIES if s.source_id == "bls"}
    if data.get("status") != "REQUEST_SUCCEEDED" or data.get("message"):
        raise ValueError("BLS request failed or returned a warning")
    facts: list[Fact] = []
    found: set[str] = set()
    series: dict
    for series in data["Results"]["series"]:
        identity: str = series["seriesID"]
        if identity not in expected:
            continue
        if identity in found:
            raise ValueError("Duplicate BLS series")
        found.add(identity)
        monthly_count: int = 0
        row: dict
        for row in series["data"]:
            period: str = row["period"]
            if period == "M13":
                continue
            if period not in {f"M{month:02}" for month in range(1, 13)}:
                raise ValueError("Invalid BLS monthly period")
            monthly_count += 1
            facts.append(
                Fact(
                    expected[identity],
                    date(int(row["year"]), int(period[1:]), 1),
                    number(row["value"]),
                    identity,
                    [note for note in row.get("footnotes", []) if note],
                )
            )
        if monthly_count == 0:
            raise ValueError("BLS series contains no monthly observations")
    if found != set(expected):
        raise ValueError("Missing requested BLS series")
    return validate(facts)


def parse_usda(payload: bytes) -> list[Fact]:
    """Build a fixed family from exactly four individual weekly costs."""
    workbook: openpyxl.Workbook = openpyxl.load_workbook(
        io.BytesIO(payload), read_only=True, data_only=True
    )
    try:
        sheet: ReadOnlyWorksheet = cast(ReadOnlyWorksheet, workbook["Moderate-Cost 07-Pres"])
        sheet.reset_dimensions()
        rows: Iterator[tuple[str | float | int | None, ...]] = sheet.iter_rows(values_only=True)
        headers: tuple[str, ...] = tuple(next(rows))
        required: set[str] = {
            "geographic_area",
            "fam_indv",
            "group",
            "age",
            "year",
            "month",
            "food_plan",
            "frequency",
            "cost",
        }
        if set(headers) != required:
            raise ValueError("USDA workbook columns changed")
        months: dict[str, int] = {
            name: index for index, name in enumerate(calendar.month_name) if index
        }
        components: dict[date, dict[str, Decimal]] = {}
        targets: set[tuple[str, str]] = {
            ("Male", "19-50 years"),
            ("Female", "19-50 years"),
            ("Child", "6-8 years"),
            ("Child", "9-11 years"),
        }
        values: tuple[str | float | int | None, ...]
        for values in rows:
            row: dict = dict(zip(headers, values, strict=True))
            if row["frequency"] != "Weekly" or row["geographic_area"] != "Mainland U.S.":
                continue
            if str(row["food_plan"]).lower().replace(" ", "-") != "moderate-cost":
                raise ValueError("Unexpected USDA plan")
            day: date = date(int(row["year"]), months[row["month"]], 1)
            value: Decimal | None = number(row["cost"])
            if value is None:
                raise ValueError("Missing USDA family component")
            group: tuple[str, str] = (row["group"], row["age"])
            if row["fam_indv"] == "Individual" and group in targets:
                key: str = ":".join(group)
                bucket: dict[str, Decimal] = components.setdefault(day, {})
                if key in bucket:
                    raise ValueError("Duplicate USDA family component")
                bucket[key] = value
        facts: list[Fact] = []
        for day in sorted(components):
            parts: dict[str, Decimal] = components.get(day, {})
            if len(parts) == 4:
                refs: list[dict[str, str]] = [
                    {"component": key, "value": str(value), "formula": "sum"}
                    for key, value in sorted(parts.items())
                ]
                facts.append(
                    Fact(
                        "family-groceries",
                        day,
                        sum(parts.values(), Decimal(0)),
                        "Moderate-Cost 07-Pres",
                        derived_from=refs,
                    )
                )
            else:
                raise ValueError("Incomplete USDA family composition")
        return validate(facts)
    finally:
        workbook.close()


def parse_eia(payload: bytes, key: str) -> list[Fact]:
    """Validate workbook identity and preserve actual weekly survey dates."""
    definition: Series = next(s for s in SERIES if s.key == key and s.source_id == "eia")
    workbook: xlrd.Book = xlrd.open_workbook(file_contents=payload)
    sheet: xlrd.sheet.Sheet = workbook.sheet_by_name("Data 1")
    if (
        sheet.cell_value(1, 0) != "Sourcekey"
        or sheet.cell_value(1, 1) != definition.source_key
        or sheet.cell_value(2, 0) != "Date"
        or "Dollars per Gallon" not in str(sheet.cell_value(2, 1))
    ):
        raise ValueError("EIA workbook identity or units changed")
    facts: list[Fact] = []
    index: int
    for index in range(3, sheet.nrows):
        if sheet.cell_value(index, 0) == "":
            continue
        day: date = xlrd.xldate_as_datetime(sheet.cell_value(index, 0), workbook.datemode).date()
        value: Decimal | None = number(sheet.cell_value(index, 1))
        facts.append(Fact(key, day, value, definition.source_key))
    return validate(facts)
