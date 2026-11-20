"""Collect an auditable, standalone SEC cash-flow pilot without database writes.

Example: python collect.py --output-dir hard-disk/reports/debt-issuance-pilot
The configured EDGAR_IDENTITY supplies the SEC contact header and is never exported.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator, FormatChecker

HERE: Path = Path(__file__).resolve().parent
FIELDS: tuple[str, ...] = (
    "cfo",
    "cash_capex",
    "debt_cash_proceeds",
    "debt_cash_repayments",
)
COHORT: list[dict] = json.loads((HERE / "cohort.json").read_text())
FORMS: set[str] = {"10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A"}


@dataclass(frozen=True)
class Rule:
    """One explicit source concept and measurement scope; aliases are never summed."""

    concept: str
    label: str
    scope: str


CFO: Rule = Rule(
    "NetCashProvidedByUsedInOperatingActivities",
    "Net operating cash flow",
    "Consolidated operating cash flow, signed USD",
)
CAPEX: Rule = Rule(
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "Cash purchases of property and equipment",
    "Consolidated cash PPE purchases; excludes noncash lease additions",
)
LONG_PROCEEDS: Rule = Rule(
    "ProceedsFromIssuanceOfLongTermDebt",
    "Reported long-term debt cash proceeds",
    "Cash-flow proceeds as reported; not bond face value or bond-only issuance",
)
LONG_REPAYMENTS: Rule = Rule(
    "RepaymentsOfLongTermDebt",
    "Long-term debt cash repayments",
    "Cash repayments of long-term debt; excludes separately reported lease payments",
)
NET_PROCEEDS: Rule = Rule(
    "ProceedsFromDebtNetOfIssuanceCosts",
    "Debt proceeds net of issuance costs",
    "Cash debt proceeds net of issuance costs; not gross principal issuance",
)
DEBT_REPAYMENTS: Rule = Rule(
    "RepaymentsOfDebt",
    "Debt cash repayments",
    "Reported cash debt repayments; not restricted to bonds",
)
RULES: dict[str, dict[str, Rule]] = {
    entity["id"]: {
        "cfo": CFO,
        "cash_capex": CAPEX,
        "debt_cash_proceeds": LONG_PROCEEDS,
        "debt_cash_repayments": LONG_REPAYMENTS,
    }
    for entity in COHORT
}
RULES["MSFT"]["debt_cash_proceeds"] = Rule(
    "ProceedsFromDebtMaturingInMoreThanThreeMonths",
    "Proceeds from debt with original maturities over three months",
    "Cash proceeds from debt originally maturing after three months; excludes shorter debt",
)
RULES["MSFT"]["debt_cash_repayments"] = Rule(
    "RepaymentsOfDebtMaturingInMoreThanThreeMonths",
    "Repayments of debt with original maturities over three months",
    "Cash repayments of debt originally maturing after three months; excludes shorter debt",
)
RULES["GOOGL"]["debt_cash_proceeds"] = NET_PROCEEDS
RULES["GOOGL"]["debt_cash_repayments"] = DEBT_REPAYMENTS
RULES["ORCL"]["debt_cash_repayments"] = DEBT_REPAYMENTS
RULES["NBIS"]["debt_cash_repayments"] = DEBT_REPAYMENTS


@dataclass(frozen=True)
class Fact:
    """An exact entity-wide USD duration fact from a permitted filing before cutoff."""

    start: date
    end: date
    value: Decimal
    accession: str
    filed_date: date
    form: str
    concept: str
    label: str
    scope: str
    source_id: str
    filing_url: str | None

    def reference(self) -> dict:
        """Keep all calculation inputs and their exact source context visible."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "value": str(self.value),
            "accession": self.accession,
            "filed_date": self.filed_date.isoformat(),
            "filing_form": self.form,
            "concept": self.concept,
            "reported_label": self.label,
            "unit": "USD",
            "scope": self.scope,
            "source_id": self.source_id,
            "filing_url": self.filing_url,
        }


def month_shift(day: date, months: int) -> date:
    """Move between first-of-month fiscal boundaries without approximating durations."""
    index: int = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def fiscal_window(end: date, fiscal_year_end: str) -> tuple[date, date, int, int] | None:
    """Identify exact monthly fiscal-quarter boundaries rather than XBRL frame labels."""
    month: int = int(fiscal_year_end[:2])
    year: int = end.year + (end.month > month)
    start: date = date(year if month == 12 else year - 1, month % 12 + 1, 1)
    quarter: int = ((end.month - start.month) % 12) // 3 + 1
    qstart: date = month_shift(start, (quarter - 1) * 3)
    qend: date = month_shift(qstart, 3) - timedelta(days=1)
    return (start, qstart, year, quarter) if qend == end else None


