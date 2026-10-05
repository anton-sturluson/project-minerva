"""Shared company financial inputs; portfolio tables and credentials are separate."""

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SCHEMA_VERSION = "minerva-financial-inputs-v1"
CORE_TABLES = ("companies", "metrics", "company_periods", "metric_values")


def connect(*, readonly=False):
    dsn = os.environ.get("INVESTOR_DATA_DATABASE_URL")
    if not dsn:
        raise ValueError("Set INVESTOR_DATA_DATABASE_URL explicitly; no database fallback is used")
    conn = psycopg.connect(
        dsn.replace("postgresql+psycopg://", "postgresql://", 1),
        row_factory=dict_row,
        connect_timeout=5,
    )
    conn.read_only = readonly
    return conn


def relation(schema, table):
    if not re.fullmatch(r"investor_data(?:_[a-z0-9]+)*", schema):
        raise ValueError("Use investor_data or an investor_data_<suffix> namespace")
    return sql.Identifier(schema, table)


def initialize(conn, schema):
    relation(schema, "companies")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (schema,))
    existing = conn.execute(
        "SELECT obj_description(oid, 'pg_namespace') AS version "
        "FROM pg_namespace WHERE nspname = %s",
        (schema,),
    ).fetchone()
    if existing:
        if existing["version"] != SCHEMA_VERSION:
            raise ValueError("Target namespace already exists without the expected schema version")
        return
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    ddl = Path(__file__).with_name("financial_schema.sql").read_text()
    conn.execute(sql.SQL(ddl).format(schema=sql.Identifier(schema)))
    conn.execute(
        sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
            sql.Identifier(schema), sql.Literal(SCHEMA_VERSION)
        )
    )


def wire(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, UUID)):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    raise TypeError(type(value).__name__)


def source_id(reference):
    return uuid5(NAMESPACE_URL, reference)


def company_rows(conn, schema, ticker=None):
    query = sql.SQL("SELECT * FROM {} ").format(relation(schema, "companies"))
    if ticker is not None:
        query += sql.SQL("WHERE ticker = %s ")
    return conn.execute(
        query + sql.SQL("ORDER BY id LIMIT 500"), (ticker,) if ticker is not None else ()
    ).fetchall()


def history_rows(conn, schema, company_id, metric_key=None, scenario="actual", limit=100):
    if not 1 <= limit <= 500:
        raise ValueError("History limit must be between 1 and 500")
    query = sql.SQL("SELECT * FROM {} WHERE company_id = %s AND scenario = %s ").format(
        relation(schema, "metric_values_flat")
    )
    parameters = [company_id, scenario]
    if metric_key is not None:
        query += sql.SQL("AND metric_key = %s ")
        parameters.append(metric_key)
    query += sql.SQL("ORDER BY period_end DESC, metric_key, id LIMIT %s")
    parameters.append(limit)
    rows = conn.execute(query, parameters).fetchall()
    return sorted(rows, key=lambda row: (row["period_end"], row["metric_key"], row["id"]))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeriodInput(Input):
    period_kind: Literal["year", "quarter", "ytd"]
    fiscal_year: int
    fiscal_quarter: Annotated[int, Field(ge=1, le=4)] | None = None
    fiscal_label: Annotated[str, Field(min_length=1)]
    period_start: date | None = None
    period_end: date

    @model_validator(mode="after")
    def dates_and_kind(self):
        if self.period_start and self.period_start > self.period_end:
            raise ValueError("Period start must not follow its end")
        if self.period_kind == "year" and self.fiscal_quarter is not None:
            raise ValueError("A fiscal year cannot carry a fiscal quarter")
        if self.period_kind == "quarter" and self.fiscal_quarter is None:
            raise ValueError("A quarter needs a fiscal quarter number")
        return self


class SourceInput(Input):
    reference: Annotated[str, Field(min_length=1)]
    url: HttpUrl | None = None
    published_on: date | None = None
    retrieved_at: datetime | None = None
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None

    @field_validator("retrieved_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Retrieval time needs an explicit timezone")
        return value


class ObservationInput(Input):
    metric_key: str
    value: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    value_high: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    value_status: Literal[
        "valid", "unavailable", "not_disclosed", "not_applicable", "unreadable"
    ] = "valid"
    qualifier: Literal["exact", "approx", "gt", "gte", "lt", "lte", "range"] = "exact"
    scenario: Literal["actual", "guidance", "target", "consensus", "estimate"] = "actual"
    origin: Literal["reported", "derived"] = "reported"
    currency_code: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    reported_text: str | None = None
    source: SourceInput | None = None
    source_locator: str | None = None
    calculation_note: str | None = None

    @field_validator("value", "value_high", mode="before")
    @classmethod
    def exact_input(cls, value):
        if isinstance(value, float):
            raise ValueError("Send decimal values as strings, not floating-point JSON numbers")
        return value

    @model_validator(mode="after")
    def shape(self):
        if self.value_status == "valid" and self.value is None:
            raise ValueError("A valid observation needs a value")
        if self.qualifier == "range":
            if self.value is None or self.value_high is None or self.value_high < self.value:
                raise ValueError("A range needs ordered lower and upper values")
        elif self.value_high is not None:
            raise ValueError("Only ranges have an upper value")
        if self.origin == "reported" and (
            self.source is None or not self.source_locator or not self.source_locator.strip()
        ):
            raise ValueError("Reported observations need a source and locator")
        if self.origin == "derived" and (
            not self.calculation_note or not self.calculation_note.strip()
        ):
            raise ValueError("Derived observations need a calculation note")
        return self


