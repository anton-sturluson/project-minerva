"""One-time, explicitly incomplete reconstruction from a transaction CSV."""

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation, localcontext
from pathlib import Path
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounting import replay
from .accounts import AccountInput
from .db import LOCAL_OWNER, LOCAL_WORKSPACE, Actor, make_engine
from .domain import ACCOUNTING_PRECISION, Currency, EntryKind
from .ledger import CashInput, entries_for, fingerprint
from .models import Account, LedgerEntry, Workspace
from .trades import TradeInput, build_trade

MAX_EXPORT_BYTES = 5_000_000

WARNING = (
    "Incomplete transaction reconstruction for testing. Opening shares and cash are inferred "
    "minimums, not broker balances. Fees, cash flows, distributions and corporate actions are "
    "incomplete. Holdings, trade statistics and portfolio returns are provisional."
)


def decimal(value):
    value = Decimal(value.strip().replace("$", "").replace(",", ""))
    if not value.is_finite() or value <= 0:
        raise ValueError("Expected a positive amount")
    return value


def trade_date(value):
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            pass
    raise ValueError("Expected an ISO or US month/day/year date")


def source_rows(payload):
    text = payload.decode("utf-8-sig")
    if "google.visualization.Query.setResponse(" not in text[:100]:
        return list(csv.DictReader(io.StringIO(text))), "csv"
    response = json.loads(text[text.index("{") : text.rindex("}") + 1], parse_float=Decimal)
    table = response["table"]
    columns = [c["label"] for c in table["cols"]]
    rows = []
    for row in table["rows"]:
        values = {}
        for column, cell in zip(columns, row["c"], strict=True):
            value = cell.get("v") if cell else None
            if column == "Date" and isinstance(value, str):
                match = re.fullmatch(r"Date\((\d+),(\d+),(\d+)\)", value)
                if match:
                    year, month, day = map(int, match.groups())
                    value = date(year, month + 1, day).isoformat()
            values[column] = "" if value is None else str(value)
        rows.append(values)
    return rows, "google-unformatted"


def reconstruct(payload: bytes, listings: dict):
    """Keep raw evidence, reject ambiguous rows and infer only minimum opening balances."""
    rows, source_format = source_rows(payload)
    if not rows or not {"Date", "Type", "Symbol", "Shares", "Cost", "Price"} <= rows[0].keys():
        raise ValueError("CSV needs Date, Type, Symbol, Shares, Cost and Price columns")
    digest = hashlib.sha256(payload).hexdigest()
    # Include the explicit listing/currency choices in retry identity.
    identity = hashlib.sha256(payload + json.dumps(listings, sort_keys=True).encode()).hexdigest()
    trades, skipped, differences = [], [], []
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        for row_number, row in enumerate(rows, 2):
            try:
                ticker = row["Symbol"].strip().upper()
                listing = listings.get(ticker, {})
                if listing.get("currency") != Currency.USD:
                    raise ValueError("USD record currency is not confirmed in the listing map")
                kind = row["Type"].strip().lower()
                if kind not in {EntryKind.BUY, EntryKind.SELL}:
                    raise ValueError("Only Buy and Sell rows are supported")
                quantity = decimal(row["Shares"]).quantize(Decimal("0.00000001"))
                if not quantity:
                    raise ValueError(
                        "Shares round to zero at the supported eight-decimal precision"
                    )
                quoted = decimal(row["Cost" if kind == EntryKind.BUY else "Price"])
                total = row.get(
                    "Total Cost" if kind == EntryKind.BUY else "Market Value", ""
                ).strip()
                price = quoted.quantize(Decimal("0.00000001"))
                if total:
                    total = decimal(total)
                    if abs(quantity * quoted - total) > Decimal("0.01"):
                        differences.append(row_number)
                    # Displayed per-share prices are rounded. Prefer the source cash total.
                    if source_format == "csv":
                        price = (total / quantity).quantize(Decimal("0.00000001"))
                trade = TradeInput(
                    kind=kind,
                    effective_date=trade_date(row["Date"]),
                    ticker=ticker,
                    exchange=listing.get("exchange", "UNVERIFIED"),
                    currency=Currency.USD,
                    quantity=quantity,
                    price=price,
                    request_key=uuid5(NAMESPACE_URL, f"{identity}:row:{row_number}"),
                    note=f"Source row {row_number}; rounded totals; fees not supplied.",
                )
                trades.append((row_number, trade))
            except (ValueError, InvalidOperation, TypeError, AttributeError) as exc:
                skipped.append({"row": row_number, "reason": str(exc)})
        # Keep source order within a date; never silently reorder same-day decisions.
        trades.sort(key=lambda item: (item[1].effective_date, item[0]))
        if not trades:
            raise ValueError("No importable transactions; confirm USD listings and inspect the CSV")
        shares, minimum, cash, lowest = {}, {}, Decimal(0), Decimal(0)
        for _, t in trades:
            key = (t.ticker, t.exchange)
            shares[key] = shares.get(key, Decimal(0)) + t.quantity * (
                1 if t.kind == EntryKind.BUY else -1
            )
            minimum[key] = min(minimum.get(key, Decimal(0)), shares[key])
            cash += t.quantity * t.price * (-1 if t.kind == EntryKind.BUY else 1)
            lowest = min(lowest, cash)
        start = trades[0][1].effective_date
        opening_cash = (-lowest).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        entries = [
            CashInput(
                kind=EntryKind.OPENING_CASH,
                amount=opening_cash,
                currency=Currency.USD,
                effective_date=start,
                request_key=uuid5(NAMESPACE_URL, f"{identity}:opening-cash"),
                note="INFERRED minimum starting cash for incomplete transaction reconstruction.",
            )
        ]
        openings = {}
        for (ticker, exchange), low in sorted(minimum.items()):
            if low >= 0:
                continue
            openings[f"{ticker} · {exchange}"] = str(-low)
            entries.append(
                TradeInput(
                    kind=EntryKind.OPENING_POSITION,
                    ticker=ticker,
                    exchange=exchange,
                    currency=Currency.USD,
                    quantity=-low,
                    effective_date=start,
                    cost_basis=None,
                    request_key=uuid5(NAMESPACE_URL, f"{identity}:opening:{ticker}:{exchange}"),
                    note="INFERRED minimum opening shares; acquisition date and basis unknown.",
                )
            )
        entries.extend(t for _, t in trades)
    summary = {
        "warning": WARNING,
        "source_sha256": digest,
        "identity": identity,
        "source_rows": rows,
        "source_format": source_format,
        "raw_source": payload.decode("utf-8-sig"),
        "listings": listings,
        "imported_trades": len(trades),
        "skipped": skipped,
        "opening_cash": str(opening_cash),
        "opening_positions": openings,
        "price_discrepancies": differences,
        "holdings": {
            f"{t} · {e}": str(q - minimum[(t, e)])
            for (t, e), q in sorted(shares.items())
            if q - minimum[(t, e)] > 0
        },
    }
    return entries, summary


