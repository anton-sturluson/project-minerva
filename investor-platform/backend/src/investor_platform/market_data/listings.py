"""Recorded listing identities and provider exchange validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from investor_platform.domain import Currency
from investor_platform.market_data.types import History

if TYPE_CHECKING:
    from investor_platform.ledger.schemas import SecurityView
    from investor_platform.models import Security

EXCHANGES: dict[str, set[str]] = {
    "NYSE": {"NYQ"},
    "XNYS": {"NYQ"},
    "NASDAQ": {"NMS", "NGM", "NCM"},
    "XNAS": {"NMS", "NGM", "NCM"},
    "NYSEARCA": {"PCX"},
    "ARCA": {"PCX"},
    "ARCX": {"PCX"},
    "AMEX": {"ASE"},
    "BATS": {"BTS"},
    "OTC": {"PNK", "OQB", "OQX"},
}


PROVIDER_EXCHANGES: frozenset[str] = frozenset().union(*EXCHANGES.values())


FOREIGN_LISTINGS: dict[str, tuple[str, str, set[str]]] = {
    "ASX": (".AX", "AUD", {"ASX"}),
    "TSXV": (".V", "CAD", {"VAN"}),
    "TSX": (".TO", "CAD", {"TOR"}),
    "XSTO": (".ST", "SEK", {"STO"}),
    "FNSE": (".ST", "SEK", {"STO"}),
    "WSE": (".WA", "PLN", {"WSE"}),
}


def symbol_for(security: Security | SecurityView, *, provisional: bool = False) -> str:
    """Resolve a supported provider symbol from the recorded listing identity."""
    if security.currency != Currency.USD:
        raise ValueError(f"{security.ticker}: recorded cash amounts must be in USD")
    if security.exchange in FOREIGN_LISTINGS:
        return security.ticker + FOREIGN_LISTINGS[security.exchange][0]
    supported: bool = security.exchange in EXCHANGES or (
        provisional and security.exchange == "UNVERIFIED"
    )
    if not supported:
        raise ValueError(f"{security.ticker}: confirm a supported listing exchange")
    return security.ticker.replace(".", "-")


def verify_exchange(
    security: Security | SecurityView, history: History, *, provisional: bool = False
) -> None:
    """Reject provider histories whose exchange does not match the recorded listing."""
    allowed: set[str] | frozenset[str]
    if security.exchange in FOREIGN_LISTINGS:
        allowed = FOREIGN_LISTINGS[security.exchange][2]
    elif provisional and security.exchange == "UNVERIFIED":
        allowed = PROVIDER_EXCHANGES
    else:
        allowed = EXCHANGES[security.exchange]
    if history.exchange not in allowed:
        raise ValueError(f"{security.ticker}: provider listing does not match {security.exchange}")
