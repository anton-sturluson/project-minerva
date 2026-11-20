"""Check the source-table boundaries that affect SPGI amount interpretation."""

import pytest
from spgi import extract


def table(labels: list[str], unit: str, *, mix: bool = False) -> str:
    """Build a synthetic quarter-versus-YTD table with separate currency cells."""
    rows: list[str] = [
        f"<tr><td>{label}</td><td>$</td><td>{index + 11}</td><td>$</td>"
        f"<td>{index + 7}</td><td>10%</td><td>999</td><td>888</td></tr>"
        for index, label in enumerate(labels)
    ]
    if mix:
        rows.append("<tr><td>% of total revenue:</td></tr>")
        rows.append(
            "<tr><td>Transaction revenue</td><td>55</td><td>%</td><td>54</td><td>%</td></tr>"
        )
    header: str = f"<table><tr><td>(in {unit}) Three Months Six Months 2026 2025</td></tr>"
    return header + "".join(rows) + "</table>"


def filing() -> str:
    """Use distinct current/prior amounts and deliberately unrelated YTD amounts."""
    return table(
        [
            "Investment-grade billed issuance*",
            "High-yield billed issuance *",
            "Other billed issuance **",
            "Total billed issuance",
        ],
        "billions",
    ) + table(["Transaction revenue", "Non-transaction revenue"], "millions", mix=True)


def test_quarter_columns_and_reported_total_survive_normalization() -> None:
    """Exclude YTD values, percent cells and percentage-mix duplicates."""
    current, prior = extract(filing(), "example-source", 2026, 2)
    assert current["start"] == "2026-04-01" and prior["end"] == "2025-06-30"
    assert current["billed_ig"] == "11000000000"
    assert current["billed_total"] == "14000000000"
    assert current["ratings_transaction_revenue"] == "11000000"
    assert prior["ratings_non_transaction_revenue"] == "8000000"
    assert current["source_refs"]["billed_total"] == ["example-source"]


@pytest.mark.parametrize(
    "body",
    [
        filing().replace("(in billions)", "(in millions)"),
        filing().replace("2026 2025", "2027 2026"),
        filing().replace("Three Months Six Months", "Six Months Three Months"),
    ],
)
def test_changed_units_or_column_order_are_rejected(body: str) -> None:
    """A source layout change cannot silently become an incorrect time series."""
    with pytest.raises(ValueError):
        extract(body, "example-source", 2026, 2)
