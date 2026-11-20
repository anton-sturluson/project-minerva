"""Validate official SEC/BIS downloads and render three standalone comparison charts.

Run with --research-dir containing the four public files listed in SOURCE_URLS.
This experiment reads structured cells and CSV fields; it does not parse issuer filings.
"""

import argparse
import csv
import hashlib
import html
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

SEC_PAGE: str = (
    "https://www.sec.gov/data-research/statistics-data-visualizations/corporate-bond-offerings"
)
BIS_ROOT: str = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_DEBT_SEC2_PUB/1.0/"
SOURCE_URLS: dict[str, str] = {
    "sec-corporate-bond-offerings-20260922.xlsx": (
        "https://www.sec.gov/files/sec-stats-corporate-bond-offerings-20260922.xlsx"
    ),
    "bis-us-nationality.csv": BIS_ROOT
    + "Q.3P.US.1.J.C.A.A.TO1.A.A.A.A.A.C+G?startPeriod=2018-Q1&format=csvfile",
    "bis-us-residence.csv": BIS_ROOT
    + "Q.US.3P.J.1.C.A.A.TO1.A.A.A.A.A.C+G?startPeriod=2018-Q1&format=csvfile",
    "bis-debt-structure.json": (
        "https://stats.bis.org/api/v2/structure/dataflow/BIS/WS_DEBT_SEC2_PUB/1.0"
        "?references=all&format=sdmx-json"
    ),
}
INK: str = "#172e33"
TEAL: str = "#087e8b"
ORANGE: str = "#b9511a"
GRID: str = "#dde5e5"


@dataclass(frozen=True)
class Observation:
    """Store source-native USD millions, not rounded chart labels."""

    source: str
    series: str
    period: str
    value_usd_millions: str
    source_location: str


