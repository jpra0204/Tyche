"""Bar: one instrument's prices over one period."""

import math
from dataclasses import dataclass
from datetime import datetime

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.timeframe import Timeframe
from tyche.core.domain.validation import require_utc


@dataclass(frozen=True, slots=True)
class Bar:
    """Open, high, low, close and volume for one instrument over one period.

    A ``Bar`` that exists is valid: construction fails on a naive or non-UTC timestamp,
    a non-finite or non-positive price, a high or low that contradicts the other prices,
    or a negative volume. Bad vendor data is therefore stopped at the data adapter,
    which reports it, and never reaches a strategy.

    Prices are ``float`` because market data is an input to estimates (ADR-0012). They
    become ``Decimal`` at the single point where a simulated fill takes a price.

    Attributes:
        instrument: What the bar describes.
        timeframe: The period it covers.
        timestamp: When the bar closed, timezone-aware UTC. This is the moment the bar
            became known, so comparing it with the clock answers "could we have known
            this yet?". A daily bar is stamped at its session's close, not at midnight.
        open, high, low, close: Prices in the instrument's currency.
        volume: Units traded during the period.
        is_adjusted: True if prices are adjusted for splits and dividends.
    """

    instrument: Instrument
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_adjusted: bool

    def __post_init__(self) -> None:
        require_utc(self.timestamp, f"{self._label()}: timestamp")

        prices = {"open": self.open, "high": self.high, "low": self.low, "close": self.close}
        for name, price in prices.items():
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"{self._label()}: {name} must be a positive number, got {price}")

        if self.high < max(self.open, self.close, self.low):
            raise ValueError(f"{self._label()}: high {self.high} is below another price in the bar")
        if self.low > min(self.open, self.close):
            raise ValueError(f"{self._label()}: low {self.low} is above the open or the close")

        if not math.isfinite(self.volume) or self.volume < 0:
            raise ValueError(f"{self._label()}: volume must be zero or more, got {self.volume}")

    def _label(self) -> str:
        return f"{self.instrument} {self.timeframe} bar at {self.timestamp.isoformat()}"
