"""Validate, append and read bounded annual financial observations."""

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import cast
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from psycopg import Connection, sql
from psycopg.types.json import Jsonb

type Json = str | int | float | bool | None | list[Json] | dict[str, Json]
type Record = dict[str, Json]
type Value = Json | Decimal | date | datetime | UUID
type Row = dict[str, Value]

SCHEMA: Path = Path(__file__).with_name("annual_financial_bundle.schema.json")
VERSION: str = "annual-financial-v2"
FORMULA_VERSION: str = "annual-financial-formulas-v2"


def record(value: Json) -> Record:
    """Require a JSON object before accessing its fields."""
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object; use the annual financial bundle schema")
    return value


def records(value: Json) -> list[Record]:
    """Read an array of JSON objects."""
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array; use the annual financial bundle schema")
    return [record(item) for item in value]


def digest(bundle: Record) -> str:
    """Identify exact bundle content independent of JSON key order or whitespace."""
    return hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()


def unique_object(pairs: list[tuple[str, Json]]) -> Record:
    """Reject duplicate JSON keys instead of silently discarding evidence components."""
    result: Record = {}
    key: str
    value: Json
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key}; retain each component only once")
        result[key] = value
    return result


def validate_capital_spending(bundle: Record) -> None:
    """Require compatible reported components with resolved sources and no duplicated subtotal."""
    if bundle.get("capital_spending") is None:
        return
    spending: Record = record(bundle["capital_spending"])
    schema: Record = cast(Record, json.loads(SCHEMA.read_text()))
    Draft202012Validator(
        {"$ref": "#/$defs/capital_spending", "$defs": schema["$defs"]},
        format_checker=FormatChecker(),
    ).validate(spending)
    components: Record = record(spending["components"])
    keys: set[str] = set(components)
    if (
        "property_equipment_software" in keys
        and len(keys) > 1
        or (
            "ppe" in keys
            and keys & {"equipment", "leasehold_improvements", "other_capital_investments"}
        )
    ):
        raise ValueError("Capital spending subtotal overlaps components; select disjoint cash rows")
    sources: dict[str, Record] = {str(s["source_id"]): s for s in records(bundle["sources"])}
    locations: set[tuple[str, str, str, str, str]] = set()
    tags: set[tuple[str, str, str]] = set()
    key: str
    raw: Json
    for key, raw in components.items():
        fact: Record = record(raw)
        source: Record | None = sources.get(str(fact["source_id"]))
        if source is None:
            raise ValueError(
                f"Unresolved capital spending source for {key}; add its document source"
            )
        locator: Record = record(fact["locator"])
        location: tuple[str, str, str, str, str] = (
            str(source["document_id"]),
            str(source["content_sha256"]),
            str(locator["statement"]).strip().casefold(),
            str(locator["row"]).strip().casefold(),
            str(locator["column"]).strip().casefold(),
        )
        tag: tuple[str, str, str] = (
            str(source["document_id"]),
            str(source["content_sha256"]),
            str(locator.get("xbrl_tag", "")).strip().casefold(),
        )
        if location in locations or tag[2] and tag in tags:
            raise ValueError(
                "Duplicate capital spending source locator/tag; do not count a cash row twice"
            )
        locations.add(location)
        if tag[2]:
            tags.add(tag)


def basic_share_reason(fact: Record) -> str | None:
    """Require reported positive annual basic shares and a supported common-class basis."""
    if fact.get("status") != "reported":
        return "Reported annual basic weighted-average shares are unavailable"
    if Decimal(str(fact["value"])) <= 0:
        return "A positive annual basic-share denominator is required"
    if not fact.get("share_basis"):
        return "Reported common-class and split basis is unavailable"
    basis: Record = record(fact["share_basis"])
    classes: list[Json] = cast(list[Json], basis["classes"])
    if not classes or not basis.get("split_adjusted_through"):
        return "Reported common-class and split basis is unavailable"
    if len(classes) > 1 and not basis.get("equivalence_note"):
        return "Common-class economic equivalence has not been established"
    return None


