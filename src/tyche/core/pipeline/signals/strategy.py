"""The strategy plugin contract (ADR-0021).

A strategy is a pure function of its context. It declares how much history it needs,
and at every decision cycle it is handed a ``StrategyContext`` and returns targets. It
has no bus, no clock, no data provider and no memory between cycles: everything it may
know is in the context, and the context holds nothing the clock has not reached.

That is what makes a strategy behave the same in backtest, paper and live, and what
makes it testable by building a context by hand.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tyche.core.domain import (
    Instrument,
    ScoredInstrument,
    StrategyPosition,
    Target,
    Timeframe,
    WarmingUp,
)
from tyche.core.domain.validation import require_utc
from tyche.core.pipeline.signals.windows import HistoryView


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Everything a strategy is told at one decision time.

    Attributes:
        as_of: The decision time: the close of the bars just delivered.
        ranked: The screening ranking, best first, restricted to instruments the
            strategy has a full window for. These are the only instruments it may
            target.
        warming_up: Ranked instruments left out because the strategy does not have
            ``lookback`` bars for them yet. Recorded in its ``SignalEvent``.
        history: Exactly ``lookback`` bars for each instrument in ``ranked``.
        positions: The strategy's own current positions. Empty until execution exists
            (PR 14); see ADR-0021.
    """

    as_of: datetime
    ranked: tuple[ScoredInstrument, ...]
    warming_up: tuple[WarmingUp, ...]
    history: HistoryView
    positions: tuple[StrategyPosition, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of, "StrategyContext as_of")
        if self.history.as_of != self.as_of:
            raise ValueError("StrategyContext: the history view is for another decision time")
        held = [p.instrument for p in self.positions]
        if len(set(held)) != len(held):
            raise ValueError("StrategyContext: a position appears more than once")

    @property
    def instruments(self) -> tuple[Instrument, ...]:
        """The instruments the strategy may target, best ranked first."""
        return tuple(s.instrument for s in self.ranked)

    def position(self, instrument: Instrument) -> StrategyPosition | None:
        """The strategy's position in ``instrument``, or ``None`` if it holds none."""
        for position in self.positions:
            if position.instrument == instrument:
                return position
        return None


class Strategy(Protocol):
    """A trading strategy: turns a context into targets within its own budget.

    Rules for implementers, checked by the signals stage at every cycle:

    * target only instruments in ``context.ranked``, each at most once;
    * weights are ``Decimal`` between 0 and 1 and add up to at most 1;
    * a stop, if any, is below the instrument's last close;
    * keep no state between calls, and be deterministic: the same context must give
      the same targets.

    A strategy that raises, or returns targets that break a rule, is recorded as
    failed for that cycle and publishes nothing; the run goes on.
    """

    @property
    def strategy_id(self) -> str:
        """The instance's identifier, unique in a run, e.g. ``buy_and_hold``."""
        ...

    @property
    def version(self) -> str:
        """The version of the strategy's code. Change it whenever its logic changes."""
        ...

    @property
    def timeframe(self) -> Timeframe:
        """The bars it decides on. Phase 1 supports daily only."""
        ...

    @property
    def lookback(self) -> int:
        """How many bars of history it needs per instrument, at least 1."""
        ...

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        """The targets for this decision time."""
        ...


class PositionBook(Protocol):
    """Where the signals stage gets each strategy's current positions.

    Execution builds the real one from fills in PR 14, once portfolio construction
    records which strategy each order was for (PR 13).
    """

    def positions_of(self, strategy_id: str) -> tuple[StrategyPosition, ...]: ...


class NoPositions:
    """A position book that is always empty: nothing has been traded."""

    def positions_of(self, strategy_id: str) -> tuple[StrategyPosition, ...]:
        return ()
