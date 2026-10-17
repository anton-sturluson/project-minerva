"""Append and read immutable annual financial publications in PostgreSQL."""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from investor_platform.financials.bundles import SCHEMA, validate_capital_spending
from investor_platform.financials.calculations import calculations
from investor_platform.financials.types import Json, Record, Row, Value, digest, record, records

VERSION: str = "annual-financial-v2"


def relation(schema: str, table: str) -> sql.Identifier:
    """Limit financial operations to explicitly named isolated financial namespaces."""
    if not re.fullmatch(r"investor_financial_[a-z][a-z0-9_]{0,43}", schema):
        raise ValueError(
            "Use an explicit investor_financial_<name> schema; legacy schemas are refused"
        )
    return sql.Identifier(schema, table)


def check_schema(conn: Connection[Row], schema: str, create: bool = False) -> None:
    """Initialize a fresh namespace or require the exact known financial schema version."""
    relation(schema, "companies")
    if create:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (schema,))
    existing: Row | None = conn.execute(
        "SELECT obj_description(oid, 'pg_namespace') AS version FROM pg_namespace WHERE nspname=%s",
        (schema,),
    ).fetchone()
    if existing:
        if existing["version"] != VERSION:
            raise ValueError("Unknown existing schema; choose a fresh financial namespace")
        return
    if not create:
        raise ValueError(
            "Financial schema missing; import a reviewed bundle into a fresh namespace"
        )
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    ddl: str = Path(__file__).with_name("financial_schema.sql").read_text()
    conn.execute(sql.SQL(ddl).format(schema=sql.Identifier(schema)))
    conn.execute(
        sql.SQL("COMMENT ON SCHEMA {} IS {}").format(sql.Identifier(schema), sql.Literal(VERSION))
    )


def identifier(conn: Connection[Row], query: sql.Composed, params: tuple[Value, ...]) -> int:
    """Fetch an existing or inserted normalized identity."""
    row: Row | None = conn.execute(query, params).fetchone()
    if row is None:
        raise ValueError("Financial identity missing; review the target schema")
    return int(cast(int, row["id"]))


def import_bundle(conn: Connection[Row], schema: str, bundle: Record, reviewed: bool) -> Record:
    """Append one validated bundle atomically; identical UUID replay is idempotent."""
    with conn.transaction():
        return _append_bundle(conn, schema, bundle, reviewed)