def document_url(entity: dict, accession: str, submissions: dict) -> str:
    """Link the filing document when indexed, otherwise its public EDGAR accession directory."""
    recent: dict = submissions.get("filings", {}).get("recent", {})
    primary: dict[str, str] = dict(
        zip(
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            strict=True,
        )
    )
    base: str = (
        f"https://www.sec.gov/Archives/edgar/data/{int(entity['cik'])}/"
        f"{accession.replace('-', '')}/"
    )
    return base + primary.get(accession, "")


def read_facts(
    payload: dict,
    rule: Rule,
    entity: dict,
    submissions: dict,
    cutoff: date,
    source_id: str,
) -> list[Fact]:
    """Accept only named consolidated USD facts with explicit start/end/filing dates."""
    concept: dict = payload.get("facts", {}).get("us-gaap", {}).get(rule.concept, {})
    result: list[Fact] = []
    row: dict
    for row in concept.get("units", {}).get("USD", []):
        if row.get("form") not in FORMS or not all(
            row.get(key) for key in ("start", "end", "filed", "accn")
        ):
            continue
        start: date = date.fromisoformat(row["start"])
        end: date = date.fromisoformat(row["end"])
        filed: date = date.fromisoformat(row["filed"])
        if (
            filed > cutoff
            or end > cutoff
            or end < date(2023, 1, 1)
            or not 60 <= (end - start).days <= 370
        ):
            continue
        try:
            value: Decimal = Decimal(str(row["val"]))
        except (InvalidOperation, KeyError):
            continue
        if not value.is_finite():
            continue
        result.append(
            Fact(
                start,
                end,
                value,
                row["accn"],
                filed,
                row["form"],
                "us-gaap:" + rule.concept,
                str(concept.get("label", rule.label)),
                rule.scope,
                source_id,
                document_url(entity, row["accn"], submissions),
            )
        )
    return result


def latest(facts: list[Fact]) -> tuple[Fact | None, str | None]:
    """Reject conflicting values in the latest presentation instead of choosing an older version."""
    if not facts:
        return None, None
    newest: Fact = max(facts, key=lambda fact: (fact.filed_date, fact.accession))
    values: set[Decimal] = {
        fact.value
        for fact in facts
        if (fact.filed_date, fact.accession) == (newest.filed_date, newest.accession)
    }
    if len(values) != 1:
        return (
            None,
            "Conflicting USD values in the latest filing; manual review required.",
        )
    return newest, None


def quarter_field(
    facts: list[Fact], rule: Rule, start: date, end: date, year_start: date
) -> tuple[str | None, dict]:
    """Prefer reported quarters; derive only matching YTD contexts from the same filing."""
    detail: dict = {
        "label": rule.label,
        "scope": rule.scope,
        "status": "missing",
        "source_ids": [],
        "derivation_inputs": [],
        "reason": None,
    }
    current: Fact | None
    error: str | None
    current, error = latest([fact for fact in facts if fact.start == start and fact.end == end])
    if error:
        detail["reason"] = error
        return None, detail
    inputs: list[Fact] = []
    value: Decimal | None = None
    if current is not None:
        inputs = [current]
        value = current.value
        detail["status"] = "reported"
    elif start != year_start:
        current, error = latest(
            [fact for fact in facts if fact.start == year_start and fact.end == end]
        )
        if error:
            detail["reason"] = error
            return None, detail
        if current is not None:
            previous: Fact | None
            previous, error = latest(
                [
                    fact
                    for fact in facts
                    if fact.start == year_start
                    and fact.end == start - timedelta(days=1)
                    and fact.accession == current.accession
                ]
            )
            inputs = [current]
            if previous is not None:
                inputs.append(previous)
                value = current.value - previous.value
                detail["status"] = "derived"
            else:
                detail["reason"] = (
                    error
                    or "Prior YTD is not in the same filing and scope; no cross-filing inference."
                )
    if value is None and detail["reason"] is None:
        detail["reason"] = (
            "No eligible reported period or same-filing YTD pair for this concept and USD."
        )
    if value is not None and rule is not CFO and value < 0:
        value = None
        detail["status"] = "missing"
        detail["reason"] = "Negative cash expenditure or debt flow requires manual scope review."
    detail["source_ids"] = sorted({fact.source_id for fact in inputs})
    detail["derivation_inputs"] = [fact.reference() for fact in inputs]
    return str(value) if value is not None else None, detail


