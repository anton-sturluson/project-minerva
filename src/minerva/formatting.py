"""Utility functions for formatting financial data and building markdown tables."""

from pathlib import Path

import pandas as pd
import xmltodict
import yaml


def is_empty(value: object) -> bool:
    """Return True for None, pandas/numpy missing values, and blank-ish strings."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "nat", "<na>"}


def clean_text(value: object) -> str:
    """Convert a messy value to stripped text, returning an empty string for missing values."""
    if is_empty(value):
        return ""
    return str(value).strip()


def md_cell(value: object) -> str:
    """Clean text for use in a markdown table cell."""
    return clean_text(value).replace("\n", " ").replace("|", "\\|")


def format_usd(value: float | None, decimals: int = 2, auto_scale: bool = True) -> str:
    """Format a numeric value as a USD string with automatic scaling.

    Args:
        value: Dollar amount (raw number, e.g. 1_500_000_000 for $1.5B).
        decimals: Number of decimal places for scaled output.
        auto_scale: If True, automatically use B/M/K suffixes.
    """
    if value is None:
        return "N/A"
    if not auto_scale:
        return f"${value:,.{decimals}f}"
    abs_val: float = abs(value)
    sign: str = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.{decimals}f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.{decimals}f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.{decimals}f}M"
    if abs_val >= 1e3:
        return f"{sign}${abs_val / 1e3:.{decimals}f}K"
    return f"{sign}${abs_val:,.{decimals}f}"


def format_pct(value: float | None, decimals: int = 1, *, na_value: str = "N/A") -> str:
    """Format a percentage value (input as 0-100 range)."""
    if value is None:
        return na_value
    return f"{value:.{decimals}f}%"


def format_signed_percent(value: float | None, decimals: int = 1) -> str:
    """Format a signed percentage value (input as 0-100 range)."""
    if value is None:
        return ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_pp(value: float | None, decimals: int = 1) -> str:
    """Format a percentage-point delta with an explicit plus sign for gains."""
    if value is None:
        return ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}pp"


def format_shares(value: float | None) -> str:
    """Format a share count as a whole number with thousands separators."""
    if value is None:
        return ""
    return f"{int(round(value)):,.0f}"


def format_delta_shares(value: float | None) -> str:
    """Format a signed share-count delta as a whole number with thousands separators."""
    if value is None:
        return ""
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(int(round(value))):,}"


def format_millions(value: float | None, *, signed: bool = False) -> str:
    """Format a dollar value in whole millions (e.g. $1,500M)."""
    if value is None:
        return ""
    amount = value / 1_000_000
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}${abs(amount):,.0f}M"
    if amount < 0:
        return f"-${abs(amount):,.0f}M"
    return f"${amount:,.0f}M"


def format_multiple(value: float | None, suffix: str = "x", decimals: int = 1) -> str:
    """Format a valuation multiple (e.g. 2.5x, 30.0x)."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}{suffix}"


def build_markdown_table(headers: list[str], rows: list[list[str]], alignment: list[str] | None = None) -> str:
    """Build a markdown table from headers and row data.

    Args:
        headers: Column header labels.
        rows: List of rows, each row is a list of cell values as strings.
        alignment: Optional list of alignment markers ('l', 'r', 'c') per column.
    """
    if not headers:
        return ""
    align_map: dict[str, str] = {"l": ":---", "r": "---:", "c": ":---:"}
    if alignment is None:
        alignment = ["l"] * len(headers)

    header_line: str = "| " + " | ".join(headers) + " |"
    separator_line: str = "| " + " | ".join(align_map.get(a, "---") for a in alignment) + " |"
    data_lines: list[str] = []
    for row in rows:
        padded_row: list[str] = row + [""] * (len(headers) - len(row))
        data_lines.append("| " + " | ".join(padded_row[:len(headers)]) + " |")

    return "\n".join([header_line, separator_line] + data_lines)


def calculate_growth_rate(current: float, prior: float) -> float | None:
    """Calculate year-over-year growth rate as a percentage.

    Returns None if prior is zero or negative.
    """
    if prior <= 0:
        return None
    return ((current - prior) / prior) * 100


def calculate_margin(numerator: float, denominator: float) -> float | None:
    """Calculate a margin percentage (numerator / denominator * 100).

    Returns None if denominator is zero.
    """
    if denominator == 0:
        return None
    return (numerator / denominator) * 100


def xml_to_yaml(xml_path: Path, yaml_path: Path | None = None) -> Path:
    """Convert an XML file to YAML format.

    Args:
        xml_path: Path to source XML file.
        yaml_path: Output path. If None, replaces .xml with .yaml.

    Returns: Path to the written YAML file.
    """
    if yaml_path is None:
        yaml_path = xml_path.with_suffix(".yaml")

    xml_content: str = xml_path.read_text(encoding="utf-8")
    parsed: dict = xmltodict.parse(xml_content)
    yaml_content: str = yaml.dump(parsed, default_flow_style=False, allow_unicode=True)
    yaml_path.write_text(yaml_content, encoding="utf-8")

    return yaml_path
