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


@dataclass(frozen=True, slots=True)
class DataQualityEvent(Event):
    """A problem was found in market data (ADR-0018)."""

    issue: DataIssue
