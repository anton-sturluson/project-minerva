"""Explicit PostgreSQL financial-data operations for the app and agent callers."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import psycopg
from pydantic import ValidationError

from .financial_import import migrate, read_legacy, summary, verify
from .financial_store import (
    ObservationBatch,
    append_observations,
    company_rows,
    connect,
    history_rows,
    initialize,
    json_result,
    relation,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="investor_data")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create only the versioned financial namespace")
    for command in ("inspect-sqlite", "migrate-sqlite", "verify-sqlite"):
        sub = commands.add_parser(command)
        sub.add_argument("--sqlite", type=Path, required=True)
    companies = commands.add_parser("companies", help="Read company identities")
    companies.add_argument("--ticker")
    history = commands.add_parser("history", help="Read observations in chronological order")
    history.add_argument("--company-id", type=int, required=True)
    history.add_argument("--metric-key")
    history.add_argument(
        "--scenario",
        choices=["actual", "guidance", "target", "consensus", "estimate"],
        default="actual",
    )
    history.add_argument("--limit", type=int, default=100)
    append = commands.add_parser("append", help="Append unverified observations; conflicts fail")
    append.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        relation(args.schema, "companies")
        if args.command == "inspect-sqlite":
            result = summary(read_legacy(args.sqlite))
        else:
            dataset = read_legacy(args.sqlite) if args.command.endswith("sqlite") else None
            batch = (
                ObservationBatch.model_validate_json(args.input.read_text())
                if args.command == "append"
                else None
            )
            readonly = args.command in {"verify-sqlite", "companies", "history"}
            with connect(readonly=readonly) as conn:
                if args.command == "init":
                    initialize(conn, args.schema)
                    result = {"status": "initialized"}
                elif args.command == "migrate-sqlite":
                    result = migrate(conn, args.schema, dataset)
                elif args.command == "verify-sqlite":
                    result = verify(conn, args.schema, dataset)
                elif args.command == "companies":
                    result = company_rows(conn, args.schema, args.ticker)
                elif args.command == "history":
                    result = history_rows(
                        conn,
                        args.schema,
                        args.company_id,
                        args.metric_key,
                        args.scenario,
                        args.limit,
                    )
                else:
                    result = append_observations(conn, args.schema, batch)
        print(json_result(result))
    except ValidationError as exc:
        # Pydantic errors normally echo the input; keep potentially private data out of logs.
        print(
            json.dumps(
                {
                    "error": "Invalid observation batch",
                    "fields": [
                        list(e["loc"])
                        for e in exc.errors(include_input=False, include_context=False)
                    ],
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except psycopg.Error as exc:
        print(
            json.dumps(
                {
                    "error": "PostgreSQL operation failed; no changes committed",
                    "sqlstate": exc.sqlstate,
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (ValueError, OSError, json.JSONDecodeError, sqlite3.Error) as exc:
        message = (
            str(exc)
            if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
            else "Input file is unavailable or invalid"
        )
        print(json.dumps({"error": message}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