def _append_bundle(conn: Connection[Row], schema: str, bundle: Record, reviewed: bool) -> Record:
    """Persist the normalized rows within the caller's locked admission transaction."""
    Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).validate(
        bundle
    )
    validate_capital_spending(bundle)
    check_schema(conn, schema, create=True)
    bundle_id: str = str(bundle["bundle_id"])
    status: str = "reviewed" if reviewed else "candidate"
    checksum: str = digest(bundle)
    previous: Row | None = conn.execute(
        sql.SQL("SELECT bundle_sha256, review_status FROM {} WHERE bundle_id=%s").format(
            relation(schema, "publications")
        ),
        (bundle_id,),
    ).fetchone()
    if previous:
        if previous["bundle_sha256"] != checksum or previous["review_status"] != status:
            raise ValueError(
                "Bundle UUID conflicts with saved content/review; use a new revision UUID"
            )
        return {"bundle_id": bundle_id, "status": "unchanged", "review_status": status}
    issuer: Record = record(bundle["issuer"])
    conn.execute(
        sql.SQL(
            "INSERT INTO {} (issuer_key,name) VALUES (%s,%s) ON CONFLICT (issuer_key) DO NOTHING"
        ).format(relation(schema, "companies")),
        (issuer["issuer_key"], issuer["name"]),
    )
    company_id: int = identifier(
        conn,
        sql.SQL("SELECT id FROM {} WHERE issuer_key=%s").format(relation(schema, "companies")),
        (issuer["issuer_key"],),
    )
    period: Record = record(bundle["period"])
    conn.execute(
        sql.SQL(
            "INSERT INTO {} (company_id,fiscal_year,fiscal_label,period_start,period_end) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (company_id,period_start,period_end) DO NOTHING"
        ).format(relation(schema, "periods")),
        (company_id, period["fiscal_year"], period["fiscal_label"], period["start"], period["end"]),
    )
    period_id: int = identifier(
        conn,
        sql.SQL(
            "SELECT id FROM {} WHERE company_id=%s AND period_start=%s AND period_end=%s"
        ).format(relation(schema, "periods")),
        (company_id, period["start"], period["end"]),
    )
    saved_period: Row | None = conn.execute(
        sql.SQL("SELECT fiscal_year,fiscal_label FROM {} WHERE id=%s").format(
            relation(schema, "periods")
        ),
        (period_id,),
    ).fetchone()
    if (
        not saved_period
        or saved_period["fiscal_year"] != period["fiscal_year"]
        or (saved_period["fiscal_label"] != period["fiscal_label"])
    ):
        raise ValueError("Fiscal identity conflicts; review the existing issuer-period label")
    conn.execute(
        sql.SQL(
            "INSERT INTO {} "
            "(bundle_id,period_id,bundle_sha256,review_status,issuer,capital_spending) "
            "VALUES (%s,%s,%s,%s,%s,%s)"
        ).format(relation(schema, "publications")),
        (
            bundle_id,
            period_id,
            checksum,
            status,
            Jsonb(issuer),
            Jsonb(bundle["capital_spending"]) if "capital_spending" in bundle else None,
        ),
    )
    source: Record
    for source in records(bundle["sources"]):
        conflicting_date: Row | None = conn.execute(
            sql.SQL(
                "SELECT published_on FROM {} WHERE company_id=%s AND document_id=%s "
                "AND content_sha256=%s AND published_on<>%s LIMIT 1"
            ).format(relation(schema, "sources")),
            (company_id, source["document_id"], source["content_sha256"], source["published_on"]),
        ).fetchone()
        if conflicting_date:
            raise ValueError(
                "Source publication date conflicts; preserve the original document publication date"
            )
        conn.execute(
            sql.SQL(
                "INSERT INTO {} "
                "(company_id,document_id,url,published_on,retrieved_at,content_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT "
                "(company_id,document_id,content_sha256,retrieved_at) DO NOTHING"
            ).format(relation(schema, "sources")),
            (
                company_id,
                source["document_id"],
                source["url"],
                source["published_on"],
                source["retrieved_at"],
                source["content_sha256"],
            ),
        )
        source_db_id: int = identifier(
            conn,
            sql.SQL(
                "SELECT id FROM {} WHERE company_id=%s AND document_id=%s AND url=%s "
                "AND published_on=%s AND retrieved_at=%s AND content_sha256=%s"
            ).format(relation(schema, "sources")),
            (
                company_id,
                source["document_id"],
                source["url"],
                source["published_on"],
                source["retrieved_at"],
                source["content_sha256"],
            ),
        )
        conn.execute(
            sql.SQL("INSERT INTO {} VALUES (%s,%s,%s)").format(
                relation(schema, "publication_sources")
            ),
            (bundle_id, source["source_id"], source_db_id),
        )
    key: str
    raw: Json
    for key, raw in record(bundle["facts"]).items():
        fact: Record = record(raw)
        conn.execute(
            sql.SQL(
                "INSERT INTO {} VALUES (%s,%s,%s,%s) ON CONFLICT (metric_key) DO NOTHING"
            ).format(relation(schema, "metrics")),
            (key, fact["unit"], fact["entity_scope"], fact["measurement_basis"]),
        )
        conn.execute(
            sql.SQL(
                "INSERT INTO {} "
                "(bundle_id,metric_key,value,status,source_id,locator,reason,share_basis) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            ).format(relation(schema, "observations")),
            (
                bundle_id,
                key,
                Decimal(str(fact["value"])) if "value" in fact else None,
                fact["status"],
                fact.get("source_id"),
                Jsonb(fact["locator"]) if "locator" in fact else None,
                fact.get("reason"),
                Jsonb(fact["share_basis"]) if "share_basis" in fact else None,
            ),
        )
    return {"bundle_id": bundle_id, "status": "imported", "review_status": status}


def show(conn: Connection[Row], schema: str, issuer_key: str, calendar_year: int) -> Record:
    """Read one coherent publication, preferring the latest reviewed version over candidates."""
    check_schema(conn, schema)
    row: Row | None = conn.execute(
        sql.SQL(
            "SELECT b.*, p.fiscal_year,p.fiscal_label,p.period_start,p.period_end "
            "FROM {} b JOIN {} p ON p.id=b.period_id JOIN {} c ON c.id=p.company_id "
            "WHERE c.issuer_key=%s AND EXTRACT(YEAR FROM p.period_end)=%s "
            "ORDER BY (b.review_status='reviewed') DESC,b.imported_at DESC,b.bundle_id DESC LIMIT 1"
        ).format(
            relation(schema, "publications"),
            relation(schema, "periods"),
            relation(schema, "companies"),
        ),
        (issuer_key, calendar_year),
    ).fetchone()
    if row is None:
        raise ValueError("Issuer/year missing; import its annual bundle into this schema first")
    bundle_id: str = str(row["bundle_id"])
    facts: dict[str, Record] = {}
    saved: Row
    for saved in conn.execute(
        sql.SQL(
            "SELECT o.*,m.unit,m.entity_scope,m.measurement_basis FROM {} o "
            "JOIN {} m USING (metric_key) WHERE bundle_id=%s ORDER BY metric_key"
        ).format(relation(schema, "observations"), relation(schema, "metrics")),
        (bundle_id,),
    ):
        fact: Record = {
            "observation_id": str(saved["id"]),
            "status": str(saved["status"]),
            "unit": str(saved["unit"]),
            "entity_scope": str(saved["entity_scope"]),
            "measurement_basis": str(saved["measurement_basis"]),
        }
        field: str
        for field in ("value", "source_id", "locator", "reason", "share_basis"):
            if saved[field] is not None:
                fact[field] = (
                    format(cast(Decimal, saved[field]), "f")
                    if field == "value"
                    else cast(Json, saved[field])
                )
        facts[str(saved["metric_key"])] = fact
    sources: list[Row] = conn.execute(
        sql.SQL(
            "SELECT ps.source_id,s.document_id,s.url,s.published_on,"
            "s.retrieved_at,s.content_sha256 "
            "FROM {} ps JOIN {} s ON s.id=ps.document_source_id "
            "WHERE bundle_id=%s ORDER BY source_id"
        ).format(relation(schema, "publication_sources"), relation(schema, "sources")),
        (bundle_id,),
    ).fetchall()
    issuer: Record = cast(Record, row["issuer"])
    return {
        "bundle_id": bundle_id,
        "review_status": str(row["review_status"]),
        "issuer": issuer,
        "period": {
            "kind": "year",
            "fiscal_year": cast(int, row["fiscal_year"]),
            "fiscal_label": str(row["fiscal_label"]),
            "start": str(row["period_start"]),
            "end": str(row["period_end"]),
        },
        "sources": cast(
            Json,
            [
                {
                    key: value.isoformat() if isinstance(value, (date, datetime)) else str(value)
                    for key, value in source.items()
                }
                for source in sources
            ],
        ),
        "facts": cast(Json, facts),
        "capital_spending": cast(Json, row["capital_spending"]),
        "calculations": calculations(
            facts,
            issuer["business_type"] == "insurer",
            cast(Record | None, row["capital_spending"]),
            bundle_id,
        ),
    }
