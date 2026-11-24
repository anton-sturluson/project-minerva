"""Check the source dimensions that materially change the issuance charts."""

from pathlib import Path

import pytest
from official_comparison import Observation, amount, read_bis

CSV_SAMPLE: str = (
    "FREQ,ISSUER_RES,ISSUER_NAT,ISSUER_BUS_IMM,ISSUER_BUS_ULT,MARKET,ISSUE_TYPE,"
    "ISSUE_CUR_GROUP,ISSUE_CUR,ISSUE_OR_MAT,ISSUE_RE_MAT,ISSUE_RATE,ISSUE_RISK,"
    "ISSUE_COL,MEASURE,UNIT_MEASURE,UNIT_MULT,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "Q,3P,US,1,J,C,A,A,TO1,A,A,A,A,A,G,USD,6,2020-Q4,-15710,A\n"
)


def test_negative_net_issuance_is_preserved(tmp_path: Path) -> None:
    """Redemptions above issuance must remain a negative value, not a missing value."""
    source: Path = tmp_path / "source.csv"
    source.write_text(CSV_SAMPLE)
    observations: list[Observation] = read_bis(source, "nationality")
    assert observations[0].period == "2020-Q4"
    assert observations[0].value_usd_millions == "-15710"


@pytest.mark.parametrize(
    "changed", [CSV_SAMPLE.replace(",USD,6,", ",USD,9,"), CSV_SAMPLE.replace(",1,J,C,", ",1,1,C,")]
)
def test_changed_units_or_sector_are_rejected(tmp_path: Path, changed: str) -> None:
    """A valid but different BIS series must not silently enter the selected chart."""
    source: Path = tmp_path / "source.csv"
    source.write_text(changed)
    with pytest.raises(ValueError, match="dimensions or USD units"):
        read_bis(source, "nationality")


def test_duplicate_period_is_rejected(tmp_path: Path) -> None:
    """Repeated observations must not become repeated chart points."""
    source: Path = tmp_path / "source.csv"
    source.write_text(CSV_SAMPLE + CSV_SAMPLE.splitlines()[-1] + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        read_bis(source, "nationality")


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity"])
def test_invalid_values_cannot_become_zero(value: object) -> None:
    """Keep missing or invalid observations distinct from a measured zero."""
    with pytest.raises(ValueError):
        amount(value)
