"""Store reviewed financial history without changing the annual-only observation model."""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from .financial import Json, Record, Row, check_schema, digest, record, records

VERSION: str = "portfolio-financial-history-v1"
METRICS: tuple[str, ...] = (
    "gross_margin",
    "operating_margin",
    "fcf_margin_after_disclosed_capex",
    "basic_eps",
    "fcf_per_basic_share",
)


def fund_listings(release: Record | None) -> set[tuple[str, str]]:
    """Identify funds only from the reviewed release's explicit classifications."""
    return (
        {
            (str(row["ticker"]), str(row["exchange"]))
            for row in records(release["records"])
            if row["instrument_type"] == "fund"
        }
        if release
        else set()
    )


def number(value: object) -> Decimal:
    """Require a finite decimal string without silently rounding source data."""
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        raise ValueError("Financial values must be decimal strings")
    return Decimal(value)


def resolve(document: Record, identifier: str) -> Record:
    """Resolve a source observation/calculation ID or an exact JSON pointer."""
    if identifier.startswith("#/"):
        value: object = document
        for token in identifier[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                value = value[int(token)]
            elif isinstance(value, dict):
                value = value[token]
            else:
                raise ValueError("Invalid financial evidence pointer")
        return record(value)
    group: str
    for group in ("observations", "calculated_metrics"):
        item: Record
        for item in records(document.get(group, [])):
            if item.get("id", item.get("observation_id", item.get("calculation_id"))) == identifier:
                return item
    raise ValueError("Unresolved financial evidence reference")


def validate_release(release: Record) -> None:
    """Check the bounded admission contract and exact reviewed evidence bytes."""
    if release.get("schema_version") != VERSION:
        raise ValueError("Unsupported financial history release")
    UUID(str(release["release_id"]))
    receipts: list[Record] = records(release["review_receipts"])
    if not receipts:
        raise ValueError("Financial history needs independent review receipts")
    reviewed_hashes: set[str] = set()
    receipt: Record
    for receipt in receipts:
        content: str = str(receipt["content"])
        if hashlib.sha256(content.encode()).hexdigest() != receipt["sha256"]:
            raise ValueError("Review receipt hash does not match")
        record(json.loads(content))
        reviewed_hashes.update(re.findall(r'"([0-9a-f]{64})"', content))
    evidence: Record = record(record(release["evidence"])["packets"])
    documents: dict[str, Record] = {}
    sha: str
    for sha, text in evidence.items():
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != sha:
            raise ValueError("Financial packet hash does not match")
        if sha not in reviewed_hashes:
            raise ValueError("Financial packet is not pinned by an independent review receipt")
        documents[sha] = record(json.loads(text))
    identities: set[tuple[str, str, int]] = set()
    row: Record
    for row in records(release["records"]):
        identity: tuple[str, str, int] = (
            str(row["exchange"]),
            str(row["ticker"]),
            int(str(row["year"])),
        )
        if identity in identities:
            raise ValueError("Duplicate financial listing/year")
        identities.add(identity)
        if row.get("instrument_type") not in {"company", "fund"}:
            raise ValueError("Unsupported financial instrument classification")
        if not re.fullmatch(r"[A-Z]{3}", str(row["currency"])):
            raise ValueError("Financial reporting currency is required")
        if row.get("shares_per_traded_unit") is not None:
            if number(row["shares_per_traded_unit"]) <= 0 or not row.get("share_basis"):
                raise ValueError("Traded share conversion needs verified positive units")
        if row["instrument_type"] == "fund":
            continue
        key: str
        for key in ("period", "prior_period"):
            period: Record = record(row[key])
            start: date = date.fromisoformat(str(period["start"]))
            end: date = date.fromisoformat(str(period["end"]))
            if not 350 <= (end - start).days + 1 <= 380:
                raise ValueError("Financial comparison requires a complete annual/LTM period")
        if str(record(row["prior_period"])["end"]) >= str(record(row["period"])["start"]):
            raise ValueError("Prior financial period overlaps the selected period")
        for key in ("metrics", "prior_metrics"):
            metrics: Record = record(row[key])
            if set(metrics) != set(METRICS):
                raise ValueError("Financial history requires exactly five bounded measures")
            metric_key: str
            metric_value: Json
            for metric_key, metric_value in metrics.items():
                metric: Record = record(metric_value)
                eps_basis: Json = metric.get("eps_basis")
                denominator_basis: Json = metric.get("share_denominator_basis")
                if denominator_basis is not None and (
                    metric_key != "fcf_per_basic_share"
                    or denominator_basis
                    not in ("basic_weighted_average", "diluted_weighted_average", "period_end")
                ):
                    raise ValueError("Share denominator basis applies only to FCF/share")
                if eps_basis is not None and (
                    metric_key != "basic_eps" or eps_basis not in ("basic", "diluted")
                ):
                    raise ValueError("EPS basis applies only to the company EPS measure")
                convention: Json = metric.get("convention")
                if convention is not None and (
                    convention != "zero_revenue_margin"
                    or metric_key not in METRICS[:3]
                    or metric.get("status") != "available"
                    or number(metric.get("value")) != 0
                ):
                    raise ValueError(
                        "Zero-revenue convention applies only to available zero margins"
                    )
                if metric.get("status") == "unavailable":
                    if metric.get("value") is not None or not metric.get("reason"):
                        raise ValueError("Unavailable financial measures need a reason")
                    continue
                if metric.get("status") != "available":
                    raise ValueError("Unsupported financial measure status")
                number(metric["value"])
                inputs: list[Record] = records(metric["inputs"])
                if not inputs or not metric.get("method"):
                    raise ValueError("Available financial measures need input proof and method")
                zero_revenue_proof: bool = False
                expected_period: Record = record(
                    row["period" if key == "metrics" else "prior_period"]
                )
                proof: Record
                for proof in inputs:
                    document: Record = documents[str(proof["packet_sha256"])]
                    identifiers: object = proof["ids"]
                    if not isinstance(identifiers, list) or not identifiers:
                        raise ValueError("Financial evidence needs exact input IDs")
                    for identifier in identifiers:
                        node: Record = resolve(document, str(identifier))
                        if convention is not None and (
                            node.get("metric") == "revenue"
                            and node.get("value") is not None
                            and number(node["value"]) == 0
                            and node.get("period_start") == expected_period["start"]
                            and node.get("period_end") == expected_period["end"]
                        ):
                            zero_revenue_proof = True
                if convention is not None and not zero_revenue_proof:
                    raise ValueError(
                        "Zero-revenue convention needs exact-period verified zero revenue"
                    )


def history_table(schema: str) -> sql.Composed:
    """Restrict history to the existing explicitly configured financial namespace."""
    if not re.fullmatch(r"investor_financial_[a-z][a-z0-9_]{0,47}", schema):
        raise ValueError("Use an explicit investor_financial namespace")
    return sql.SQL("{}.history_releases").format(sql.Identifier(schema))


def import_release(
    conn: Connection[Row], schema: str, release: Record, *, reviewed: bool = False
) -> Record:
    """Append one independently reviewed release atomically; repeat UUIDs cannot change."""
    if not reviewed:
        raise ValueError("Independent admission review is required")
    validate_release(release)
    table: sql.Composed = history_table(schema)
    sha: str = digest(release)
    with conn.transaction():
        check_schema(conn, schema)
        exists: Row | None = conn.execute(
            "SELECT obj_description(to_regclass(%s), 'pg_class') AS marker",
            (f"{schema}.history_releases",),
        ).fetchone()
        if exists is not None and exists["marker"] is not None:
            if exists["marker"] != VERSION:
                raise ValueError("Unsupported existing history table")
        else:
            # Do not adopt an unmarked table, even inside a valid annual namespace.
            present: Row | None = conn.execute(
                "SELECT to_regclass(%s) AS name", (f"{schema}.history_releases",)
            ).fetchone()
            if present and present["name"] is not None:
                raise ValueError("Unmarked financial history table")
            conn.execute(
                sql.SQL(
                    "CREATE TABLE {} (release_id uuid PRIMARY KEY, content_sha256 text NOT NULL, "
                    "imported_at timestamptz NOT NULL DEFAULT clock_timestamp(), "
                    "payload jsonb NOT NULL)"
                ).format(table)
            )
            conn.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(table, sql.Literal(VERSION)))
            conn.execute(
                sql.SQL(
                    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {} FOR EACH ROW "
                    "EXECUTE FUNCTION {}.reject_observation_change()"
                ).format(table, sql.Identifier(schema))
            )
        previous: Row | None = conn.execute(
            sql.SQL("SELECT content_sha256 FROM {} WHERE release_id=%s").format(table),
            (release["release_id"],),
        ).fetchone()
        if previous:
            if previous["content_sha256"] != sha:
                raise ValueError("Financial release UUID already identifies different evidence")
            return {"release_id": release["release_id"], "sha256": sha, "created": False}
        conn.execute(
            sql.SQL("INSERT INTO {} (release_id,content_sha256,payload) VALUES (%s,%s,%s)").format(
                table
            ),
            (release["release_id"], sha, Jsonb(release)),
        )
    return {"release_id": release["release_id"], "sha256": sha, "created": True}


def read_release(conn: Connection[Row], schema: str) -> Record | None:
    """Read the latest reviewed import without bootstrapping or touching source files."""
    check_schema(conn, schema)
    marker: Row | None = conn.execute(
        "SELECT obj_description(to_regclass(%s), 'pg_class') AS marker",
        (f"{schema}.history_releases",),
    ).fetchone()
    if not marker or marker["marker"] != VERSION:
        return None
    result: Row | None = conn.execute(
        sql.SQL("SELECT payload FROM {} ORDER BY imported_at DESC,release_id DESC LIMIT 1").format(
            history_table(schema)
        )
    ).fetchone()
    return record(result["payload"]) if result else None