def disclosed_capex_calculations(
    facts: dict[str, Record],
    spending: Record | None,
    bundle_id: str | None,
) -> Record:
    """Subtract evidenced disclosed capital-spending components without inventing a reported sum."""
    outputs: Record = {}
    key: str
    for key in (
        "fcf_after_disclosed_capex",
        "fcf_margin_after_disclosed_capex",
        "allocated_fcf_after_disclosed_capex_per_basic_share",
    ):
        denominator: str | None = (
            "revenue"
            if key == "fcf_margin_after_disclosed_capex"
            else "basic_weighted_average_shares"
            if key.endswith("per_basic_share")
            else None
        )
        names: list[str] = ["operating_cash_flow"] + ([denominator] if denominator else [])
        inputs: list[Record] = [
            {
                "metric_key": name,
                "observation_id": facts[name]["observation_id"],
                "value": facts[name].get("value"),
                "source_id": facts[name].get("source_id"),
                "locator": facts[name].get("locator"),
            }
            for name in names
        ]
        reason: str | None = None
        if not spending or not bundle_id:
            reason = "Disclosed cash capital spending components are unavailable"
        elif any(facts[name]["status"] != "reported" for name in names):
            reason = (
                "Required annual inputs are unavailable"
                if key.endswith("per_basic_share")
                else ("Reported annual cash flow or revenue is unavailable")
            )
        elif (
            key == "fcf_margin_after_disclosed_capex"
            and Decimal(str(facts["revenue"]["value"])) <= 0
        ):
            reason = "A positive revenue denominator is required"
        if denominator == "basic_weighted_average_shares":
            reason = reason or basic_share_reason(facts[denominator])
            inputs[-1]["share_basis"] = facts[denominator].get("share_basis")
        components: Record = record(spending["components"]) if spending else {}
        component_key: str
        for component_key in sorted(components):
            component: Record = record(components[component_key])
            inputs.append(
                {
                    "component_key": component_key,
                    "component_ref": f"{bundle_id}#/capital_spending/components/{component_key}",
                    "value": component["value"],
                    "source_id": component["source_id"],
                    "locator": component["locator"],
                }
            )
        result: Record = {
            "formula_version": FORMULA_VERSION,
            "formula": f"(CFO - sum(disclosed cash capital spending components)) / {denominator}"
            if denominator
            else "CFO - sum(disclosed cash capital spending components)",
            "inputs": inputs,
            "scope": spending["scope"] if spending else None,
            "review_note": spending["review_note"] if spending else None,
        }
        if reason:
            result.update(status="unavailable", reason=reason)
        else:
            context: Context
            with localcontext() as context:
                context.prec = 38
                total: Decimal = sum(
                    (Decimal(str(record(value)["value"])) for value in components.values()),
                    Decimal(0),
                )
                value: Decimal = Decimal(str(facts["operating_cash_flow"]["value"])) - total
                if denominator:
                    value /= Decimal(str(facts[denominator]["value"]))
            result.update(
                status="calculated",
                value=format(value, "f"),
                capital_spending_total=format(total, "f"),
            )
        if denominator == "basic_weighted_average_shares":
            result["share_basis"] = facts[denominator].get("share_basis")
        outputs[key] = result
    return outputs


def validate(path: Path, source_dir: Path | None = None) -> Record:
    """Check structure, semantic boundaries and original downloaded document hashes."""
    bundle: Record = record(
        cast(Json, json.loads(path.read_text(), object_pairs_hook=unique_object))
    )
    schema: Record = record(cast(Json, json.loads(SCHEMA.read_text())))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(bundle)
    period: Record = record(bundle["period"])
    start: date = date.fromisoformat(str(period["start"]))
    end: date = date.fromisoformat(str(period["end"]))
    if not 350 <= (end - start).days + 1 <= 380:
        raise ValueError(
            "Unsupported annual dates; supply a full year. "
            "Transition periods need an explicit policy"
        )
    sources: list[Record] = records(bundle["sources"])
    by_id: dict[str, Record] = {str(source["source_id"]): source for source in sources}
    if len(by_id) != len(sources):
        raise ValueError("Duplicate source IDs; give each document version a unique source ID")
    hashes: set[str] = set()
    folder: Path = (source_dir or path.parent).resolve()
    file: Path
    for file in folder.rglob("*"):
        if file.is_file() and not file.is_symlink():
            hashes.add(hashlib.sha256(file.read_bytes()).hexdigest())
    source: Record
    for source in sources:
        published: date = date.fromisoformat(str(source["published_on"]))
        retrieved: datetime = datetime.fromisoformat(
            str(source["retrieved_at"]).replace("Z", "+00:00")
        )
        if published < end or retrieved.date() < published:
            raise ValueError(
                "Invalid source chronology; use the document's actual publication date"
            )
        if source["content_sha256"] not in hashes:
            raise ValueError(
                "Source bytes missing or hash differs; save original bytes in --source-dir"
            )
    key: str
    raw: Json
    for key, raw in record(bundle["facts"]).items():
        fact: Record = record(raw)
        sid: str = str(fact.get("source_id", ""))
        if sid and sid not in by_id:
            raise ValueError(f"Unresolved source for {key}; reference a source in this bundle")
        if fact["status"] in {"not_disclosed", "not_applicable"} and not sid:
            raise ValueError(f"Missing absence evidence for {key}; add a source and locator")
        if "share_basis" in fact:
            basis: Record = record(fact["share_basis"])
            if not sid or str(basis["split_adjusted_through"]) > str(by_id[sid]["published_on"]):
                raise ValueError(
                    f"Unsupported split basis for {key}; use the source's reported basis"
                )
    validate_capital_spending(bundle)
    return bundle


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


