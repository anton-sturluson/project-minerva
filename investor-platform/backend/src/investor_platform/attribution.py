"""Read-only stock contributions linked to the same daily portfolio return index."""

from collections import defaultdict
from decimal import Decimal

from .domain import IN_KIND_ENTRIES, EntryKind

ZERO = Decimal(0)
ONE = Decimal(1)


class StockAttribution:
    def __init__(self, securities):
        self.securities = securities
        self.previous = {}
        self.periods = {}

    def record(
        self,
        day,
        previous_day,
        values,
        entries,
        prices,
        distributions,
        denominator,
        growth_before,
        growth_after,
    ):
        if previous_day is None:
            self.previous = values
            return
        gains = {
            sid: values.get(sid, ZERO) - self.previous.get(sid, ZERO)
            for sid in values.keys() | self.previous.keys()
        }
        for entry in entries:
            sid = entry.security_id
            if sid is None:
                continue
            gains.setdefault(sid, ZERO)
            if entry.kind == EntryKind.BUY:
                gains[sid] -= entry.amount
            elif entry.kind == EntryKind.SELL:
                gains[sid] += entry.amount
            elif entry.kind in IN_KIND_ENTRIES:
                gains[sid] -= entry.quantity * prices[sid].close[day]
        for (sid, exdate), amount in distributions.items():
            if previous_day < exdate <= day:
                gains[sid] = gains.get(sid, ZERO) + amount
        for key in ("all", str(day.year)):
            period = self.periods.setdefault(
                key,
                {
                    "start": previous_day,
                    "base": growth_before,
                    "linked": defaultdict(Decimal),
                    "gains": defaultdict(Decimal),
                },
            )
            period["end"] = day
            period["growth"] = growth_after
            for sid, gain in gains.items():
                period["gains"][sid] += gain
                period["linked"][sid] += growth_before * gain / denominator if denominator else ZERO
        self.previous = values

    def report(self):
        reports = []
        for key, period in self.periods.items():
            base = period["base"]
            result = period["growth"] / base - ONE if base else None
            rows = [
                {
                    "security_id": sid,
                    "ticker": self.securities[sid].ticker,
                    "exchange": self.securities[sid].exchange,
                    "contribution": linked / base if base else None,
                    "gain": period["gains"][sid],
                }
                for sid, linked in period["linked"].items()
            ]
            total = sum((row["contribution"] for row in rows), ZERO) if base else None
            # Never redistribute an unexplained difference between securities to force a match.
            if result is not None and abs(result - total) > Decimal("1e-20"):
                raise ValueError("Stock return contributions could not be reconciled")
            reports.append(
                {
                    "period": key,
                    "start": period["start"],
                    "end": period["end"],
                    "return": result,
                    "contribution_total": total,
                    "gain": sum(period["gains"].values(), ZERO),
                    "stocks": sorted(
                        rows,
                        key=lambda row: (
                            -(row["contribution"] or ZERO),
                            row["ticker"],
                            row["exchange"],
                        ),
                    ),
                }
            )
        return reports
