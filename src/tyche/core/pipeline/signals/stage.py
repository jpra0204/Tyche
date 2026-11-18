"""SignalsStage: pipeline stage 3, what each strategy wants to hold.

The stage keeps a window of recent bars from the ``BarEvent``s it is sent. At each
``ScreeningEvent`` it builds one ``StrategyContext`` per strategy and asks it to decide
(ADR-0021). For every strategy that decides within the rules it publishes a
``SignalEvent``; then one ``SignalsReadyEvent`` saying who reported and who failed.

Two kinds of problem, handled differently:

* **A strategy's fault**: it raised, or returned targets that break the contract.
  Recorded in ``SignalsReadyEvent.failed``; the other strategies and the run go on.
* **The stage's inputs are wrong**: bars out of order or on mixed bases, or a ranked
  instrument without a bar for the decision time. A bug upstream: the run halts
  (fail closed, ADR-0003).
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from tyche.core.domain import (
    Bar,
    BarHistory,
    Instrument,
    ScoredInstrument,
    StrategyFailure,
    Target,
    Timeframe,
    WarmingUp,
    require_strategy_id,
)
from tyche.core.events import (
    BarEvent,
    Envelope,
    EventBus,
    ScreeningEvent,
    SignalEvent,
    SignalsReadyEvent,
)
from tyche.core.pipeline.signals.strategy import (
    NoPositions,
    PositionBook,
    Strategy,
    StrategyContext,
)
from tyche.core.pipeline.signals.windows import BarWindows, HistoryView, WindowKey

SUBSCRIBER = "signals"


class SignalsError(Exception):
    """The stage was set up wrongly or its inputs broke an assumption. Not a strategy's fault."""


class StrategyContractError(Exception):
    """A strategy returned targets that break the strategy contract."""


