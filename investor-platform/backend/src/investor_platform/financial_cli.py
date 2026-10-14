"""Expose annual candidate validation, explicit imports and coherent company reads."""

import argparse
import json
import os
import sys
from pathlib import Path

from jsonschema import ValidationError
from psycopg import Connection, Error, connect
from psycopg.rows import dict_row

from .financial import Record, Row, digest, import_bundle, show, validate


def parser() -> argparse.ArgumentParser:
    """Describe each composable operation without adding text to JSON results."""
    cli: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="investor-financial", description="Annual company financial facts; JSON on stdout."
    )
    commands: argparse._SubParsersAction = cli.add_subparsers(dest="command")
    name: str
    for name in ("validate", "import"):
        command: argparse.ArgumentParser = commands.add_parser(
            name,
            help="Validate source-backed candidates"
            if name == "validate"
            else "Append a candidate or independently reviewed bundle to an explicit schema",
            epilog=f"Example: investor-financial {name} bundle.json"
            + (" --schema investor_financial_pilot --reviewed" if name == "import" else ""),
        )
        command.add_argument("bundle", type=Path, help="Annual financial bundle JSON file")
        command.add_argument(
            "--source-dir",
            type=Path,
            help="Original source bytes directory (default: bundle folder)",
        )
        if name == "import":
            command.add_argument("--schema", required=True, help="Fresh investor_financial_<name>")
            command.add_argument(
                "--reviewed",
                action="store_true",
                help="Record completed independent fact review; not automatic verification",
            )
    read: argparse.ArgumentParser = commands.add_parser(
        "show",
        help="Read the latest coherent company-year facts and declared calculations",
        epilog="Example: investor-financial show sec-cik:0000000001 2025 "
        "--schema investor_financial_pilot",
    )
    read.add_argument("issuer", help="Confirmed issuer key; never a ticker-only join")
    read.add_argument("year", type=int, help="Calendar year in which the fiscal period ends")
    read.add_argument("--schema", required=True, help="Explicit investor_financial_<name>")
    return cli


def main() -> None:
    """Return clean JSON, or a recoverable error on stderr with a nonzero exit."""
    cli: argparse.ArgumentParser = parser()
    args: argparse.Namespace = cli.parse_args()
    if not args.command:
        cli.print_help()
        return
    try:
        bundle: Record | None = None
        if args.command in {"validate", "import"}:
            bundle = validate(args.bundle, args.source_dir)
        result: Record
        if args.command == "validate":
            assert bundle is not None
            result = {
                "status": "candidate",
                "bundle_id": bundle["bundle_id"],
                "bundle_sha256": digest(bundle),
                "checks": "structure, semantics, source hashes",
                "financial_truth": "independent fact review still required",
            }
        else:
            dsn: str | None = os.environ.get("INVESTOR_FINANCIAL_DATABASE_URL")
            if not dsn:
                raise ValueError(
                    "Set INVESTOR_FINANCIAL_DATABASE_URL explicitly; no fallback is used"
                )
            conn: Connection[Row]
            with connect(
                dsn.replace("postgresql+psycopg://", "postgresql://", 1),
                row_factory=dict_row,
                connect_timeout=5,
            ) as conn:
                conn.read_only = args.command == "show"
                if args.command == "import":
                    assert bundle is not None
                    result = import_bundle(conn, args.schema, bundle, args.reviewed)
                else:
                    result = show(conn, args.schema, args.issuer, args.year)
        print(json.dumps(result, default=str))
    except (OSError, ValueError, ValidationError, Error) as error:
        message: str
        if isinstance(error, Error):
            message = (
                f"Database operation failed (SQLSTATE {error.sqlstate or 'unavailable'}); "
                "check the explicit connection, schema and import permissions"
            )
        elif isinstance(error, OSError):
            message = "Cannot read a bundle or source file; check the input file and --source-dir"
        else:
            message = error.message if isinstance(error, ValidationError) else str(error)
        print(
            f"Error: {message}. Review the bundle/source files and command --help, then retry.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
