"""Deterministic chronological replay and FIFO lot allocation."""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from fastapi import HTTPException

UNIT = Decimal("0.0000000000000001")


@dataclass
class Lot:
    quantity: Decimal
    basis: Decimal | None


def replay(entries):
    # Products can contain 40 significant digits; never use the default 28-digit context.
    with localcontext() as context:
        context.prec = 64
        cash = Decimal(0)
        lots = {}
        seen = set()
        realized = {}
        opening_date = next((e.effective_date for e in entries if e.kind == "opening_cash"), None)
        for e in entries:
            if opening_date and e.effective_date < opening_date:
                raise HTTPException(409, "Entries cannot precede the opening balance date")
            if e.kind in {"opening_cash", "deposit", "income"}:
                cash += e.amount
            elif e.kind in {"withdrawal", "buy"}:
                cash -= e.amount
            elif e.kind == "sell":
                cash += e.amount
            if cash < 0:
                raise HTTPException(
                    409, "This entry would make cash negative in the account history"
                )
            if e.kind in {"opening_position", "buy"}:
                if e.kind == "opening_position" and e.security_id in seen:
                    raise HTTPException(
                        409, "An opening position must precede all trades in that security"
                    )
                lots.setdefault(e.security_id, []).append(
                    Lot(e.quantity, e.cost_basis if e.kind == "opening_position" else e.amount)
                )
            elif e.kind == "sell":
                remaining = e.quantity
                basis = Decimal(0)
                unknown = False
                for lot in lots.get(e.security_id, []):
                    take = min(remaining, lot.quantity)
                    if take == 0:
                        continue
                    if lot.basis is None:
                        unknown = True
                    else:
                        allocated = (
                            lot.basis
                            if take == lot.quantity
                            else (lot.basis * take / lot.quantity).quantize(
                                UNIT, rounding=ROUND_HALF_EVEN
                            )
                        )
                        basis += allocated
                        lot.basis -= allocated
                    remaining -= take
                    lot.quantity -= take
                    if remaining == 0:
                        break
                if remaining:
                    raise HTTPException(
                        409, "This sale would leave negative shares in the account history"
                    )
                realized[e.id] = None if unknown else e.amount - basis
            if e.security_id is not None:
                seen.add(e.security_id)
        return cash, lots, realized
