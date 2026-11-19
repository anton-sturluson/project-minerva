"""Complete SEC sources, including unaggregated 13F rows; no database ingest."""
from __future__ import annotations
import csv
from datetime import date
from calendar import monthrange
from decimal import Decimal
from io import StringIO
import json
import re
from pathlib import Path
import tempfile
from xml.etree import ElementTree as ET
import yaml
from minerva.documents import DocumentError, create_pair, pair_files
from minerva.sec_xml import element_text, reporting_unit, parse_report_period


def leaves(root: ET.Element, prefix: str = "") -> list[tuple[str, str]]:
    """Include every XML leaf in source order, retaining repeated/optional fields."""
    path = prefix + root.tag.rsplit("}", 1)[-1]
    if not len(root):
        return [(path, (root.text or "").strip())]
    return [item for child in root for item in leaves(child, path + "/")]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br/>")


def full_13f_markdown(primary: bytes, tables: list[bytes], *, filed_date: str,
                       report_period: str | None = None) -> tuple[str, dict, str]:
    """Cover + summary + every original row/field. Never group or deduplicate."""
    root = ET.fromstring(primary)
    rows = [node for table in tables for node in ET.fromstring(table).iter()
            if node.tag.rsplit("}", 1)[-1].lower() == "infotable"]
    declared = element_text(root, "tableEntryTotal")
    if not declared or int(declared) != len(rows):
        raise DocumentError(f"13F incomplete table: declared {declared or 'unknown'}, found {len(rows)} rows")
    period = parse_report_period(element_text(root, "reportCalendarOrQuarter"))
    if period.month not in {3, 6, 9, 12} or period.day != monthrange(period.year, period.month)[1]:
        raise DocumentError("13F report period is not a calendar quarter end")
    if report_period and period != date.fromisoformat(report_period):
        raise DocumentError("13F cover report period differs from SEC index")
    multiplier = reporting_unit(date.fromisoformat(filed_date))
    value = Decimal(0)
    records = []
    for index, row in enumerate(rows, 1):
        raw = element_text(row, "value")
        number = Decimal(raw)
        quantity = Decimal(element_text(row, "sshPrnamt"))
        if not number.is_finite() or number < 0 or not quantity.is_finite() or quantity < 0:
            raise DocumentError("Invalid 13F value or share quantity")
        if (len(element_text(row, "cusip")) != 9
            or not element_text(row, "titleOfClass")
            or element_text(row, "sshPrnamtType").upper() not in {"SH", "PRN"}
            or element_text(row, "putCall").upper() not in {"", "PUT", "CALL"}):
            raise DocumentError("Invalid 13F identity or option type")
        value += number
        record = {"Source row": str(index)}
        for key, text in leaves(row):
            key = key.removeprefix("infoTable/")
            # Repeated manager entries retain order rather than overwriting one another.
            record[key] = record[key] + "; " + text if key in record else text
        records.append(record)
    declared_value = Decimal(element_text(root, "tableValueTotal"))
    tolerance = Decimal(len(rows) + 1) / 2
    if not declared_value.is_finite() or abs(declared_value - value) > tolerance:
        raise DocumentError("13F table value differs from cover beyond per-row rounding tolerance")
    columns = list(dict.fromkeys(key for row in records for key in row))
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(records)
    # Vertical field/value tables avoid losing columns in PDF page width.
    lines = ["# Complete SEC Form 13F", "", "## Cover and summary (all XML fields)", "", "| XML field | Value |", "| --- | --- |"]
    lines.extend(f"| {_cell(key)} | {_cell(text)} |" for key, text in leaves(root))
    unit = "USD" if multiplier == 1 else "USD thousands"
    lines += ["", f"## Information table — all {len(rows)} original rows", "",
              f"Reported value unit: **{unit}**; raw total: **{value}**; USD total: **{value * multiplier}**.",
              "Source order, duplicate CUSIPs and option rows are preserved. This filing is not merged with amendments."]
    for record in records:
        lines += ["", f"### Source row {record['Source row']}", "", "| XML field | Reported value |", "| --- | --- |"]
        lines.extend(f"| {_cell(key)} | {_cell(text)} |" for key, text in record.items() if key != "Source row")
    warnings = []
    if element_text(root, "isConfidentialOmitted").lower() in {"true", "1"}:
        warnings.append("Confidential holdings omitted by filer; all PUBLIC rows included, not a complete economic portfolio")
        lines += ["", "**Warning: " + warnings[-1] + ".**"]
    return "\n".join(lines) + "\n", {"table_rows": len(rows), "reported_value_unit": unit,
        "table_value_raw": str(value), "table_value_usd": str(value * multiplier),
        "report_period": period.isoformat(), "amendment_type": element_text(root, "amendmentType"),
        "is_amendment": element_text(root, "isAmendment"), "source_warnings": warnings}, output.getvalue()


def _archive_xml(raw: dict[str, bytes]) -> dict[str, bytes]:
    """Retain XML originals plus a readable, lossless leaf-order YAML companion."""
    result = dict(raw)
    for name, payload in raw.items():
        if name.endswith(".xml"):
            result[name + ".yaml"] = yaml.safe_dump(leaves(ET.fromstring(payload)), allow_unicode=True, sort_keys=False).encode()
    return result


