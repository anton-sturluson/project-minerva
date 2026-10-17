"""One-time, explicitly incomplete reconstruction from a transaction CSV."""

import argparse
import csv
import hashlib
import io
import json
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Context, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from http.client import HTTPResponse
from pathlib import Path
from typing import cast
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from investor_platform.accounts import AccountInput
from investor_platform.db import LOCAL_OWNER, LOCAL_WORKSPACE, Actor, make_engine
from investor_platform.domain import ACCOUNTING_PRECISION, Currency, EntryKind, FundingStatus
from investor_platform.ledger.accounting import replay
from investor_platform.ledger.commands import build_trade
from investor_platform.ledger.purchase_shortfalls import FUNDING_WARNING as WARNING
from investor_platform.ledger.purchase_shortfalls import (
    CashMovement,
    PurchaseShortfall,
    infer_purchase_shortfalls,
    inferred_deposit,
)
from investor_platform.ledger.schemas import CashInput, LedgerRecord, LedgerValue, Money, TradeInput
from investor_platform.ledger.state import active_entries_for_account, fingerprint
from investor_platform.models import Account, LedgerEntry, Workspace

MAX_EXPORT_BYTES: int = 5_000_000


class TransactionLayout(StrEnum):
    """Supported legacy unit-price and authoritative USD-total source layouts."""

    LEGACY = "legacy"
    USD_TOTALS = "usd-totals"


class ImportedTrade(TradeInput):
    """A source trade that retains reported cash separately from its quoted unit price."""

    # Reported cash may include charges or execution-price precision absent from unit prices.
    reported_amount: Money


def decimal(value: str) -> Decimal:
    """Read a positive source amount after removing dollar signs and thousands separators."""
    amount: Decimal = Decimal(value.strip().replace("$", "").replace(",", ""))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Expected a positive amount")
    return amount


def trade_date(value: str) -> date:
    """Read a source transaction date in an explicitly supported date format."""
    pattern: str
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            pass
    raise ValueError("Expected an ISO or US month/day/year date")


def source_rows(payload: bytes) -> tuple[list[dict[str, str]], str]:
    """Normalize CSV or unformatted visualization cells while retaining source row order."""
    text: str = payload.decode("utf-8-sig")
    if "google.visualization.Query.setResponse(" not in text[:100]:
        return cast(list[dict[str, str]], list(csv.DictReader(io.StringIO(text)))), "csv"
    response: LedgerRecord = json.loads(
        text[text.index("{") : text.rindex("}") + 1], parse_float=Decimal
    )
    table: LedgerRecord = cast(LedgerRecord, response["table"])
    columns: list[str] = [cast(str, c["label"]) for c in cast(list[LedgerRecord], table["cols"])]
    rows: list[dict[str, str]] = []
    row: LedgerRecord
    for row in cast(list[LedgerRecord], table["rows"]):
        values: dict[str, str] = {}
        column: str
        cell: LedgerRecord | None
        for column, cell in zip(columns, cast(list[LedgerRecord | None], row["c"]), strict=True):
            value: LedgerValue = cell.get("v") if cell else None
            if column == "Date" and isinstance(value, str):
                match: re.Match[str] | None = re.fullmatch(r"Date\((\d+),(\d+),(\d+)\)", value)
                if match:
                    year: int
                    month: int
                    day: int
                    year, month, day = map(int, match.groups())
                    value = date(year, month + 1, day).isoformat()
            values[column] = "" if value is None else str(value)
        rows.append(values)
    return rows, "google-unformatted"


