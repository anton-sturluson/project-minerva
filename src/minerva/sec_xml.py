"""Pure SEC XML collection primitives, adapted from the research importer.

Keep this narrow copy independent: the backend is a separately installed package.
Source: investor_platform/research/sync.py; no database or ingest imports."""
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET


def element_text(element: ET.Element, name: str) -> str:
    """Find a tag without depending on a particular SEC namespace."""
    child: ET.Element
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1].lower() == name.lower():
            return (child.text or "").strip()
    return ""


def reporting_unit(filed_date: date) -> Decimal:
    """Return the USD value of one reported unit under the filing-date convention."""
    return Decimal(1) if filed_date >= date(2023, 1, 3) else Decimal(1000)


def parse_report_period(value: str) -> date:
    """Accept SEC ISO dates and historical month-first date formats."""
    format_string: str
    for format_string in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, format_string).date()
        except ValueError:
            continue
    raise ValueError("Unrecognized SEC report period")