class SignalsStage:
    """Pipeline stage 3. Publishes signals for every ``ScreeningEvent``.

    Subscribe it before anything is published, like every other component, and call
    ``warm_up`` before the first event if windows should start full.

    Args:
        bus: The run's event bus.
        strategies: The strategies to ask, in the order they are asked. Their
            identifiers must be unique.
        positions: Where each strategy's current positions come from. Empty until
            execution exists (PR 14).
    """

    def __init__(
        self,
        bus: EventBus,
        strategies: Sequence[Strategy],
        *,
        positions: PositionBook | None = None,
    ) -> None:
        if not strategies:
            raise SignalsError("the signals stage needs at least one strategy")
        ids = [s.strategy_id for s in strategies]
        if len(set(ids)) != len(ids):
            raise SignalsError(f"strategy ids must be unique in a run, got {ids}")
        capacity: dict[Timeframe, int] = {}
        for strategy in strategies:
            _check_declaration(strategy)
            capacity[strategy.timeframe] = max(
                capacity.get(strategy.timeframe, 0), strategy.lookback
            )
        self._bus = bus
        self._strategies = tuple(strategies)
        self._positions = positions or NoPositions()
        self._windows = BarWindows(capacity)
        bus.subscribe(BarEvent, self._on_bar, name=SUBSCRIBER)
        bus.subscribe(ScreeningEvent, self._on_screening, name=SUBSCRIBER)

    @property
    def history_needed(self) -> Mapping[Timeframe, int]:
        """The most bars any strategy needs, per timeframe: how much warm-up to fetch."""
        return self._windows.capacity

    def warm_up(self, histories: Iterable[BarHistory], *, through: datetime) -> None:
        """Fill the windows from cached history up to ``through`` (ADR-0021).

        The one warm-up path for every mode. Call it before the run's first event, with
        ``through`` no later than that event's moment.
        """
        self._windows.seed(histories, through=through)

    # --- what the stage is told ------------------------------------------------------

    def _on_bar(self, envelope: Envelope[BarEvent]) -> None:
        self._windows.add(envelope.event.bar)

    def _on_screening(self, envelope: Envelope[ScreeningEvent]) -> None:
        screening = envelope.event
        self._require_current_bars(screening)
        reported: list[str] = []
        failed: list[StrategyFailure] = []
        for strategy in self._strategies:
            context = self._context(strategy, screening)
            try:
                targets = tuple(strategy.decide(context))
                _check_targets(context, strategy.timeframe, targets)
                signal = SignalEvent(
                    screening.as_of,
                    strategy.strategy_id,
                    strategy.version,
                    context.instruments,
                    targets,
                    context.warming_up,
                )
            except Exception as error:
                # A plugin's failure is reported, not allowed to halt the run (ADR-0021).
                failed.append(StrategyFailure(strategy.strategy_id, _describe(error)))
                continue
            self._bus.publish(signal)
            reported.append(strategy.strategy_id)
        self._bus.publish(SignalsReadyEvent(screening.as_of, tuple(reported), tuple(failed)))

    # --- building a context ------------------------------------------------------------

    def _require_current_bars(self, screening: ScreeningEvent) -> None:
        for scored in screening.ranked:
            for timeframe in self._windows.capacity:
                latest = self._windows.latest(scored.instrument, timeframe)
                if latest is None or latest.timestamp != screening.as_of:
                    seen = latest.timestamp.isoformat() if latest else "none"
                    raise SignalsError(
                        f"{scored.instrument} is ranked at {screening.as_of.isoformat()}, but "
                        f"its newest {timeframe} bar is {seen}"
                    )

    def _context(self, strategy: Strategy, screening: ScreeningEvent) -> StrategyContext:
        timeframe, lookback = strategy.timeframe, strategy.lookback
        offered: list[ScoredInstrument] = []
        warming_up: list[WarmingUp] = []
        windows: dict[WindowKey, tuple[Bar, ...]] = {}
        for scored in screening.ranked:
            instrument = scored.instrument
            held = self._windows.held(instrument, timeframe)
            if held < lookback:
                warming_up.append(WarmingUp(instrument, held, lookback))
                continue
            offered.append(scored)
            windows[(instrument, timeframe)] = self._windows.last(instrument, timeframe, lookback)
        return StrategyContext(
            as_of=screening.as_of,
            ranked=tuple(offered),
            warming_up=tuple(warming_up),
            history=HistoryView(screening.as_of, windows, lookback),
            positions=self._positions.positions_of(strategy.strategy_id),
        )


def _check_declaration(strategy: Strategy) -> None:
    label = f"strategy {strategy.strategy_id!r}"
    try:
        require_strategy_id(strategy.strategy_id)
    except ValueError as error:
        raise SignalsError(str(error)) from error
    if not strategy.version.strip():
        raise SignalsError(f"{label} needs a version")
    if strategy.timeframe is not Timeframe.D1:
        raise SignalsError(
            f"{label} decides on {strategy.timeframe} bars; Phase 1 supports daily only"
        )
    if isinstance(strategy.lookback, bool) or strategy.lookback < 1:
        raise SignalsError(f"{label} needs a lookback of at least 1, got {strategy.lookback}")


def _check_targets(
    context: StrategyContext, timeframe: Timeframe, targets: tuple[Target, ...]
) -> None:
    offered = set(context.instruments)
    seen: set[Instrument] = set()
    total = Decimal(0)
    for target in targets:
        if not isinstance(target, Target):
            raise StrategyContractError(f"returned {target!r}, which is not a Target")
        instrument = target.instrument
        if instrument not in offered:
            raise StrategyContractError(
                f"targeted {instrument}, which it was not offered this cycle"
            )
        if instrument in seen:
            raise StrategyContractError(f"targeted {instrument} more than once")
        seen.add(instrument)
        total += target.weight
        if target.stop_price is not None:
            close = context.history.bars(instrument, timeframe)[-1].close
            if float(target.stop_price.amount) >= close:
                raise StrategyContractError(
                    f"put the stop for {instrument} at {target.stop_price}, not below its "
                    f"last close {close}"
                )
    if total > 1:
        raise StrategyContractError(f"weights add up to {total}, more than 1")


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"
