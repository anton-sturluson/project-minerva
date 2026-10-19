"""Concrete parsers for original-publisher macro and Shiller workbooks."""

import calendar
import csv
import io
import re
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser
from typing import cast
from urllib.parse import unquote, urljoin, urlsplit
from zipfile import ZipFile

import openpyxl
import xlrd
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from investor_platform.economics.parsers import Fact, number, validate

BEA_SECTION1: str = "https://apps.bea.gov/national/Release/XLS/Survey/Section1All_xls.xlsx"
BEA_SECTION2: str = "https://apps.bea.gov/national/Release/XLS/Survey/Section2All_xls.xlsx"
SHILLER_URL: str = "https://shillerdata.com/"


class ShillerLinks(HTMLParser):
    """Read the publisher's current workbook link instead of guessing an asset URL."""

    def __init__(self) -> None:
        """Start a fresh candidate list for one publisher page."""
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Accept only explicitly linked standard equity-data workbooks."""
        if tag != "a":
            return
        attributes: dict[str, str | None] = dict(attrs)
        href: str = attributes.get("href") or ""
        url: str = urljoin(SHILLER_URL, href)
        if (
            unquote(urlsplit(url).path).endswith("/ie_data.xls")
            and urlsplit(url).scheme == "https"
            and urlsplit(url).hostname
            in {"shillerdata.com", "www.shillerdata.com", "img1.wsimg.com"}
        ):
            self.links.append(url)


def shiller_workbook_url(html: bytes) -> str:
    """Require one unambiguous standard CAPE workbook link on the publisher page."""
    parser: ShillerLinks = ShillerLinks()
    parser.feed(html.decode("utf-8"))
    links: set[str] = set(parser.links)
    if len(links) != 1:
        raise ValueError("Shiller workbook link is missing or ambiguous")
    return links.pop()


def parse_shiller_rows(rows: list[list[str | float | int]]) -> list[Fact]:
    """Find the named standard CAPE column and retain provisional publisher notes."""
    headers: list[tuple[int, int, int]] = [
        (index, row.index("Date"), row.index("CAPE"))
        for index, row in enumerate(rows[:30])
        if "Date" in row and "CAPE" in row and "TR CAPE" in row
    ]
    if len(headers) != 1:
        raise ValueError("Shiller standard and total-return CAPE headers changed")
    header, date_column, cape_column = headers[0]
    facts: list[Fact] = []
    notes: list[str] = []
    row: list[str | float | int]
    row_index: int
    for row_index, row in enumerate(rows[header + 1 :], header + 2):
        raw_date: str | float | int = row[date_column]
        if not isinstance(raw_date, (int, float)):
            notes += [str(value).strip() for value in row if str(value).strip()]
            continue
        period: Decimal = Decimal(str(raw_date))
        year: int = int(period)
        month: int = int((period - year) * 100)
        if not 1 <= month <= 12:
            raise ValueError("Invalid Shiller year.month period")
        day: date = date(year, month, 1)
        value: Decimal | None = number(row[cape_column])
        # The ten-year earnings history is unavailable before CAPE begins in 1881.
        if value is None and year < 1881:
            continue
        refs: list[dict[str, str]] = (
            [
                {
                    "component": "CAPE",
                    "value": str(value),
                    "formula": "round half-even to six decimal places",
                }
            ]
            if value is not None
            else []
        )
        normalized: Decimal | None = (
            value.quantize(Decimal("0.000001")) if value is not None else None
        )
        facts.append(Fact("cape", day, normalized, f"Data:row{row_index}:CAPE", derived_from=refs))
    facts = validate(facts)
    latest: date = max(fact.date for fact in facts)
    note_text: str = "; ".join(dict.fromkeys(notes))
    provisional_months: set[int] = {latest.month}
    estimated_notes: str = " ".join(note for note in notes if "estimated" in note.lower())
    provisional_months |= {
        month
        for month in range(1, 13)
        if re.search(
            r"\b(?:"
            + calendar.month_abbr[month]
            + "|"
            + calendar.month_name[month]
            + ("|Sept" if month == 9 else "")
            + r")\b",
            estimated_notes,
        )
    }
    provisional_periods: set[tuple[int, int]] = {
        (latest.year - (month > latest.month), month) for month in provisional_months
    }
    return [
        Fact(
            fact.series_key,
            fact.date,
            fact.value,
            fact.locator,
            [
                {
                    "code": "provisional",
                    "text": note_text
                    or "Latest workbook month can contain partial prices or estimated inputs.",
                }
            ]
            if (fact.date.year, fact.date.month) in provisional_periods
            else [],
            fact.derived_from,
        )
        for fact in facts
    ]


def parse_shiller(payload: bytes) -> list[Fact]:
    """Parse the current original .xls workbook through named Data-sheet headers."""
    workbook: xlrd.Book = xlrd.open_workbook(file_contents=payload)
    sheet: xlrd.sheet.Sheet = workbook.sheet_by_name("Data")
    return parse_shiller_rows([sheet.row_values(index) for index in range(sheet.nrows)])


def parse_bea(payload: bytes, section: int) -> list[Fact]:
    """Read named BEA series and period columns, validating units before conversion."""
    specifications: tuple[tuple[str, str, str, str, Decimal], ...] = (
        (
            (
                "T10101-Q",
                "A191RL",
                "real-gdp-growth",
                "[Percent] Seasonally adjusted at annual rates",
                Decimal(1),
            ),
            (
                "T10105-Q",
                "A191RC",
                "nominal-gdp",
                "[Millions of dollars] Seasonally adjusted at annual rates",
                Decimal(1000),
            ),
        )
        if section == 1
        else (
            (
                "T20804-M",
                "DPCCRG",
                "core-pce-index",
                "[Index numbers, 2017=100; seasonally adjusted]",
                Decimal(1),
            ),
            (
                "T20806-M",
                "DPCERX",
                "real-consumption",
                "[Millions of chained (2017) dollars; seasonally adjusted at annual rates]",
                Decimal(1000),
            ),
        )
    )
    workbook: openpyxl.Workbook = openpyxl.load_workbook(
        io.BytesIO(payload), read_only=True, data_only=True
    )
    facts: list[Fact] = []
    try:
        sheet_name: str
        code: str
        key: str
        units: str
        divisor: Decimal
        for sheet_name, code, key, units, divisor in specifications:
            sheet: ReadOnlyWorksheet = cast(ReadOnlyWorksheet, workbook[sheet_name])
            rows: list[tuple] = list(sheet.iter_rows(values_only=True))
            if rows[1][0] != units or rows[3][0] != "Bureau of Economic Analysis":
                raise ValueError("BEA publisher identity or units changed")
            matches: list[tuple] = [row for row in rows[8:] if len(row) > 2 and row[2] == code]
            if len(matches) != 1:
                raise ValueError("BEA series code missing or ambiguous")
            periods: tuple = rows[7]
            if periods[0] != "Line":
                raise ValueError("BEA period header changed")
            column: int
            for column, label in enumerate(periods[3:], 3):
                if label is None:
                    continue
                match: re.Match[str] | None = re.fullmatch(r"(\d{4})([MQ])(\d{1,2})", str(label))
                if match is None or ("M" if section == 2 else "Q") != match[2]:
                    raise ValueError("Unexpected BEA period frequency")
                month: int = int(match[3]) if match[2] == "M" else (int(match[3]) - 1) * 3 + 1
                day: date = date(int(match[1]), month, 1)
                value: Decimal | None = number(matches[0][column], signed=True)
                notes: list[dict[str, str]] = []
                refs: list[dict[str, str]] = []
                if divisor != 1:
                    refs = [
                        {
                            "component": code,
                            "value": str(value),
                            "formula": "millions / 1000 = billions",
                        }
                    ]
                facts.append(
                    Fact(
                        key,
                        day,
                        value / divisor if value is not None else None,
                        f"{sheet_name}:{code}:{label}",
                        notes,
                        refs,
                    )
                )
        return validate(facts)
    finally:
        workbook.close()


def parse_freddie(payload: bytes) -> list[Fact]:
    """Read the weekly 30-year FRM column with its original observed dates."""
    workbook: openpyxl.Workbook = openpyxl.load_workbook(
        io.BytesIO(payload), read_only=True, data_only=True
    )
    try:
        sheet: ReadOnlyWorksheet = cast(ReadOnlyWorksheet, workbook["Full History"])
        rows: Iterator[tuple] = sheet.iter_rows(values_only=True)
        headers: list[tuple] = [next(rows) for _ in range(7)]
        if (
            headers[1][3] != "PRIMARY MORTGAGE MARKET SURVEY®"
            or headers[4][1] != "U.S."
            or headers[5][1] != "30 yr"
            or headers[6][:2] != ("Week", "FRM")
        ):
            raise ValueError("Freddie Mac 30-year weekly workbook headers changed")
        facts: list[Fact] = []
        row: tuple
        for row in rows:
            if row[0] is None:
                continue
            if not isinstance(row[0], datetime):
                if facts and str(row[0]).startswith("Although Freddie Mac"):
                    continue
                raise ValueError("Invalid Freddie Mac weekly date")
            facts.append(
                Fact("mortgage-30y", row[0].date(), number(row[1]), "Full History:30 yr FRM")
            )
        return validate(facts)
    finally:
        workbook.close()


FED_TARGET_URL: str = "https://www.federalreserve.gov/aboutthefed/files/target-funds-2014-2024.csv"
FED_H15_URL: str = (
    "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&"
    "series=bf17364827e38702b42a58cf8eaa3f78&lastobs=&from=&to=&filetype=csv&"
    "label=include&layout=seriescolumn&type=package"
)
FED_EQUITY_URL: str = "https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip"
FREDDIE_URL: str = "https://www.freddiemac.com/pmms/docs/historicalweeklydata.xlsx"


def parse_fed_targets(payload: bytes) -> list[Fact]:
    """Transpose the publisher's effective-date, lower-bound and upper-bound rows."""
    rows: list[list[str]] = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    if len(rows) != 3 or not rows[0] or len({len(row) for row in rows}) != 1:
        raise ValueError("Fed target-range table shape changed")
    facts: list[Fact] = []
    index: int
    for index, text in enumerate(rows[0]):
        day: date = (
            datetime.strptime(text, "%m/%d/%Y").date()
            if "/" in text
            else datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        )
        lower: Decimal | None = number(rows[1][index], signed=True)
        upper: Decimal | None = number(rows[2][index], signed=True)
        if lower is None or upper is None or lower > upper:
            raise ValueError("Invalid Federal Reserve target range")
        facts += [
            Fact("fed-target-lower", day, lower, "effective target range:lower"),
            Fact("fed-target-upper", day, upper, "effective target range:upper"),
        ]
    return validate(facts)


