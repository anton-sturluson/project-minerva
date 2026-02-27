"""Utility functions for formatting financial data and building markdown tables."""

from pathlib import Path

import xmltodict
import yaml


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


def format_pct(value: float | None, decimals: int = 1) -> str:
    """Format a percentage value (input as 0-100 range)."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}%"


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