class ObservationBatch(Input):
    company_id: int
    period: PeriodInput
    observations: Annotated[list[ObservationInput], Field(min_length=1, max_length=100)]


def append_observations(conn, schema, batch):
    """Append or return exact retries; never silently correct an existing observation."""
    periods = relation(schema, "company_periods")
    period = batch.period.model_dump()
    period["company_id"] = batch.company_id
    columns = list(period)
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
            periods,
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        ),
        list(period.values()),
    )
    existing = conn.execute(
        sql.SQL(
            "SELECT * FROM {} WHERE company_id = %s AND period_kind = %s AND period_end = %s"
        ).format(periods),
        (batch.company_id, period["period_kind"], period["period_end"]),
    ).fetchone()
    if existing is None or any(existing[key] != value for key, value in period.items()):
        raise ValueError("The existing fiscal period differs; no dates were replaced")
    counts = {"inserted": 0, "unchanged": 0}
    for observation in batch.observations:
        metric = conn.execute(
            sql.SQL("SELECT * FROM {} WHERE metric_key = %s").format(relation(schema, "metrics")),
            (observation.metric_key,),
        ).fetchone()
        if metric is None:
            raise ValueError("Define the metric before appending observations")
        if metric["value_type"] in {"currency", "per_share"} and observation.value is not None:
            if observation.currency_code is None:
                raise ValueError("Monetary observations need a currency")
        row = observation.model_dump(exclude={"metric_key", "source"})
        row.update(
            metric_id=metric["id"], period_id=existing["id"], source_id=None, source_ref=None
        )
        if observation.source:
            source = observation.source.model_dump()
            source["url"] = str(source["url"]) if source["url"] is not None else None
            source["id"] = source_id(source["reference"])
            columns = list(source)
            conn.execute(
                sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                    relation(schema, "sources"),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                ),
                list(source.values()),
            )
            saved = conn.execute(
                sql.SQL("SELECT * FROM {} WHERE id = %s").format(relation(schema, "sources")),
                (source["id"],),
            ).fetchone()
            if saved is None or any(saved[key] != value for key, value in source.items()):
                raise ValueError("Source metadata differs; use the correct document identity")
            row.update(source_id=source["id"], source_ref=source["reference"])
        columns = list(row)
        inserted = conn.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING RETURNING id").format(
                relation(schema, "metric_values"),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            ),
            list(row.values()),
        ).fetchone()
        if inserted:
            counts["inserted"] += 1
        else:
            saved = conn.execute(
                sql.SQL(
                    "SELECT * FROM {} WHERE metric_id = %s AND period_id = %s AND scenario = %s"
                ).format(relation(schema, "metric_values")),
                (row["metric_id"], row["period_id"], row["scenario"]),
            ).fetchone()
            if saved is None or any(saved[key] != value for key, value in row.items()):
                raise ValueError("Observation conflicts with stored data; correction is explicit")
            counts["unchanged"] += 1
    return counts


def json_result(value):
    return json.dumps(value, default=wire, ensure_ascii=False)


def grant_access(conn, schema, reader, writer):
    """Existing dedicated roles receive no portfolio privileges or verified-state writes."""
    relation(schema, "companies")
    for role, prefix in ((reader, "investor_data_reader"), (writer, "investor_data_writer")):
        if not re.fullmatch(prefix + r"(?:_[a-z0-9]+)*", role):
            raise ValueError("Use dedicated investor_data_reader/writer roles")
        capabilities = conn.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
        if capabilities is None or any(capabilities.values()):
            raise ValueError("Create a dedicated non-administrator role first")
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        for table in (*CORE_TABLES, "sources", "metric_values_flat"):
            conn.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(
                    relation(schema, table), sql.Identifier(role)
                )
            )
    for table in ("company_periods", "sources"):
        conn.execute(
            sql.SQL("GRANT INSERT ON {} TO {}").format(
                relation(schema, table), sql.Identifier(writer)
            )
        )
    columns = (
        "metric_id",
        "period_id",
        "value",
        "value_high",
        "value_status",
        "qualifier",
        "scenario",
        "origin",
        "currency_code",
        "reported_text",
        "source_ref",
        "source_id",
        "source_locator",
        "calculation_note",
    )
    conn.execute(
        sql.SQL("GRANT INSERT ({}) ON {} TO {}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            relation(schema, "metric_values"),
            sql.Identifier(writer),
        )
    )
    for table in ("company_periods", "metric_values"):
        conn.execute(
            sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(
                relation(schema, f"{table}_id_seq"), sql.Identifier(writer)
            )
        )