def apply_import(engine, name, entries, summary):
    """Create the entire test account atomically; never replace or append to an existing account."""
    data = AccountInput(name=name, base_currency=Currency.USD)
    with Session(engine) as session, session.begin():
        workspace = session.scalar(
            select(Workspace)
            .where(Workspace.id == LOCAL_WORKSPACE, Workspace.owner_id == LOCAL_OWNER)
            .with_for_update()
        )
        if workspace is None:
            raise ValueError("Run migrations before importing")
        existing = session.scalar(select(Account).where(Account.workspace_id == LOCAL_WORKSPACE))
        if existing:
            if (existing.reconstruction or {}).get("identity") == summary["identity"]:
                return str(existing.id), False
            raise ValueError(
                "Target already has an account. Use a separate empty testing database."
            )
        account = Account(workspace_id=LOCAL_WORKSPACE, reconstruction=summary, **data.model_dump())
        session.add(account)
        session.flush()
        actor = Actor(LOCAL_OWNER, LOCAL_WORKSPACE)
        for entry in entries:
            body = fingerprint(entry)
            record = (
                build_trade(account, entry, session, actor, body)
                if isinstance(entry, TradeInput)
                else LedgerEntry(
                    account_id=account.id,
                    created_by=actor.owner_id,
                    request_body=body,
                    **entry.model_dump(),
                )
            )
            session.add(record)
        session.flush()
        replay(entries_for(session, account.id))
        return str(account.id), True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, help="CSV / unformatted Google export path or HTTPS URL"
    )
    parser.add_argument(
        "--listings",
        required=True,
        type=Path,
        help='JSON: {"TICKER": {"exchange": "NASDAQ", "currency": "USD"}}',
    )
    parser.add_argument("--name", default="Transaction reconstruction · testing")
    parser.add_argument(
        "--apply", action="store_true", help="Write to the empty DATABASE_URL database"
    )
    args = parser.parse_args()
    try:
        if args.source.startswith("https://"):
            with urlopen(args.source, timeout=30) as response:
                payload = response.read(MAX_EXPORT_BYTES + 1)
        else:
            payload = Path(args.source).read_bytes()
        if len(payload) > MAX_EXPORT_BYTES:
            raise ValueError("Transaction export exceeds 5 MB")
        entries, summary = reconstruct(payload, json.loads(args.listings.read_text()))
        output = {
            k: v
            for k, v in summary.items()
            if k not in {"source_rows", "raw_source", "listings", "identity"}
        }
        if args.apply:
            engine = make_engine()
            try:
                account_id, created = apply_import(engine, args.name, entries, summary)
                output.update(account_id=account_id, created=created)
            finally:
                engine.dispose()
        else:
            output["mode"] = "preview; no database writes"
        print(json.dumps(output, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Import stopped: {exc}\n")


if __name__ == "__main__":
    main()