def amount(value: object) -> Decimal:
    """Reject missing, boolean and non-finite amounts instead of turning them into zero."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"Invalid numeric amount: {value!r}")
    result: Decimal = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite amount")
    return result


def read_sec(path: Path) -> tuple[list[Observation], list[Observation]]:
    """Check named workbook columns and separate quarterly totals from H1 industries."""
    workbook: Workbook = load_workbook(path, read_only=True, data_only=True)
    sheet: ReadOnlyWorksheet = workbook["Stats Table"]
    headers: tuple[object, ...] = next(sheet.values)
    if headers[0] != "Time Period" or headers[6] != (
        "Corporate bond offering total proceeds ($US Million)"
    ):
        raise ValueError("SEC workbook total-proceeds columns changed")
    quarterly: list[Observation] = []
    seen: set[str] = set()
    for row_number, row in enumerate(sheet.values, start=1):
        period: str = str(row[0])
        if not re.fullmatch(r"\d{4}:Q[1-4]", period):
            continue
        if period in seen:
            raise ValueError("Duplicate SEC quarter")
        seen.add(period)
        total: Decimal = amount(row[6])
        if total < 0 or abs(total - amount(row[7]) - amount(row[8])) > Decimal("0.2"):
            raise ValueError("SEC issuer-location proceeds do not reconcile")
        quarterly.append(
            Observation(
                "SEC",
                "US-market proceeds",
                period.replace(":", "-"),
                str(total),
                f"Stats Table!G{row_number}",
            )
        )
    industry_sheet: ReadOnlyWorksheet = workbook["Data Visual 2"]
    industry_headers: tuple[object, ...] = tuple(industry_sheet.values)[1]
    if industry_headers[:2] != ("Time Period", "Industry") or industry_headers[4] != (
        "Total Proceeds ($US Million)"
    ):
        raise ValueError("SEC workbook industry columns changed")
    industries: list[Observation] = []
    for row_number, row in enumerate(industry_sheet.values, start=1):
        if row[0] == "2026:Q1-Q2":
            industries.append(
                Observation(
                    "SEC",
                    str(row[1]),
                    "2026-H1",
                    str(amount(row[4])),
                    f"Data Visual 2!E{row_number}",
                )
            )
    h1_total: Decimal = sum(
        (
            amount(item.value_usd_millions)
            for item in quarterly
            if item.period in ("2026-Q1", "2026-Q2")
        ),
        Decimal(0),
    )
    if not industries or abs(
        sum((amount(item.value_usd_millions) for item in industries), Decimal(0)) - h1_total
    ) > Decimal("0.2"):
        raise ValueError("SEC industry table does not reconcile to H1 quarterly totals")
    workbook.close()
    return sorted(quarterly, key=lambda item: item.period), industries


def read_bis(path: Path, basis: str) -> list[Observation]:
    """Require the exact quarterly US non-financial international-issuance series."""
    expected: dict[str, str] = {
        "FREQ": "Q",
        "MARKET": "C",
        "ISSUE_TYPE": "A",
        "ISSUE_CUR_GROUP": "A",
        "ISSUE_CUR": "TO1",
        "ISSUE_OR_MAT": "A",
        "ISSUE_RE_MAT": "A",
        "ISSUE_RATE": "A",
        "ISSUE_RISK": "A",
        "ISSUE_COL": "A",
        "UNIT_MEASURE": "USD",
        "UNIT_MULT": "6",
    }
    expected.update(
        {"ISSUER_RES": "3P", "ISSUER_NAT": "US", "ISSUER_BUS_IMM": "1", "ISSUER_BUS_ULT": "J"}
        if basis == "nationality"
        else {"ISSUER_RES": "US", "ISSUER_NAT": "3P", "ISSUER_BUS_IMM": "J", "ISSUER_BUS_ULT": "1"}
    )
    results: list[Observation] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(csv.DictReader(io.StringIO(path.read_text())), start=2):
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError(f"BIS series dimensions or USD units changed at row {row_number}")
        measure: str = row["MEASURE"]
        if measure not in ("C", "G") or row["OBS_STATUS"] != "A":
            raise ValueError("Unexpected BIS measure or missing/non-normal observation")
        period: str = row["TIME_PERIOD"]
        if not re.fullmatch(r"\d{4}-Q[1-4]", period) or (measure, period) in seen:
            raise ValueError("Invalid or duplicate BIS observation")
        seen.add((measure, period))
        value: Decimal = amount(row["OBS_VALUE"])
        if measure == "C" and value < 0:
            raise ValueError("Gross issuance cannot be negative")
        name: str = f"{basis}: {'gross' if measure == 'C' else 'net'}"
        results.append(Observation("BIS", name, period, str(value), f"{path.name}:row{row_number}"))
    if not results:
        raise ValueError("Empty BIS download")
    return sorted(results, key=lambda item: (item.series, item.period))


def text(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 15,
    fill: str = INK,
    anchor: str = "start",
    weight: str = "normal",
) -> str:
    """Escape all chart labels before placing them in SVG."""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{html.escape(value)}</text>'
    )


def line(x1: float, y1: float, x2: float, y2: float, color: str = GRID) -> str:
    """Draw a rule without introducing an additional chart dependency."""
    return f'<path d="M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}" stroke="{color}" fill="none"/>'


def frame(title: str, subtitle: str, body: list[str], footer: str, height: int) -> str:
    """Wrap an accessible vector chart with explicit source and unit labels."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 {height}" role="img" '
        f'aria-label="{html.escape(title, quote=True)}"><title>{html.escape(title)}</title>'
        "<style>text{font-family:Arial,Helvetica,sans-serif}path,rect{vector-effect:non-scaling-stroke}</style>"
        f'<rect width="1100" height="{height}" fill="white"/>'
        + text(32, 42, title, size=26, weight="bold")
        + text(32, 70, subtitle, size=15)
        + "".join(body)
        + text(32, height - 20, footer, size=13)
        + "</svg>"
    )


