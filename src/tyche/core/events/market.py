"""Market-data and time events: what the outside world tells the pipeline.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from tyche.core.domain import Bar, DataIssue, Instrument, Session, Timeframe
from tyche.core.domain.validation import require_utc
from tyche.core.events.event import Event


class SessionPhase(StrEnum):
    OPEN = "open"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class SessionEvent(Event):
    """A market opened or closed."""

    session: Session
    phase: SessionPhase


@dataclass(frozen=True, slots=True)
class BarEvent(Event):
    """A bar became known: published at the bar's own timestamp, never earlier."""

    bar: Bar


@dataclass(frozen=True, slots=True)
class DataReadyEvent(Event):
    """Every bar for one decision time has been delivered. Starts a decision cycle.

    Stages that need a complete picture act on this event, not on individual bars.
    That is what lets daily and intraday data share one code path: only the timeframe
    and the spacing of these events differ.

    Attributes:
        timeframe: The bars' timeframe.
        as_of: The decision time: the close of the bars just delivered.
        delivered: Instruments with a bar for ``as_of``.
        missing: Instruments expected at ``as_of`` that have no bar.
    """

    timeframe: Timeframe
    as_of: datetime
    delivered: tuple[Instrument, ...]
    missing: tuple[Instrument, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "DataReadyEvent as_of")


class SkipReason(StrEnum):
    """Why a session's decision cycle did not run (ADR-0043)."""

    STALE = "stale"
    """The decision could no longer trade: the moment to send orders for the next open
    had passed when the session was published."""
    INCOMPLETE = "incomplete"
    """A candidate had no bar for the session once its bars counted as final."""


@dataclass(frozen=True, slots=True)
class CycleSkippedEvent(Event):
    """A session's bars were delivered, but its decision cycle does not run.

    Published by the daily feed in place of the ``DataReadyEvent`` that would have
    started the cycle (ADR-0043). The session's bars, data problems and closes are
    still published, so the signals windows, Tyche's account view and the account
    rules see every close; only the decision is skipped, and no order is sent.

    Attributes:
        timeframe: The bars' timeframe.
        as_of: The close of the session whose cycle is skipped.
        reason: Why it is skipped.
        trade_until: The last moment its decision could have traded.
        delivered: Instruments with a bar for ``as_of``.
        missing: Candidates with no bar for ``as_of``.
    """

    timeframe: Timeframe
    as_of: datetime
    reason: SkipReason
    trade_until: datetime
    delivered: tuple[Instrument, ...]
    missing: tuple[Instrument, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "CycleSkippedEvent as_of")
        require_utc(self.trade_until, "CycleSkippedEvent trade_until")
        if self.reason is SkipReason.INCOMPLETE and not self.missing:
            raise ValueError("an incomplete cycle must name the candidates with no bar")


@dataclass(frozen=True, slots=True)
class DataQualityEvent(Event):
    """A problem was found in market data (ADR-0018)."""

    issue: DataIssue