def reconstruct(
    payload: bytes, listings: dict[str, dict[str, str]], *, portfolio: str | None = None
) -> tuple[list[TradeInput | CashInput], LedgerRecord]:
    """Keep raw evidence and fund each purchase shortfall on its source date."""
    rows: list[dict[str, str]]
    source_format: str
    rows, source_format = source_rows(payload)
    columns: set[str] = set(rows[0]) if rows else set()
    if not {"Date", "Type", "Symbol", "Shares"} <= columns:
        raise ValueError("CSV needs Date, Type, Symbol and Shares columns")
    layout: TransactionLayout
    if {"Price (USD)", "Total (USD)"} <= columns:
        layout = TransactionLayout.USD_TOTALS
    elif {"Cost", "Price"} <= columns:
        layout = TransactionLayout.LEGACY
    else:
        raise ValueError("CSV needs Price (USD) and Total (USD), or legacy Cost and Price columns")
    # Portfolio ownership is explicit source data, never inferred from a ticker.
    populated: list[dict[str, str]] = [
        r for r in rows if any(str(v or "").strip() for v in r.values())
    ]
    groups: set[str] = {r.get("Portfolio", "").strip() for r in populated}
    if "Portfolio" in columns:
        if "" in groups:
            raise ValueError("Every populated row needs a Portfolio assignment")
        if portfolio is None and len(groups) > 1:
            raise ValueError("Choose --portfolio from: " + ", ".join(sorted(groups)))
        portfolio = portfolio or next(iter(groups), None)
        if portfolio not in groups:
            raise ValueError("Selected portfolio is absent from the source")
    elif portfolio is not None:
        raise ValueError("Source has no Portfolio column")
    digest: str = hashlib.sha256(payload).hexdigest()
    # Include the explicit listing/currency choices in retry identity.
    identity: str = hashlib.sha256(
        payload + json.dumps(listings, sort_keys=True).encode()
    ).hexdigest()
    if portfolio is not None:
        identity = hashlib.sha256(f"{identity}:portfolio:{portfolio}".encode()).hexdigest()
    trades: list[tuple[int, TradeInput]] = []
    skipped: list[dict[str, int | str]] = []
    differences: list[int] = []
    excluded_rows: list[int] = []
    ctx: Context
    with localcontext() as ctx:
        ctx.prec = ACCOUNTING_PRECISION
        row_number: int
        row: dict[str, str]
        for row_number, row in enumerate(rows, 2):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            if portfolio is not None and row["Portfolio"].strip() != portfolio:
                excluded_rows.append(row_number)
                continue
            try:
                ticker: str = row["Symbol"].strip().upper()
                listing: dict[str, str] = listings.get(ticker, {})
                if listing.get("currency") != Currency.USD:
                    raise ValueError("USD record currency is not confirmed in the listing map")
                kind: str = row["Type"].strip().lower()
                if kind not in {EntryKind.BUY, EntryKind.SELL}:
                    raise ValueError("Only Buy and Sell rows are supported")
                quantity: Decimal = decimal(row["Shares"]).quantize(Decimal("0.00000001"))
                if not quantity:
                    raise ValueError(
                        "Shares round to zero at the supported eight-decimal precision"
                    )
                modern: bool = layout == TransactionLayout.USD_TOTALS
                quoted: Decimal = decimal(
                    row["Price (USD)" if modern else "Cost" if kind == EntryKind.BUY else "Price"]
                )
                total: str | Decimal = (
                    row["Total (USD)"]
                    if modern
                    else row.get("Total Cost" if kind == EntryKind.BUY else "Market Value", "")
                ).strip()
                if modern and not total:
                    raise ValueError("Total (USD) is required; no cash total is inferred")
                price: Decimal = quoted.quantize(Decimal("0.00000001"))
                if total:
                    total = decimal(total)
                    if modern:
                        total = total.quantize(Decimal("0.00000001"))
                        if not total:
                            raise ValueError("Total rounds to zero at eight-decimal precision")
                    if abs(quantity * quoted - total) > Decimal("0.01"):
                        differences.append(row_number)
                    # Displayed per-share prices are rounded. Prefer the source cash total.
                    if source_format == "csv" and not modern:
                        price = (total / quantity).quantize(Decimal("0.00000001"))
                trade_type: type[TradeInput] = ImportedTrade if modern else TradeInput
                trade: TradeInput = trade_type(
                    kind=kind,
                    effective_date=trade_date(row["Date"]),
                    ticker=listing.get("ticker", ticker),
                    exchange=listing.get("exchange", "UNVERIFIED"),
                    currency=Currency.USD,
                    quantity=quantity,
                    price=price,
                    request_key=uuid5(NAMESPACE_URL, f"{identity}:row:{row_number}"),
                    note=(
                        f"Source row {row_number}; reported USD cash total; charges not itemized."
                        if modern
                        else f"Source row {row_number}; rounded totals; fees not supplied."
                    ),
                    **({"reported_amount": total} if modern else {}),
                )
                trades.append((row_number, trade))
            except (ValueError, InvalidOperation, TypeError, AttributeError) as exc:
                skipped.append({"row": row_number, "reason": str(exc)})
        # Keep source order within a date; never silently reorder same-day decisions.
        trades.sort(key=lambda item: (item[1].effective_date, item[0]))
        if not trades:
            raise ValueError("No importable transactions; confirm USD listings and inspect the CSV")
        shares: dict[tuple[str, str], Decimal] = {}
        minimum: dict[tuple[str, str], Decimal] = {}
        t: TradeInput
        key: tuple[str, str]
        for _, t in trades:
            key = (t.ticker, t.exchange)
            shares[key] = shares.get(key, Decimal(0)) + t.quantity * (
                1 if t.kind == EntryKind.BUY else -1
            )
            minimum[key] = min(minimum.get(key, Decimal(0)), shares[key])
        start: date = trades[0][1].effective_date
        movements: list[CashMovement] = [
            CashMovement(
                trade.effective_date,
                EntryKind(trade.kind),
                trade.reported_amount
                if isinstance(trade, ImportedTrade)
                else trade.quantity * trade.price,
            )
            for _, trade in trades
        ]
        shortfalls: dict[int, PurchaseShortfall] = {
            item.index: item for item in infer_purchase_shortfalls(movements)
        }
        entries: list[TradeInput | CashInput] = []
        openings: dict[str, str] = {}
        ticker: str
        exchange: str
        low: Decimal
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
        index: int
        trade: TradeInput
        for index, (_, trade) in enumerate(trades):
            if index in shortfalls:
                entries.append(inferred_deposit(shortfalls[index], trade.request_key, Currency.USD))
            entries.append(trade)
        funding_total: Decimal = sum((item.amount for item in shortfalls.values()), Decimal(0))
    summary: LedgerRecord = {
        "warning": WARNING,
        "source_sha256": digest,
        "selected_portfolio": portfolio,
        "other_portfolio_rows": excluded_rows,
        "identity": identity,
        "source_rows": rows,
        "source_format": source_format,
        "transaction_layout": layout,
        "raw_source": payload.decode("utf-8-sig"),
        "listings": listings,
        "imported_trades": len(trades),
        "skipped": skipped,
        "cash_method": "purchase_shortfall",
        "funding_status": FundingStatus.INFERRED,
        "inferred_deposit_count": len(shortfalls),
        "inferred_deposits_total": str(funding_total),
        "opening_positions": openings,
        "price_discrepancies": differences,
        "holdings": {
            f"{t} · {e}": str(q - minimum[(t, e)])
            for (t, e), q in sorted(shares.items())
            if q - minimum[(t, e)] > 0
        },
    }
    return entries, summary