def sec_history(observations: list[Observation]) -> str:
    """Plot quarterly gross proceeds with a zero baseline and highlight the latest quarter."""
    left: int = 88
    top: int = 118
    bottom: int = 437
    width: int = 965
    maximum: int = 600
    parts: list[str] = [text(left, 101, "Gross proceeds · USD billions", size=14)]
    for tick in range(0, maximum + 1, 100):
        y: float = bottom - tick / maximum * (bottom - top)
        parts.extend(
            [line(left, y, left + width, y), text(left - 14, y + 5, str(tick), anchor="end")]
        )
    step: float = width / len(observations)
    for index, observation in enumerate(observations):
        value: float = float(amount(observation.value_usd_millions) / 1000)
        if not 0 <= value <= maximum:
            raise ValueError("SEC observation exceeds chart limits")
        height: float = value / maximum * (bottom - top)
        x: float = left + index * step + step * 0.15
        color: str = ORANGE if index == len(observations) - 1 else TEAL
        parts.append(
            f'<rect x="{x:.2f}" y="{bottom - height:.2f}" width="{step * 0.7:.2f}" '
            f'height="{height:.2f}" fill="{color}"><title>{observation.period}: '
            f"${value:,.3f}bn</title></rect>"
        )
        if observation.period.endswith("Q1"):
            parts.append(text(x, bottom + 27, observation.period[:4], size=13))
    latest: Observation = observations[-1]
    latest_value: Decimal = amount(latest.value_usd_millions) / 1000
    parts.append(
        text(
            1053,
            101,
            f"{latest.period}: ${latest_value:,.1f}bn",
            anchor="end",
            fill=ORANGE,
            weight="bold",
        )
    )
    parts.append(text(568, 493, "Pricing quarter", anchor="middle", size=14))
    return frame(
        "SEC: registered bond offerings in the U.S. market",
        "U.S. and foreign issuers · non-convertible bonds with maturity over one year",
        parts,
        "Source: SEC / LSEG SDC Platinum. Excludes 144A, private debt and convertibles.",
        550,
    )


def sec_industries(observations: list[Observation]) -> str:
    """Show the official H1 industry split without calling technology issuance AI debt."""
    ordered: list[Observation] = sorted(
        observations, key=lambda item: amount(item.value_usd_millions), reverse=True
    )
    total: Decimal = sum((amount(item.value_usd_millions) for item in ordered), Decimal(0))
    parts: list[str] = [text(370, 104, "Gross proceeds · USD billions", size=14)]
    for tick in (0, 100, 200, 300):
        x: float = 370 + tick / 360 * 600
        parts.extend([line(x, 122, x, 555), text(x, 583, str(tick), anchor="middle", size=13)])
    for index, observation in enumerate(ordered):
        value: float = float(amount(observation.value_usd_millions) / 1000)
        y: int = 130 + index * 35
        color: str = ORANGE if observation.series == "Technology" else TEAL
        parts.append(text(350, y + 16, observation.series, anchor="end", size=14))
        parts.append(
            f'<rect x="370" y="{y}" width="{value / 360 * 600:.2f}" height="23" fill="{color}"/>'
        )
        share: Decimal = amount(observation.value_usd_millions) / total * 100
        parts.append(
            text(380 + value / 360 * 600, y + 16, f"${value:,.1f}bn · {share:.1f}%", size=13)
        )
    return frame(
        "SEC: who raised the money?",
        "2026 H1 (Q1 + Q2) · all issuer locations · official major industry groups",
        parts,
        "Source: SEC / LSEG SDC Platinum. Technology includes non-AI issuers; "
        "this is not an AI-debt measure.",
        630,
    )