def extract_entity(
    entity: dict, facts_payload: dict, submissions: dict, cutoff: date, source_id: str
) -> tuple[list[dict], dict]:
    """Build a quarter grid and explicit coverage limits from the latest permitted presentations."""
    rules: dict[str, Rule] = RULES[entity["id"]]
    facts: dict[str, list[Fact]] = {
        key: read_facts(facts_payload, rule, entity, submissions, cutoff, source_id)
        for key, rule in rules.items()
    }
    all_facts: list[Fact] = [fact for values in facts.values() for fact in values]
    windows: dict[date, tuple[date, date, int, int]] = {
        fact.end: window
        for fact in all_facts
        if (window := fiscal_window(fact.end, entity["fiscal_year_end"])) is not None
    }
    periods: list[dict] = []
    if windows:
        end: date = max(windows)
        first: date = date(2024, 1, 1)
        month: date = date(first.year, first.month, 1)
        while month <= end:
            candidate_end: date = month_shift(month, 1) - timedelta(days=1)
            window: tuple[date, date, int, int] | None = fiscal_window(
                candidate_end, entity["fiscal_year_end"]
            )
            if window is not None and window[1] >= first and candidate_end <= end:
                year_start: date
                start: date
                year: int
                quarter: int
                year_start, start, year, quarter = window
                row: dict = {
                    "entity_id": entity["id"],
                    "start": start.isoformat(),
                    "end": candidate_end.isoformat(),
                    "fiscal_year": year,
                    "fiscal_quarter": quarter,
                    "presentation": "reported_quarter",
                    "duration_months": 3,
                    "currency": "USD",
                    "fields": {},
                }
                key: str
                for key, rule in rules.items():
                    value, detail = quarter_field(
                        facts[key], rule, start, candidate_end, year_start
                    )
                    row[key] = value
                    row["fields"][key] = detail
                if any(field["status"] == "derived" for field in row["fields"].values()):
                    row["presentation"] = "derived_quarter"
                periods.append(row)
                if quarter > 1 and year_start >= first:
                    reported: dict = {
                        **row,
                        "start": year_start.isoformat(),
                        "presentation": "reported_annual" if quarter == 4 else "reported_ytd",
                        "duration_months": quarter * 3,
                        "fields": {},
                    }
                    for key, rule in rules.items():
                        value, detail = quarter_field(
                            facts[key], rule, year_start, candidate_end, year_start
                        )
                        reported[key] = value
                        reported["fields"][key] = detail
                    if any(reported[key] is not None for key in FIELDS):
                        periods.append(reported)
            month = month_shift(month, 1)
    populated: int = sum(any(row[key] is not None for key in FIELDS) for row in periods)
    limitations: list[str] = [
        "Named entity-wide us-gaap USD concepts; periods starting in 2024 or later.",
        "Missing is not zero. Custom tags and foreign-interim 6-Ks are not inferred.",
        "YTD subtraction needs the same filing, concept, USD and fiscal-year start.",
        "Debt cash proceeds can include loans. They are not gross bond or AI issuance.",
    ]
    if entity["id"] == "NBIS":
        limitations.append(
            "USD annual 20-F facts exist. Annual totals and legacy RUB do not imply quarters."
        )
    if entity["id"] == "AMZN":
        limitations.append(
            "Recent capex uses a custom tag; the standard PPE concept stays missing."
        )
    if entity["id"] == "GOOGL":
        limitations.append(
            "The combined debt-and-capital-lease repayment tag is excluded from pure debt."
        )
    if entity["id"] == "META":
        limitations.append("No eligible debt repayment fact is not evidence of zero repayments.")
    for key in FIELDS:
        limitations.append(
            f"{key}: {sum(row[key] is not None for row in periods)}/{len(periods)} "
            f"periods populated; {rules[key].scope}."
        )
    coverage: dict = {
        "entity_id": entity["id"],
        "dataset": "cashflows",
        "window_start": "2024-01-01",
        "window_end": cutoff.isoformat(),
        "status": "complete_for_stated_scope"
        if periods and all(row[key] is not None for row in periods for key in FIELDS)
        else "partial"
        if populated
        else "unavailable",
        "limitations": limitations,
        "source_ids": [source_id],
    }
    return periods, coverage