def apply_import(
    engine: Engine,
    name: str,
    entries: Sequence[TradeInput | CashInput],
    summary: LedgerRecord,
) -> tuple[str, bool]:
    """Create the entire test account atomically; never replace or append to an existing account."""
    data: AccountInput = AccountInput(name=name, base_currency=Currency.USD)
    session: Session
    with Session(engine) as session, session.begin():
        workspace: Workspace | None = session.scalar(
            select(Workspace)
            .where(Workspace.id == LOCAL_WORKSPACE, Workspace.owner_id == LOCAL_OWNER)
            .with_for_update()
        )
        if workspace is None:
            raise ValueError("Run migrations before importing")
        existing: Account | None = session.scalar(
            select(Account).where(
                Account.workspace_id == LOCAL_WORKSPACE, Account.name == data.name
            )
        )
        if existing:
            if (existing.reconstruction or {}).get("identity") == summary["identity"]:
                return str(existing.id), False
            raise ValueError(
                "This portfolio name already has an account with a different import. "
                "Choose a new name."
            )
        account: Account = Account(
            workspace_id=LOCAL_WORKSPACE, reconstruction=summary, **data.model_dump()
        )
        session.add(account)
        session.flush()
        actor: Actor = Actor(LOCAL_OWNER, LOCAL_WORKSPACE)
        entry: TradeInput | CashInput
        for entry in entries:
            body: str = fingerprint(entry)
            trade_data: TradeInput | CashInput = (
                TradeInput.model_validate(entry.model_dump(exclude={"reported_amount"}))
                if isinstance(entry, ImportedTrade)
                else entry
            )
            record: LedgerEntry = (
                build_trade(account, trade_data, session, actor, body)
                if isinstance(entry, TradeInput)
                else LedgerEntry(
                    account_id=account.id,
                    created_by=actor.owner_id,
                    request_body=body,
                    **entry.model_dump(exclude={"cash_method", "purchase_request_key"}),
                )
            )
            if isinstance(entry, ImportedTrade):
                record.amount = entry.reported_amount
            session.add(record)
        session.flush()
        replay(active_entries_for_account(session, account.id))
        return str(account.id), True


def main() -> None:
    """Preview a bounded source export or atomically create a new imported account."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, help="CSV / unformatted Google export path or HTTPS URL"
    )
    parser.add_argument(
        "--listings",
        required=True,
        type=Path,
        help='JSON: {"TICKER": {"exchange": "NASDAQ", "currency": "USD"}}',
    )
    parser.add_argument("--portfolio", help="Exact value in the source Portfolio column")
    parser.add_argument("--name", default="Transaction reconstruction · testing")
    parser.add_argument(
        "--apply", action="store_true", help="Create a new named portfolio in DATABASE_URL"
    )
    args: argparse.Namespace = parser.parse_args()
    payload: bytes
    entries: list[TradeInput | CashInput]
    summary: LedgerRecord
    try:
        if args.source.startswith("https://"):
            response: HTTPResponse
            with urlopen(args.source, timeout=30) as response:
                payload = response.read(MAX_EXPORT_BYTES + 1)
        else:
            payload = Path(args.source).read_bytes()
        if len(payload) > MAX_EXPORT_BYTES:
            raise ValueError("Transaction export exceeds 5 MB")
        entries, summary = reconstruct(
            payload, json.loads(args.listings.read_text()), portfolio=args.portfolio
        )
        output: LedgerRecord = {
            k: v
            for k, v in summary.items()
            if k not in {"source_rows", "raw_source", "listings", "identity"}
        }
        if args.apply:
            engine: Engine = make_engine()
            try:
                account_id: str
                created: bool
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