def collect_13f(filing, stem: Path) -> dict:
    """Use exact accession attachment identities, not the normalized holdings model."""
    import httpx
    from edgar import get_identity
    accession = str(filing.accession_no)
    cik = str(int(filing.cik))
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    with httpx.Client(headers={"User-Agent": get_identity()}, timeout=60) as client:
        def read(name):
            response = client.get(base + name)
            response.raise_for_status()
            return response.content
        index = json.loads(read("index.json"))
        # Inventory FIRST: malformed or missing declared tables cannot be ignored
        # just because another table happens to match the cover's row count.
        submission = read(accession + ".txt")
        inventory = []
        for block in re.findall(rb"<DOCUMENT>\s*(.*?)</DOCUMENT>", submission, flags=re.I | re.S):
            header = re.split(rb"<TEXT>", block, maxsplit=1, flags=re.I)[0]
            kind = re.search(rb"<TYPE>[^\r\n]+", header, flags=re.I)
            name = re.search(rb"<FILENAME>[^\r\n]+", header, flags=re.I)
            if name:
                inventory.append((name[0].split(b">", 1)[1].decode().strip(),
                                  kind[0].split(b">", 1)[1].decode().strip().upper() if kind else ""))
        if not inventory:
            raise DocumentError("Cannot establish 13F submission attachment inventory")
        order = [name for name, _ in inventory]
        required = {name for name, kind in inventory if kind == "INFORMATION TABLE"}
        indexed = [item["name"] for item in index["directory"]["item"]]
        missing = required - set(indexed)
        if missing:
            raise DocumentError("Missing required 13F information table: " + ", ".join(sorted(missing)))
        primary_name = str(filing.document.document).rsplit("/", 1)[-1]
        primary = read(primary_name)
        raw = {primary_name: primary, accession + ".txt": submission}
        tables, table_urls, skipped = [], [], []
        import time
        candidates = list(dict.fromkeys(order + indexed))
        for name in candidates:
            if name == primary_name or (name not in required and not name.lower().endswith(".xml")):
                continue
            if Path(name).name != name:
                raise DocumentError("Unsafe 13F attachment filename")
            time.sleep(0.15)
            try:
                payload = read(name)
                table_root = ET.fromstring(payload)
            except Exception as exc:
                raise DocumentError(f"Unreadable 13F XML candidate {name}; table completeness unverified") from exc
            is_table = table_root.tag.rsplit("}", 1)[-1].lower() == "informationtable"
            if name in required and not is_table:
                raise DocumentError(f"Required 13F information table {name} has an unexpected XML root")
            if is_table:
                if name not in order:
                    raise DocumentError("Cannot establish original source order for information table " + name)
                tables.append(payload)
                table_urls.append(base + name)
                raw[name] = payload
            else:
                skipped.append(name)
        # candidates already follows submission order, including duplicate-CUSIP parts.
    if not tables:
        raise DocumentError("No complete 13F information table found")
    text, info, csv_text = full_13f_markdown(primary, tables, filed_date=str(filing.filing_date),
                                            report_period=str(filing.period_of_report) if filing.period_of_report else None)
    raw["all-original-rows.csv"] = csv_text.encode()
    return _native_pair(primary, text, stem, "xml", base + primary_name, _archive_xml(raw),
                        {"accession": accession, "form": filing.form, "table_urls": table_urls,
                         "skipped_non_table_xml": skipped, **info})


def _native_pair(data: bytes, markdown: str, stem: Path, fmt: str, source_url: str, raw: dict, metadata: dict) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ("source." + fmt)
        path.write_bytes(data)
        return create_pair(source=str(path), stem=stem, source_format=fmt, source_url=source_url,
                           markdown=markdown, raw_files=raw, metadata=metadata)


def collect_filing(filing, stem: Path) -> dict:
    if any(path.exists() or path.is_symlink() for path in pair_files(stem)):
        raise DocumentError(f"Existing complete or partial pair at {stem.name}; choose a new stem (no overwrite)")
    if str(filing.form) in {"13F-HR", "13F-HR/A"}:
        return collect_13f(filing, stem)
    html = filing.html()
    if not html or "</html>" not in html.lower():
        raise DocumentError("Missing or truncated full filing HTML")
    from edgar.documents import HTMLParser, ParserConfig
    document = HTMLParser(ParserConfig(form=str(filing.form))).parse(html)
    url = str(filing.document.url)
    document.metadata.url = url
    markdown = document.to_markdown()
    if not markdown or len(markdown.strip()) < 80:
        raise DocumentError("Full filing Markdown is empty or suspiciously short")
    return _native_pair(html.encode(), markdown, stem, "html", url, {"original.html": html.encode()},
                        {"accession": str(filing.accession_no), "form": str(filing.form),
                         "filing_date": str(filing.filing_date)})


def collect_attachment(attachment, stem: Path, *, accession: str) -> dict:
    """HTML and Markdown refer to the SAME exhibit, never the parent 8-K."""
    if any(path.exists() or path.is_symlink() for path in pair_files(stem)):
        raise DocumentError(f"Existing complete or partial pair at {stem.name}; choose a new stem (no overwrite)")
    html = attachment.content
    if not isinstance(html, str) or "</html>" not in html.lower():
        raise DocumentError("Missing or incomplete exhibit HTML")
    from edgar.documents import HTMLParser, ParserConfig
    document = HTMLParser(ParserConfig()).parse(html)
    document.metadata.url = str(attachment.url)
    markdown = document.to_markdown()
    if not markdown:
        raise DocumentError("Could not convert full exhibit HTML to Markdown")
    return _native_pair(html.encode(), markdown, stem, "html", str(attachment.url),
                        {"original.html": html.encode()}, {"accession": accession, "form": "EX-99.1"})