def bis_history(observations: list[Observation]) -> str:
    """Use aligned gross/net panels and explicit nationality versus residence definitions."""
    periods: list[str] = sorted({item.period for item in observations})
    lookup: dict[tuple[str, str], float] = {
        (item.series, item.period): float(amount(item.value_usd_millions) / 1000)
        for item in observations
    }
    parts: list[str] = [text(88, 109, "USD billions · all currencies converted by BIS", size=14)]
    for panel, measure in enumerate(("gross", "net")):
        top: int = 152 + panel * 295
        bottom: int = top + 194
        lower: int = 0 if measure == "gross" else -25
        upper: int = 150 if measure == "gross" else 100
        parts.append(
            text(
                88,
                top - 16,
                "Gross issuance"
                if measure == "gross"
                else "Net issuance (gross minus redemptions)",
                weight="bold",
                size=17,
            )
        )
        for tick in range(lower, upper + 1, 25):
            y: float = bottom - (tick - lower) / (upper - lower) * (bottom - top)
            parts.extend(
                [
                    line(88, y, 1048, y, INK if tick == 0 else GRID),
                    text(74, y + 5, str(tick), anchor="end", size=13),
                ]
            )
        for basis, color, dash in (("nationality", TEAL, ""), ("residence", ORANGE, "6 4")):
            points: list[str] = []
            for index, period in enumerate(periods):
                value: float | None = lookup.get((f"{basis}: {measure}", period))
                if value is None:
                    raise ValueError("BIS charts require matching complete quarter grids")
                x: float = 88 + index / (len(periods) - 1) * 960
                y = bottom - (value - lower) / (upper - lower) * (bottom - top)
                if not lower <= value <= upper:
                    raise ValueError("BIS observation exceeds chart limits")
                points.append(f"{x:.2f},{y:.2f}")
                parts.append(
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.7" fill="{color}">'
                    f"<title>{basis}, {period}: ${value:,.3f}bn</title></circle>"
                )
            parts.append(
                f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" '
                f'stroke-width="2.5" stroke-dasharray="{dash}"/>'
            )
        for index, period in enumerate(periods):
            if period.endswith("Q1"):
                parts.append(
                    text(
                        88 + index / (len(periods) - 1) * 960,
                        bottom + 24,
                        period[:4],
                        anchor="middle",
                        size=13,
                    )
                )
    parts.extend(
        [
            text(88, 734, "● U.S. ultimate-parent nationality / parent sector", fill=TEAL, size=14),
            text(
                88, 760, "– – U.S. issuer residence / immediate-issuer sector", fill=ORANGE, size=14
            ),
            text(1048, 760, "Issue quarter · through 2026-Q2", anchor="end", size=14),
        ]
    )
    return frame(
        "BIS: international issuance by U.S. non-financial corporations",
        "Different issuer bases overlap; they are alternatives, not amounts to add together",
        parts,
        "Source: BIS debt securities statistics. International market only; "
        "includes bonds and money-market instruments.",
        820,
    )


