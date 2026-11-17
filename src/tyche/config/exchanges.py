"""Exchanges Tyche knows: the currency each trades in and the calendar it follows.

Used where an instrument must be built from a symbol and an exchange, such as
``tyche data fetch``. Toronto (``XTSE``) is added with the ``CA`` profile in Phase 4.
"""

from dataclasses import dataclass

from tyche.core.domain import Currency


@dataclass(frozen=True, slots=True)
class ExchangeInfo:
    mic: str
    name: str
    currency: Currency
    calendar: str


KNOWN_EXCHANGES: dict[str, ExchangeInfo] = {
    info.mic: info
    for info in (
        ExchangeInfo("XNYS", "New York Stock Exchange", Currency.USD, "XNYS"),
        ExchangeInfo("XNAS", "Nasdaq", Currency.USD, "XNYS"),
        ExchangeInfo("ARCX", "NYSE Arca", Currency.USD, "XNYS"),
        ExchangeInfo("BATS", "Cboe BZX", Currency.USD, "XNYS"),
        ExchangeInfo("XASE", "NYSE American", Currency.USD, "XNYS"),
    )
}
