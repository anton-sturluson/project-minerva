"""Shared decimal, weighted-mean and comparison arithmetic without reporting policy."""

import re
from decimal import Decimal
from typing import Literal

from investor_platform.financials.types import Json


def decimal_string(value: Json) -> Decimal:
    """Read a finite unformatted decimal string without binary-float conversion."""
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        raise ValueError("Use an unformatted finite decimal string")
    return Decimal(value)


def weighted_mean(
    values: dict[str, Decimal], weights: dict[str, Decimal], *, complete: bool
) -> tuple[Decimal | None, Decimal]:
    """Normalize each measure by its covered positive weights using the caller's precision."""
    covered: Decimal = sum((weights.get(key, Decimal(0)) for key in values), Decimal(0))
    numerator: Decimal = sum(
        (value * weights.get(key, Decimal(0)) for key, value in values.items()), Decimal(0)
    )
    return (numerator / covered if complete and covered > 0 else None), covered


def comparison_values(
    current: Decimal | None, prior: Decimal | None
) -> tuple[Literal["unavailable", "not_meaningful", "calculated"], Decimal | None]:
    """Require both values and a positive prior amount before calculating a growth rate."""
    if current is None or prior is None:
        return "unavailable", None
    if prior <= 0:
        return "not_meaningful", None
    return "calculated", current / prior - 1
