"""Listing identities and provider exchange validation."""

from investor_platform.domain import Currency

EXCHANGES = {
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


PROVIDER_EXCHANGES = frozenset().union(*EXCHANGES.values())


FOREIGN_LISTINGS = {
    "ASX": (".AX", "AUD", {"ASX"}),
    "TSXV": (".V", "CAD", {"VAN"}),
    "TSX": (".TO", "CAD", {"TOR"}),
    "XSTO": (".ST", "SEK", {"STO"}),
    "FNSE": (".ST", "SEK", {"STO"}),
    "WSE": (".WA", "PLN", {"WSE"}),
}


def symbol_for(security, *, provisional=False):
    if security.currency != Currency.USD:
        raise ValueError(f"{security.ticker}: recorded cash amounts must be in USD")
    if security.exchange in FOREIGN_LISTINGS:
        return security.ticker + FOREIGN_LISTINGS[security.exchange][0]
    supported = security.exchange in EXCHANGES or (
        provisional and security.exchange == "UNVERIFIED"
    )
    if not supported:
        raise ValueError(f"{security.ticker}: confirm a supported listing exchange")
    return security.ticker.replace(".", "-")


def verify_exchange(security, history, *, provisional=False):
    if security.exchange in FOREIGN_LISTINGS:
        allowed = FOREIGN_LISTINGS[security.exchange][2]
    elif provisional and security.exchange == "UNVERIFIED":
        allowed = PROVIDER_EXCHANGES
    else:
        allowed = EXCHANGES[security.exchange]
    if history.exchange not in allowed:
        raise ValueError(f"{security.ticker}: provider listing does not match {security.exchange}")
