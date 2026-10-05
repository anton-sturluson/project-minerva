"""Prepare financial data beside SQLite and expose read-only JSON queries."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import psycopg

from .financial_import import migrate, read_legacy, summary, verify
from .financial_store import (
    Dataset,
    Report,
    Row,
    company_rows,
    connect,
    history_rows,
    json_result,
    relation,
)


def main() -> None:
    """Run explicit migration or read operations without ambient portfolio credentials."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="investor_data")
    commands: argparse._SubParsersAction = parser.add_subparsers(dest="command", required=True)
    command: str
    for command in ("inspect-sqlite", "migrate-sqlite", "verify-sqlite"):
        sub: argparse.ArgumentParser = commands.add_parser(command)
        sub.add_argument("--sqlite", type=Path, required=True)
    companies: argparse.ArgumentParser = commands.add_parser("companies")
    companies.add_argument("--ticker")
    history: argparse.ArgumentParser = commands.add_parser("history")
    history.add_argument("--company-id", type=int, required=True)
    history.add_argument("--metric-key")
    history.add_argument(
        "--scenario",
        choices=["actual", "guidance", "target", "consensus", "estimate"],
        default="actual",
    )
    history.add_argument("--limit", type=int, default=100)
    args: argparse.Namespace = parser.parse_args()
    result: Report | list[Row]
    conn: psycopg.Connection[Row]
    try:
        relation(args.schema, "companies")
        if args.command.endswith("sqlite"):
            dataset: Dataset = read_legacy(args.sqlite)
            if args.command == "inspect-sqlite":
                result = summary(dataset)
            else:
                with connect(readonly=args.command != "migrate-sqlite") as conn:
                    result = (
                        migrate(conn, args.schema, dataset)
                        if args.command == "migrate-sqlite"
                        else verify(conn, args.schema, dataset)
                    )
        else:
            with connect() as conn:
                result = (
                    company_rows(conn, args.schema, args.ticker)
                    if args.command == "companies"
                    else history_rows(
                        conn,
                        args.schema,
                        args.company_id,
                        args.metric_key,
                        args.scenario,
                        args.limit,
                    )
                )
        print(json_result(result))
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
    except (ValueError, OSError, sqlite3.Error) as exc:
        message: str = (
            str(exc) if isinstance(exc, ValueError) else "Input file is unavailable or invalid"
        )
        print(json.dumps({"error": message}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
