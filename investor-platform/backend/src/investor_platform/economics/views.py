"""Small, explicit chart calculations from accepted publisher observations."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from investor_platform.economics.registry import SERIES, Series
from investor_platform.models import EconomicObservation


@dataclass(frozen=True)
class Point:
    """One displayed point with accepted source IDs and its calculation lineage."""

    date: date
    value: Decimal | None
    source_url: str
    collected_at: datetime
    sha256: str
    footnotes: list[dict[str, str]] = field(default_factory=list)
    derived_from: list[dict] = field(default_factory=list)
    provisional: bool = False


def month_before(day: date, months: int) -> date:
    """Find a comparison calendar month without relying on row positions."""
    index: int = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def reference(row: EconomicObservation, transform: str) -> dict:
    """Retain the exact accepted revision and payload that supplied a calculation."""
    return {
        "observation_id": row.id,
        "series_key": row.series_key,
        "date": row.observation_date.isoformat(),
        "value": str(row.value) if row.value is not None else None,
        "sha256": row.provenance["sha256"],
        "source_url": row.provenance["source_url"],
        "transform": transform,
    }


def points_for(definition: Series, rows: list[EconomicObservation]) -> list[Point]:
    """Apply only the approved year-change, payroll-change and quarterly ratio formulas."""
    primary: str = definition.inputs[0] if definition.inputs else definition.key
    source: list[EconomicObservation] = sorted(
        [row for row in rows if row.series_key == primary], key=lambda row: row.observation_date
    )
    indexed: dict[tuple[str, date], EconomicObservation] = {
        (row.series_key, row.observation_date.replace(day=1)): row for row in rows
    }
    quarters: dict[tuple[str, int, int], EconomicObservation] = {
        (row.series_key, row.observation_date.year, (row.observation_date.month - 1) // 3): row
        for row in rows
        if row.series_key in definition.inputs
    }
    source_start: date | None = source[0].observation_date.replace(day=1) if source else None
    labels: dict[str, str] = {series.key: series.name for series in SERIES}
    result: list[Point] = []
    row: EconomicObservation
    for row in source:
        day: date = row.observation_date
        inputs: list[EconomicObservation | None] = [row]
        required: list[tuple[str, date]] = [(primary, day)]
        value: Decimal | None = row.value
        notes: list[dict[str, str]] = list(row.provenance["footnotes"])
        refs: list[dict] = list(row.provenance["derived_from"])
        if definition.transform in {"yoy", "change", "change_3m"}:
            offsets: tuple[int, ...] = {"yoy": (12,), "change": (1,), "change_3m": (1, 2, 3)}[
                definition.transform
            ]
            comparisons: list[date] = [month_before(day, offset) for offset in offsets]
            # A growth series begins only when its comparison history can exist. An absent
            # month inside that history is a genuine gap and must remain visible.
            if source_start is not None and any(period < source_start for period in comparisons):
                continue
            required += [(primary, period) for period in comparisons]
            inputs += [indexed.get((primary, period)) for period in comparisons]
        elif definition.transform == "equity_gdp":
            required.append((definition.inputs[1], date(day.year, (day.month - 1) // 3 * 3 + 1, 1)))
            inputs.append(quarters.get((definition.inputs[1], day.year, (day.month - 1) // 3)))
        elif definition.transform:
            raise ValueError("Unsupported economics calculation")
        if definition.transform:
            refs = [reference(item, definition.transform) for item in inputs if item is not None]
            if any(item is None or item.value is None for item in inputs):
                value = None
                key: str
                period: date
                item: EconomicObservation | None
                for (key, period), item in zip(required, inputs, strict=True):
                    if item is None or item.value is None:
                        notes.append(
                            {
                                "code": "missing_input" if item is None else "source_missing",
                                "text": f"{labels[key]} is unavailable for {period:%Y-%m}. "
                                "The calculation requires this exact period.",
                            }
                        )
                        if item is not None:
                            notes += [
                                note for note in item.provenance["footnotes"] if note not in notes
                            ]

            else:
                values: list[Decimal] = [
                    item.value for item in inputs if item is not None and item.value is not None
                ]
                if definition.transform in {"yoy", "equity_gdp"} and values[1] <= 0:
                    value = None
                    notes.append(
                        {
                            "code": "invalid_denominator",
                            "text": "The comparison denominator must be positive.",
                        }
                    )
                elif definition.transform == "yoy":
                    value = (values[0] / values[1] - 1) * 100
                elif definition.transform == "change":
                    value = values[0] - values[1]
                elif definition.transform == "change_3m":
                    value = (values[0] - values[3]) / 3
                elif definition.transform == "equity_gdp":
                    value = 100 * values[0] / (1000 * values[1])
        accepted: list[EconomicObservation] = [item for item in inputs if item is not None]
        result.append(
            Point(
                day,
                value,
                definition.source_url,
                max(item.collected_at for item in accepted),
                row.provenance["sha256"],
                notes,
                refs,
                any(
                    note.get("code") == "provisional"
                    for item in accepted
                    for note in item.provenance["footnotes"]
                ),
            )
        )
    return result


def point_view(point: Point) -> dict:
    """Serialize exact values and the dates used for the displayed measurement."""
    return {
        "date": point.date.isoformat(),
        "value": str(point.value) if point.value is not None else None,
        "missing": point.value is None,
        "source_url": point.source_url,
        "footnotes": point.footnotes,
        "derived_from": point.derived_from,
        "collected_at": point.collected_at,
        "sha256": point.sha256,
        "provisional": point.provisional,
    }
