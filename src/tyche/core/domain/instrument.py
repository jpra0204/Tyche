"""Instrument: something Tyche can hold a position in."""

import re
from dataclasses import dataclass
from enum import StrEnum

from tyche.core.domain.currency import Currency
from tyche.core.domain.validation import require_mic

# Upper-case letters and digits, with single dots or hyphens inside (BRK.B, BRK-B).
_SYMBOL = re.compile(r"[A-Z0-9]+(?:[.\-][A-Z0-9]+)*")


class AssetClass(StrEnum):
    """What kind of thing an instrument is. CDRs and crypto are added in later phases."""

    STOCK = "stock"
    ETF = "etf"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A tradable instrument with everything the core needs to know about it.

    Every instrument carries its own currency, exchange and calendar, so no code has to
    guess them from the symbol or from a global setting. Two instruments are the same
    only if every field matches: ``RY`` on XNYS in USD and ``RY`` on XTSE in CAD are
    different instruments.

    Vendor-specific identifiers (a yfinance ticker such as ``RY.TO``, an IBKR contract
    id) are not stored here. Each adapter maps an ``Instrument`` to its own vendor's
    naming.

    Attributes:
        symbol: The exchange's own ticker, upper case, e.g. ``SPY`` or ``BRK.B``.
        exchange: MIC of the primary listing exchange, e.g. ``ARCX``.
        currency: The currency the instrument is quoted and settled in.
        calendar: MIC of the trading calendar it follows, e.g. ``XNYS``. Usually but
            not always the same as ``exchange``: US exchanges share one calendar.
        asset_class: Stock or ETF.
    """

    symbol: str
    exchange: str
    currency: Currency
    calendar: str
    asset_class: AssetClass

    def __post_init__(self) -> None:
        if not _SYMBOL.fullmatch(self.symbol):
            raise ValueError(
                f"invalid symbol {self.symbol!r}: expected upper-case letters and digits, "
                "optionally separated by single dots or hyphens"
            )
        require_mic(self.exchange, "exchange")
        require_mic(self.calendar, "calendar")

    def __str__(self) -> str:
        return f"{self.symbol}@{self.exchange}"
