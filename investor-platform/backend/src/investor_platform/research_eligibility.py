"""Apply the manager AUM minimum to reviewed official evidence, never 13F holdings value."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, TypedDict
from urllib.parse import SplitResult, urlsplit

MINIMUM_AUM_USD: Decimal = Decimal("50000000")
AUM_MEASUREMENTS: frozenset[str] = frozenset(
    {
        "regulatory_aum",
        "firm_aum",
        "verified_lower_bound",
    }
)


class Eligibility(TypedDict):
    """Tracking status and the single disclosed minimum."""

    status: Literal["eligible", "below_minimum", "unverified"]
    minimum_aum_usd: str
    reason: str | None


def manager_eligibility(profile: dict, today: date) -> Eligibility:
    """Check sourced USD AUM evidence without substituting a reported stock portfolio."""
    result: Eligibility = {
        "status": "unverified",
        "minimum_aum_usd": str(MINIMUM_AUM_USD),
        "reason": "Official AUM amount, measurement, date and source must be verified",
    }
    raw_amount: str | None = profile.get("aum_usd")
    raw_date: str | None = profile.get("aum_as_of")
    raw_source: str | None = profile.get("aum_source_url")
    measurement: str | None = profile.get("aum_measurement")
    if (
        not isinstance(raw_amount, str)
        or not isinstance(raw_date, str)
        or not isinstance(raw_source, str)
        or not isinstance(measurement, str)
        or measurement not in AUM_MEASUREMENTS
    ):
        return result
    try:
        amount: Decimal = Decimal(raw_amount)
        as_of: date = date.fromisoformat(raw_date)
        source: SplitResult = urlsplit(raw_source)
        if (
            not amount.is_finite()
            or amount < 0
            or as_of > today
            or as_of.isoformat() != raw_date
            or source.scheme != "https"
            or not source.hostname
            or source.username
            or source.password
            or source.port not in (None, 443)
            or "\\" in raw_source
            or any(character.isspace() for character in raw_source)
        ):
            return result
    except (InvalidOperation, ValueError):
        return result
    if amount < MINIMUM_AUM_USD and measurement == "verified_lower_bound":
        result["reason"] = "Verified AUM lower bound does not establish the minimum"
    elif amount < MINIMUM_AUM_USD:
        result["status"] = "below_minimum"
        result["reason"] = f"Reported AUM is below the ${MINIMUM_AUM_USD:,.0f} minimum"
    else:
        result["status"] = "eligible"
        result["reason"] = None
    return result
