"""The signal types: what a strategy decides and what it is told about its holdings.

A strategy returns ``Target``s: how much of its budget it wants in each instrument,
with an optional stop (ADR-0006). It is told about its own holdings as
``StrategyPosition``s, so that a strategy that keeps no state can still tell an entry
from a hold (ADR-0021). ``WarmingUp`` says why an instrument was not offered to a
strategy, and ``StrategyFailure`` records a strategy that could not decide.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money

# Lower case, digits, "_" and "-", starting with a letter: it will name a config file.
_STRATEGY_ID = re.compile(r"[a-z][a-z0-9_-]*")


def require_strategy_id(strategy_id: str) -> None:
    """Raise ``ValueError`` unless ``strategy_id`` is a valid strategy identifier.

    The identifier names a strategy instance in events, in the journal and, from
    PR 13, in the workspace's ``config/strategies/`` folder, so it must be safe as a
    file name.
    """
    if not _STRATEGY_ID.fullmatch(strategy_id):
        raise ValueError(
            f"invalid strategy id {strategy_id!r}: expected lower-case letters, digits, "
            "'_' or '-', starting with a letter"
        )


def _require_stop(stop_price: Money | None, instrument: Instrument, label: str) -> None:
    if stop_price is None:
        return
    if not stop_price.is_positive:
        raise ValueError(f"{label}: stop price must be positive, got {stop_price}")
    if stop_price.currency is not instrument.currency:
        raise ValueError(
            f"{label}: stop price is in {stop_price.currency}, "
            f"{instrument} trades in {instrument.currency}"
        )


@dataclass(frozen=True, slots=True)
class Target:
    """How much of a strategy's budget it wants in one instrument.

    Attributes:
        instrument: What to hold.
        weight: The fraction of the strategy's budget, from 0 to 1. Zero means "hold
            none". Exact, so that a strategy's weights can be checked to add up to at
            most 1 without rounding doubts.
        reason: Why, in words, for the journal.
        stop_price: Where to place a protective stop, or ``None`` for no stop
            (ADR-0006). Tyche is long only, so a stop is below the price.
    """

    instrument: Instrument
    weight: Decimal
    reason: str
    stop_price: Money | None = None

    def __post_init__(self) -> None:
        label = f"target for {self.instrument}"
        if not isinstance(self.weight, Decimal) or not self.weight.is_finite():
            raise ValueError(f"{label}: weight must be a finite Decimal, got {self.weight!r}")
        if not 0 <= self.weight <= 1:
            raise ValueError(f"{label}: weight must be between 0 and 1, got {self.weight}")
        if not self.reason.strip():
            raise ValueError(f"{label}: needs a reason")
        _require_stop(self.stop_price, self.instrument, label)


@dataclass(frozen=True, slots=True)
class StrategyPosition:
    """A strategy's own share of a position, as the strategy is shown it.

    Attributes:
        instrument: What is held.
        quantity: Shares held for this strategy. Positive: Tyche is long only.
        entry_date: Trade date of the first fill that opened the position.
        entry_price: Average price paid per share, in the instrument's currency.
        stop_price: The protective stop resting at the broker, or ``None``.
    """

    instrument: Instrument
    quantity: Decimal
    entry_date: date
    entry_price: Money
    stop_price: Money | None = None

    def __post_init__(self) -> None:
        label = f"position in {self.instrument}"
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError(f"{label}: quantity must be positive, got {self.quantity}")
        if not self.entry_price.is_positive:
            raise ValueError(f"{label}: entry price must be positive")
        if self.entry_price.currency is not self.instrument.currency:
            raise ValueError(
                f"{label}: entry price is in {self.entry_price.currency}, "
                f"{self.instrument} trades in {self.instrument.currency}"
            )
        _require_stop(self.stop_price, self.instrument, label)


@dataclass(frozen=True, slots=True)
class WarmingUp:
    """A ranked instrument a strategy was not offered: it lacks a full window yet.

    Attributes:
        instrument: The instrument left out.
        bars_held: Bars held so far.
        bars_needed: The strategy's lookback.
    """

    instrument: Instrument
    bars_held: int
    bars_needed: int

    def __post_init__(self) -> None:
        if not 0 <= self.bars_held < self.bars_needed:
            raise ValueError(
                f"{self.instrument} is not warming up with {self.bars_held} of "
                f"{self.bars_needed} bars"
            )

    def __str__(self) -> str:
        return f"{self.instrument} warming up: {self.bars_held} of {self.bars_needed} bars"


@dataclass(frozen=True, slots=True)
class StrategyFailure:
    """A strategy that could not decide at one cycle, and why.

    Attributes:
        strategy_id: The strategy instance.
        error: What went wrong: the exception it raised or the rule its targets broke.
    """

    strategy_id: str
    error: str

    def __str__(self) -> str:
        return f"{self.strategy_id}: {self.error}"
