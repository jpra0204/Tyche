"""Decision-cycle events: what each pipeline stage concluded.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass
from datetime import datetime

from tyche.core.domain import Exclusion, Instrument, ScoredInstrument, UniverseMember
from tyche.core.domain.validation import require_utc
from tyche.core.events.event import Event


@dataclass(frozen=True, slots=True)
class UniverseEvent(Event):
    """Which instruments are eligible at one decision time. Published once per cycle.

    Every instrument the feed expected at ``as_of`` appears exactly once, either in
    ``eligible`` or in ``excluded``, so the journal can always say why an instrument
    was not traded.

    Attributes:
        as_of: The decision time, copied from the ``DataReadyEvent``.
        eligible: Instruments that passed every rule, with their measurements, in the
            feed's order.
        excluded: Instruments that failed a rule, each with the first rule it failed,
            in the feed's order.
    """

    as_of: datetime
    eligible: tuple[UniverseMember, ...]
    excluded: tuple[Exclusion, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "UniverseEvent as_of")
        instruments = [m.instrument for m in self.eligible] + [e.instrument for e in self.excluded]
        if len(set(instruments)) != len(instruments):
            raise ValueError("UniverseEvent: an instrument appears more than once")


@dataclass(frozen=True, slots=True)
class ScreeningEvent(Event):
    """The eligible instruments, ranked by one screen. Published once per cycle.

    Attributes:
        as_of: The decision time, copied from the ``UniverseEvent``.
        screen: Name of the screen that produced the ranking.
        ranked: The instruments kept, best first.
        cut: Eligible instruments ranked below the screen's limit, best first. Empty
            when the screen has no limit.
    """

    as_of: datetime
    screen: str
    ranked: tuple[ScoredInstrument, ...]
    cut: tuple[Instrument, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "ScreeningEvent as_of")
        if not self.screen:
            raise ValueError("ScreeningEvent: screen needs a name")
        instruments = [s.instrument for s in self.ranked] + list(self.cut)
        if len(set(instruments)) != len(instruments):
            raise ValueError("ScreeningEvent: an instrument appears more than once")
        scores = [s.score for s in self.ranked]
        if scores != sorted(scores, reverse=True):
            raise ValueError("ScreeningEvent: ranked must be in descending order of score")