def validate_snapshot(snapshot: dict) -> None:
    """Validate structure, dates, references and uniqueness before writing or rendering."""
    schema: dict = json.loads((HERE / "snapshot.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(snapshot)
    cutoff: str = snapshot["cutoff_date"]
    source_ids: set[str] = {source["id"] for source in snapshot["sources"]}
    if len(source_ids) != len(snapshot["sources"]):
        raise ValueError("Duplicate source IDs; keep one exact evidence record per ID")
    entity_ids: set[str] = {entity["id"] for entity in snapshot["entities"]}
    if len(entity_ids) != len(snapshot["entities"]):
        raise ValueError("Duplicate entity IDs")
    seen: set[tuple[str, str, str]] = set()
    row: dict
    for row in snapshot["fiscal_periods"]:
        identity: tuple[str, str, str] = (row["entity_id"], row["start"], row["end"])
        if (
            identity in seen
            or row["entity_id"] not in entity_ids
            or not row["start"] <= row["end"] <= cutoff
        ):
            raise ValueError("Duplicate, unknown-entity or post-cutoff fiscal period")
        seen.add(identity)
        key: str
        for key in FIELDS:
            detail: dict = row["fields"][key]
            if not set(detail["source_ids"]) <= source_ids:
                raise ValueError("Unknown cash-flow source reference")
            if (row[key] is None) != (detail["status"] == "missing"):
                raise ValueError("A missing field must be null with a missing status")
            input_: dict
            for input_ in detail["derivation_inputs"]:
                if input_["filed_date"] > cutoff or input_["source_id"] not in source_ids:
                    raise ValueError("Post-cutoff or unreferenced calculation input")
    source: dict
    for source in snapshot["sources"]:
        if source["filed_date"] is not None and source["filed_date"] > cutoff:
            raise ValueError("A source was filed after the snapshot cutoff")
    for row in snapshot["spgi_periods"]:
        if row["end"] > cutoff or row["start"] > row["end"]:
            raise ValueError("Invalid or post-cutoff SPGI period")
        references: list[str]
        for references in row["source_refs"].values():
            if not set(references) <= source_ids:
                raise ValueError("Unknown SPGI source reference")
    group: str
    event_ids: set[str] = set()
    for group in ("bond_events", "other_financings", "coverage"):
        for row in snapshot[group]:
            if group != "coverage":
                if row["id"] in event_ids:
                    raise ValueError("Duplicate financing event ID; do not double-count a deal")
                event_ids.add(row["id"])
            if row["entity_id"] not in entity_ids:
                raise ValueError("Unknown supplemental entity")
            if not set(row.get("source_ids", [])) <= source_ids:
                raise ValueError("Unknown supplemental evidence reference")
            if (
                group == "bond_events"
                and row["status"] == "closed"
                and (row["closing_date"] is None or row["closing_date"] > cutoff)
            ):
                raise ValueError("Closed issuance needs an on-or-before-cutoff closing date")
            if group == "bond_events" and row["status"] == "closed":
                if row["face_amount"] is None or Decimal(row["face_amount"]) <= 0:
                    raise ValueError("Closed bond principal must be positive")
                tranches: list[dict] = row["maturities"]
                if (
                    tranches
                    and all(tranche.get("face_amount") is not None for tranche in tranches)
                    and sum((Decimal(tranche["face_amount"]) for tranche in tranches), Decimal(0))
                    != Decimal(row["face_amount"])
                ):
                    raise ValueError(
                        "Tranche principal must sum to the event's native-currency face amount"
                    )


def fetch(url: str, target: Path, identity: str) -> tuple[dict, dict]:
    """Cache a bounded SEC JSON response beside the report and record its actual hash."""
    if not target.exists():
        request: Request = Request(
            url, headers={"User-Agent": identity, "Accept-Encoding": "identity"}
        )
        with urlopen(request, timeout=30) as response:
            body: bytes = response.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024:
            raise ValueError("SEC response exceeded 16 MiB; review the source before retrying")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        time.sleep(0.3)
    body = target.read_bytes()
    payload: dict = json.loads(body)
    source: dict = {
        "id": target.stem,
        "url": url,
        "accession": None,
        "filed_date": None,
        "retrieved_at": datetime.fromtimestamp(target.stat().st_mtime, UTC).isoformat(),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    return payload, source


def collect(output_dir: Path, cutoff: date, supplements: list[Path]) -> dict:
    """Create one bounded eight-issuer snapshot, merging only explicitly supplied supplements."""
    identity: str = os.environ.get("EDGAR_IDENTITY", "")
    if "@" not in identity:
        raise ValueError("EDGAR_IDENTITY must include a SEC contact email; configure it and retry")
    snapshot: dict = {
        "schema_version": 1,
        "cutoff_date": cutoff.isoformat(),
        "entities": COHORT.copy(),
        "fiscal_periods": [],
        "bond_events": [],
        "other_financings": [],
        "spgi_periods": [],
        "coverage": [],
        "sources": [],
    }
    raw_dir: Path = output_dir / "research" / "sec"
    entity: dict
    facts: dict
    source: dict
    submissions: dict
    submission_source: dict
    rows: list[dict]
    coverage: dict
    for entity in COHORT:
        ticker: str = entity["id"]
        cik: str = entity["cik"]
        try:
            facts, source = fetch(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                raw_dir / f"{ticker}-facts.json",
                identity,
            )
            submissions, submission_source = fetch(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                raw_dir / f"{ticker}-submissions.json",
                identity,
            )
            snapshot["sources"] += [source, submission_source]
            rows, coverage = extract_entity(entity, facts, submissions, cutoff, source["id"])
            coverage["source_ids"].append(submission_source["id"])
            snapshot["fiscal_periods"] += rows
            snapshot["coverage"].append(coverage)
            print(
                f"{ticker}: {len(rows)} fiscal periods; {coverage['status']}",
                file=sys.stderr,
            )
        except (HTTPError, URLError) as error:
            snapshot["coverage"].append(
                {
                    "entity_id": ticker,
                    "dataset": "cashflows",
                    "window_start": "2024-01-01",
                    "window_end": cutoff.isoformat(),
                    "status": "unavailable",
                    "limitations": [
                        f"SEC retrieval failed ({type(error).__name__}); retry with valid access."
                    ],
                    "source_ids": [],
                }
            )
    supplement_path: Path
    for supplement_path in supplements:
        supplement: dict = json.loads(supplement_path.read_text())
        for key in (
            "entities",
            "bond_events",
            "other_financings",
            "spgi_periods",
            "coverage",
            "sources",
        ):
            snapshot[key] += supplement.get(key, [])
    if snapshot["spgi_periods"]:
        snapshot["entities"].append(
            {
                "id": "SPGI",
                "ticker": "SPGI",
                "name": "S&P Global",
                "cik": "0000064040",
                "category": "ratings_source",
            }
        )
    row: dict
    for row in snapshot["other_financings"]:
        if row["entity_id"] not in {item["id"] for item in snapshot["entities"]}:
            snapshot["entities"].append(
                {
                    "id": row["entity_id"],
                    "ticker": None,
                    "name": row["entity_id"].title(),
                    "cik": None,
                    "category": "neocloud",
                }
            )
    row: dict
    for key in ("sources", "entities"):
        unique: dict[str, dict] = {}
        for row in snapshot[key]:
            if row["id"] in unique and unique[row["id"]] != row:
                raise ValueError(
                    f"Conflicting {key} ID {row['id']}; resolve the supplement and retry"
                )
            unique[row["id"]] = row
        snapshot[key] = list(unique.values())
    validate_snapshot(snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    return snapshot


def main() -> None:
    """Write a validated snapshot; diagnostics use stderr and stdout remains machine-readable."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Ignored self-contained report folder",
    )
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=date(2026, 10, 20),
        help="Inclusive filing-date cutoff (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--events", type=Path, help="Explicitly reviewed bond-events JSON supplement"
    )
    parser.add_argument("--spgi", type=Path, help="Verified SPGI quarterly JSON supplement")
    args: argparse.Namespace = parser.parse_args()
    try:
        snapshot: dict = collect(
            args.output_dir,
            args.cutoff,
            [path for path in (args.events, args.spgi) if path is not None],
        )
    except (ValueError, OSError) as error:
        print(
            f"Collection failed: {error}. Review inputs and retry; cached sources remain.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "snapshot": str(args.output_dir / "snapshot.json"),
                "entities": len(snapshot["entities"]),
                "fiscal_periods": len(snapshot["fiscal_periods"]),
            }
        )
    )


if __name__ == "__main__":
    main()