def parse_fed_h15(payload: bytes) -> list[Fact]:
    """Select the daily 10-year yield by native series name, not column position."""
    rows: Iterator[list[str]] = iter(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    headers: list[list[str]] = [next(rows) for _ in range(6)]
    if headers[5].count("RIFLGFCY10_N.B") != 1:
        raise ValueError("Fed H.15 daily 10-year series missing or duplicated")
    column: int = headers[5].index("RIFLGFCY10_N.B")
    if (
        headers[5][0] != "Time Period"
        or headers[1][column] != "Percent:_Per_Year"
        or headers[2][column] != "1"
        or headers[4][column] != "H15/H15/RIFLGFCY10_N.B"
    ):
        raise ValueError("Fed H.15 units or frequency changed")
    return validate(
        [
            Fact(
                "treasury-10y",
                date.fromisoformat(row[0]),
                number(row[column], signed=True),
                "H15/H15/RIFLGFCY10_N.B",
            )
            for row in rows
            if row and row[0]
        ]
    )


def parse_fed_equity(payload: bytes) -> list[Fact]:
    """Read only the public-equity memo item from the small original-publisher table ZIP."""
    with ZipFile(io.BytesIO(payload)) as archive:
        names: tuple[str, str] = ("csv/F51_1_s.csv", "data_dictionary/F51_1_s.txt")
        if any(archive.getinfo(name).file_size > 2 * 1024 * 1024 for name in names):
            raise ValueError("Fed corporate-equity table exceeds supported size")
        dictionary: list[str] = archive.read(names[1]).decode("utf-8-sig").splitlines()
        definitions: list[str] = [line for line in dictionary if line.startswith("LM883164115.Q\t")]
        if (
            len(definitions) != 1
            or "Millions of dollars" not in definitions[0]
            or "end of period" not in definitions[0]
        ):
            raise ValueError("Fed public-equity definition or units changed")
        rows: Iterator[dict[str, str]] = iter(
            csv.DictReader(io.StringIO(archive.read(names[0]).decode("utf-8-sig")))
        )
        facts: list[Fact] = []
        row: dict[str, str]
        for row in rows:
            if "LM883164115.Q" not in row:
                raise ValueError("Fed public-equity column missing")
            match: re.Match[str] | None = re.fullmatch(r"(\d{4}):Q([1-4])", row["date"])
            if match is None:
                raise ValueError("Invalid Fed quarterly period")
            day: date = date(int(match[1]), (int(match[2]) - 1) * 3 + 1, 1)
            facts.append(
                Fact(
                    "public-equity",
                    day,
                    number(row["LM883164115.Q"]),
                    "csv/F51_1_s.csv:LM883164115.Q:" + row["date"],
                )
            )
        return validate(facts)