def calculations(
    facts: dict[str, Record],
    insurer: bool,
    capital_spending: Record | None = None,
    bundle_id: str | None = None,
) -> Record:
    """Compute declared ratios with pinned inputs, missingness and exact decimal arithmetic."""
    outputs: Record = {}
    formulas: dict[str, tuple[list[str], str]] = {
        "gross_margin": (["gross_profit", "revenue"], "gross_profit / revenue"),
        "operating_margin": (["operating_income", "revenue"], "operating_income / revenue"),
        "net_margin": (["net_income", "revenue"], "net_income / revenue"),
        "net_margin_common": (["net_income_common", "revenue"], "net_income_common / revenue"),
        "cfo_margin": (["operating_cash_flow", "revenue"], "operating_cash_flow / revenue"),
        "fcf_after_ppe": (["operating_cash_flow", "cash_capex_ppe"], "CFO - cash PP&E capex"),
        "fcf_margin_after_ppe": (
            ["operating_cash_flow", "cash_capex_ppe", "revenue"],
            "(CFO - cash PP&E capex) / revenue",
        ),
        "allocated_cfo_per_basic_share": (
            ["operating_cash_flow", "basic_weighted_average_shares"],
            "CFO / basic weighted shares",
        ),
        "allocated_fcf_after_ppe_per_basic_share": (
            ["operating_cash_flow", "cash_capex_ppe", "basic_weighted_average_shares"],
            "(CFO - cash PP&E capex) / basic weighted shares",
        ),
    }
    key: str
    inputs: list[str]
    formula: str
    for key, (inputs, formula) in formulas.items():
        if (
            key == "gross_margin"
            and not insurer
            and facts["gross_profit"]["status"] == "not_disclosed"
        ):
            inputs = ["revenue", "cost_of_revenue"]
            formula = "(revenue - cost_of_revenue) / revenue"
        reason: str | None = None
        if insurer and key == "gross_margin":
            reason = "Insurer gross margin is not applicable under the pilot definition"
        missing: list[str] = [name for name in inputs if facts[name]["status"] != "reported"]
        if missing and reason is None:
            reason = "Missing/applicability inputs: " + ", ".join(missing)
        denominator: str | None = (
            "basic_weighted_average_shares"
            if "per_basic_share" in key
            else ("revenue" if "margin" in key else None)
        )
        if denominator and facts[denominator]["status"] == "reported":
            if Decimal(str(facts[denominator]["value"])) <= 0:
                reason = "A positive denominator is required"
        if denominator == "basic_weighted_average_shares" and not missing:
            reason = reason or basic_share_reason(facts[denominator])
        result: Record = {
            "formula_version": FORMULA_VERSION,
            "formula": formula,
            "inputs": [
                {
                    "metric_key": name,
                    "observation_id": facts[name]["observation_id"],
                    "source_id": facts[name].get("source_id"),
                }
                for name in inputs
            ],
        }
        if reason:
            result.update(status="unavailable", reason=reason)
        else:
            amounts: list[Decimal] = [Decimal(str(facts[name]["value"])) for name in inputs]
            context: Context
            with localcontext() as context:
                context.prec = 38
                value: Decimal = amounts[0]
                if key == "gross_margin" and len(inputs) == 2 and inputs[0] == "revenue":
                    value = (amounts[0] - amounts[1]) / amounts[0]
                elif key.startswith("fcf_") or key.startswith("allocated_fcf"):
                    value -= amounts[1]
                    if denominator:
                        value /= amounts[-1]
                elif denominator:
                    value /= amounts[-1]
            result.update(status="calculated", value=format(value, "f"))
        outputs[key] = result
    outputs.update(disclosed_capex_calculations(facts, capital_spending, bundle_id))
    return outputs


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