def write_report(research_dir: Path, output_dir: Path) -> None:
    """Retain exact plot data, file hashes and a responsive standalone report."""
    quarterly, industries = read_sec(research_dir / next(iter(SOURCE_URLS)))
    bis: list[Observation] = read_bis(research_dir / "bis-us-nationality.csv", "nationality")
    bis.extend(read_bis(research_dir / "bis-us-residence.csv", "residence"))
    all_data: list[Observation] = quarterly + industries + bis
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "plotted-data.csv").open("w", newline="") as handle:
        writer: csv.DictWriter[str] = csv.DictWriter(handle, fieldnames=list(asdict(all_data[0])))
        writer.writeheader()
        writer.writerows(asdict(item) for item in all_data)
    manifest: list[dict[str, str | int]] = [
        {
            "file": name,
            "url": url,
            "bytes": (research_dir / name).stat().st_size,
            "sha256": hashlib.sha256((research_dir / name).read_bytes()).hexdigest(),
            "retrieved_at": datetime.fromtimestamp(
                (research_dir / name).stat().st_mtime, UTC
            ).isoformat(),
        }
        for name, url in SOURCE_URLS.items()
    ]
    (output_dir / "source-manifest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "sources": manifest,
                "observations": len(all_data),
                "sec_quarters": len(quarterly),
                "industry_rows": len(industries),
                "bis_observations": len(bis),
            },
            indent=2,
        )
        + "\n"
    )
    charts: dict[str, str] = {
        "sec-quarterly": sec_history(quarterly),
        "sec-industries": sec_industries(industries),
        "bis-issuance": bis_history(bis),
    }
    for name, svg in charts.items():
        (output_dir / f"{name}.svg").write_text(svg)
    sections: str = "".join(
        f'<section>{svg}<p><a href="{name}.svg">SVG</a>'
        + (f' · <a href="{name}.png">PNG</a>' if (output_dir / f"{name}.png").exists() else "")
        + "</p></section>"
        for name, svg in charts.items()
    )
    sources: str = "".join(
        f'<li><a href="{html.escape(url, quote=True)}">{html.escape(name)}</a></li>'
        for name, url in SOURCE_URLS.items()
    )
    (output_dir / "index.html").write_text(
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Official debt data comparison</title>
<style>body{font:17px/1.55 Arial,sans-serif;margin:0;background:#f3f5f4;color:#172e33}
main{max-width:1100px;margin:auto;padding:28px 18px}h1{font-size:32px;line-height:1.2}
section{background:white;margin:24px 0;border:1px solid #dde5e5}section p{padding:0 24px}
svg{display:block;width:100%;height:auto}a{color:#087e8b}table{border-collapse:collapse;width:100%;font-size:15px}
td,th{border-bottom:1px solid #ccd6d6;text-align:left;padding:10px;vertical-align:top}
small{color:#476167}.scroll{overflow-x:auto}details{margin:24px 0}li{overflow-wrap:anywhere}
@media(prefers-color-scheme:dark){body{background:#152326;color:#e7f0ee}a{color:#71d2dc}small{color:#b1c5c1}}
</style><main><small>RESEARCH / STRUCTURED DATA TEST · 23 OCT 2026</small>
<h1>Official sources cover different parts of the debt market.</h1>
<p>These downloads provide broad market context without parsing company filings.
Neither identifies individual hyperscalers or neoclouds.
The chart totals overlap and must not be added.</p>
<div class="scroll"><table><tr><th>Source</th><th>What it measures</th>
<th>Collection</th><th>Company detail</th></tr>
<tr><td>SEC</td><td>Registered non-convertible U.S.-market bond offerings over one year;
all sectors and issuer locations. Excludes private placements / 144A and private debt.</td>
<td>Quarterly XLSX; 34 quarters, 2018 Q1–2026 Q2.
Published by SEC using LSEG SDC Platinum.</td><td>Unavailable</td></tr>
<tr><td>BIS</td><td>International debt securities, including money-market instruments;
U.S. non-financial corporations. Parent nationality and issuer residence are separate views.</td>
<td>Quarterly CSV/API; 34 quarters × 4 series.
All currencies converted to USD by BIS.</td><td>Unavailable</td></tr>
<tr><td>LSEG IFR</td><td>Deal-level records with issuer, amount, terms and status.</td>
<td>Paid/authenticated API. Not collected or plotted in this test.</td><td>Potentially useful;
cohort and private-financing coverage need a subscription sample.</td></tr></table></div>
<p><strong>How to read the difference:</strong> SEC follows where and how a bond is offered.
BIS follows international securities and the issuer's sector and location.
BIS net issuance subtracts redemptions; SEC proceeds are gross. Flows are quarterly, not annualized.
Technology is a broad industry, not an AI classification.</p>"""
        + sections
        + """
<details><summary>Data and sources</summary><p>
<a href="plotted-data.csv">Exact plotted data (CSV)</a> ·
<a href="source-manifest.json">Source files and SHA-256 hashes</a> ·
<a href="research-log.md">Research log</a></p>
<ul>"""
        + sources
        + """</ul><p><a href="""
        + '"'
        + SEC_PAGE
        + '"'
        + """>SEC definitions</a> ·
<a href="https://data.bis.org/topics/IDS">BIS international debt securities</a> ·
<a href="https://deals-api.ifre.com/">LSEG IFR API documentation</a></p></details></main></html>"""
    )
    print(
        json.dumps(
            {
                "sec_quarters": len(quarterly),
                "industry_rows": len(industries),
                "bis_observations": len(bis),
                "charts": len(charts),
            }
        )
    )


def main() -> None:
    """Render from retained official downloads so a replay does not need network access."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args: argparse.Namespace = parser.parse_args()
    write_report(args.research_dir, args.output_dir)


if __name__ == "__main__":
    main()
