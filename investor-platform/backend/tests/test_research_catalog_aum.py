"""Keep reviewed manager lower bounds distinct from securities portfolio values."""

import json
from datetime import date
from pathlib import Path

import pytest

from investor_platform.research_eligibility import manager_eligibility

CATALOG: Path = Path(__file__).parents[1] / "src" / "investor_platform" / "research_managers.json"


@pytest.mark.parametrize(
    ("slug", "amount", "disclosed", "crd", "attribution"),
    [
        ("berkshire", "111718023582", "2026-03-31", "105900", "NEAM client AUM"),
        ("tci", "70281928000", "2026-06-29", "269954", "gross asset value"),
    ],
)
def test_reviewed_catalog_lower_bounds_qualify(
    slug: str, amount: str, disclosed: str, crd: str, attribution: str
) -> None:
    """Named sources establish eligibility without claiming complete manager AUM."""
    records: list[dict] = json.loads(CATALOG.read_text())
    profile: dict = next(record for record in records if record["slug"] == slug)
    assert profile["aum_usd"] == amount
    assert profile["aum_as_of"] == disclosed
    assert profile["aum_measurement"] == "verified_lower_bound"
    assert profile["aum_source_url"] == (
        f"https://reports.adviserinfo.sec.gov/reports/ADV/{crd}/PDF/{crd}.pdf"
    )
    assert attribution in profile["notes"]
    assert manager_eligibility(profile, date(2026, 10, 14))["status"] == "eligible"
