"""Decision-cycle events: what each pipeline stage concluded.

See ``docs/architecture/event-catalog.md`` for who publishes and who consumes each one.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tyche.core.domain import (
    Exclusion,
    Instrument,
    ScoredInstrument,
    StrategyFailure,
    Target,
    UniverseMember,
    WarmingUp,
    require_strategy_id,
)
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


@dataclass(frozen=True, slots=True)
class SignalEvent(Event):
    """What one strategy wants to hold at one decision time (ADR-0021).

    Published by the signals stage for each strategy that decided successfully, before
    the cycle's ``SignalsReadyEvent``.

    How portfolio construction reads ``targets`` (PR 13):

    * an instrument in ``targets`` gets that weight of the strategy's budget;
    * an instrument the strategy was offered and did not target gets zero;
    * an instrument the strategy holds but was not offered this cycle (not ranked, or
      in ``warming_up``) keeps its position: a data gap is not a decision to sell.

    Attributes:
        as_of: The decision time, copied from the ``ScreeningEvent``.
        strategy_id: The strategy instance.
        strategy_version: The version of its code, recorded so a result can be traced
            to the code that produced it.
        targets: Weights within the strategy's budget, adding up to at most 1, in the
            order the strategy returned them.
        warming_up: Ranked instruments the strategy was not offered because it does
            not have a full window of history for them yet.
    """

    as_of: datetime
    strategy_id: str
    strategy_version: str
    targets: tuple[Target, ...]
    warming_up: tuple[WarmingUp, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "SignalEvent as_of")
        require_strategy_id(self.strategy_id)
        if not self.strategy_version.strip():
            raise ValueError(f"SignalEvent of {self.strategy_id}: needs a strategy version")
        instruments = [t.instrument for t in self.targets] + [w.instrument for w in self.warming_up]
        if len(set(instruments)) != len(instruments):
            raise ValueError(
                f"SignalEvent of {self.strategy_id}: an instrument appears more than once"
            )
        total = sum((t.weight for t in self.targets), start=Decimal(0))
        if total > 1:
            raise ValueError(
                f"SignalEvent of {self.strategy_id}: weights add up to {total}, more than 1"
            )


@dataclass(frozen=True, slots=True)
class SignalsReadyEvent(Event):
    """Every strategy has been asked at one decision time. Portfolio construction acts on it.

    Attributes:
        as_of: The decision time.
        reported: Strategies that published a ``SignalEvent`` this cycle, in the order
            they were asked.
        failed: Strategies that could not decide, each with the reason. They published
            nothing this cycle.
    """

    as_of: datetime
    reported: tuple[str, ...]
    failed: tuple[StrategyFailure, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "SignalsReadyEvent as_of")
        ids = list(self.reported) + [f.strategy_id for f in self.failed]
        if len(set(ids)) != len(ids):
            raise ValueError("SignalsReadyEvent: a strategy appears more than once")
