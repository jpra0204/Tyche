"""The signals stage: what each strategy is shown, and what happens to what it returns."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of
from tests.support.recording import Recorder, TickingClock
from tyche.core.domain import (
    BarHistory,
    Currency,
    Instrument,
    Money,
    ScoredInstrument,
    StrategyPosition,
    Target,
    Timeframe,
    WarmingUp,
)
from tyche.core.events import (
    BarEvent,
    EventBus,
    HandlerError,
    ScreeningEvent,
    SignalEvent,
    SignalsReadyEvent,
)
from tyche.core.pipeline.signals import (
    HistoryError,
    HistoryView,
    SignalsError,
    SignalsStage,
    StrategyContext,
)

D1 = Timeframe.D1
DAYS = JANUARY_2024[:5]
AS_OF = close_of(DAYS[-1])

type Decide = Callable[[StrategyContext], Sequence[Target]]


@dataclass
class Fake:
    """A strategy whose decision is a function given by the test. Records every context."""

    strategy_id: str = "fake"
    lookback: int = 3
    decision: Decide = lambda context: ()
    version: str = "1"
    timeframe: Timeframe = D1
    seen: list[StrategyContext] = field(default_factory=list)

    def decide(self, context: StrategyContext) -> Sequence[Target]:
        self.seen.append(context)
        return self.decision(context)


def all_in() -> Decide:
    return lambda context: (Target(SPY, Decimal(1), "all in"),)


@dataclass
class Book:
    held: dict[str, tuple[StrategyPosition, ...]]

    def positions_of(self, strategy_id: str) -> tuple[StrategyPosition, ...]:
        return self.held.get(strategy_id, ())


def ranking(*instruments: Instrument) -> ScreeningEvent:
    ranked = tuple(ScoredInstrument(i, 10.0 - n) for n, i in enumerate(instruments))
    return ScreeningEvent(AS_OF, "dollar_volume", ranked)


def run(
    strategies: Sequence[Fake],
    *,
    spy_days: list[date] = DAYS,
    qqq_days: list[date] = DAYS,
    screening: ScreeningEvent | None = None,
    book: Book | None = None,
) -> tuple[Recorder, SignalsStage]:
    """Publish the bars, then one ranking of SPY and QQQ at ``AS_OF``."""
    bus = EventBus(TickingClock().now)
    stage = SignalsStage(bus, strategies, positions=book)
    recorder = Recorder(bus)
    for day in DAYS:
        if day in spy_days:
            bus.publish(BarEvent(bar(day, 100.0 + day.day)), source="replay")
        if day in qqq_days:
            bus.publish(BarEvent(bar(day, 300.0 + day.day, instrument=QQQ)), source="replay")
    bus.publish(screening or ranking(SPY, QQQ), source="screening", cycle_id="c1")
    bus.drain()
    return recorder, stage


def signals(recorder: Recorder) -> list[SignalEvent]:
    return [e for e in recorder.events if isinstance(e, SignalEvent)]


def ready(recorder: Recorder) -> SignalsReadyEvent:
    [event] = [e for e in recorder.events if isinstance(e, SignalsReadyEvent)]
    return event


class TestWhatAStrategyIsShown:
    def test_the_ranking_and_exactly_lookback_bars_ending_now(self) -> None:
        strategy = Fake(lookback=3)

        run([strategy])

        [context] = strategy.seen
        assert context.as_of == AS_OF
        assert context.instruments == (SPY, QQQ)
        assert [b.timestamp for b in context.history.bars(SPY, D1)] == [
            close_of(d) for d in DAYS[2:]
        ]
        assert context.history.closes(QQQ, D1) == (304.0, 305.0, 308.0)

    def test_an_instrument_short_of_history_is_flagged_and_not_offered(self) -> None:
        strategy = Fake(lookback=4)

        recorder, _ = run([strategy], qqq_days=DAYS[2:])

        [context] = strategy.seen
        assert context.instruments == (SPY,)
        assert context.warming_up == (WarmingUp(QQQ, 3, 4),)
        with pytest.raises(HistoryError):
            context.history.bars(QQQ, D1)
        [signal] = signals(recorder)
        assert signal.warming_up == (WarmingUp(QQQ, 3, 4),)

    def test_each_strategy_gets_its_own_lookback(self) -> None:
        short, long = Fake("short", lookback=2), Fake("long", lookback=5)

        run([short, long])

        assert len(short.seen[0].history.bars(SPY, D1)) == 2
        assert len(long.seen[0].history.bars(SPY, D1)) == 5

    def test_its_own_positions(self) -> None:
        held = StrategyPosition(SPY, Decimal(2), date(2024, 1, 3), Money.of("103", Currency.USD))
        strategy = Fake("mine")

        run([strategy, Fake("other")], book=Book({"mine": (held,)}))

        assert strategy.seen[0].positions == (held,)
        assert strategy.seen[0].position(SPY) == held
        assert strategy.seen[0].position(QQQ) is None

    def test_no_positions_until_execution_exists(self) -> None:
        strategy = Fake()

        run([strategy])

        assert strategy.seen[0].positions == ()

    def test_nothing_later_than_the_decision_time(self) -> None:
        strategy = Fake(lookback=5)

        run([strategy])

        context = strategy.seen[0]
        for instrument in context.instruments:
            assert all(b.timestamp <= AS_OF for b in context.history.bars(instrument, D1))

    def test_the_warm_up_fills_windows_before_the_first_event(self) -> None:
        strategy = Fake(lookback=5)
        bus = EventBus(TickingClock().now)
        stage = SignalsStage(bus, [strategy])
        Recorder(bus)
        stage.warm_up([BarHistory(SPY, tuple(bar(d) for d in DAYS[:4]))], through=close_of(DAYS[3]))
        bus.publish(BarEvent(bar(DAYS[4])), source="replay")
        bus.publish(ranking(SPY), source="screening")
        bus.drain()

        assert strategy.seen[0].instruments == (SPY,)
        assert stage.history_needed == {D1: 5}


class TestWhatTheStagePublishes:
    def test_one_signal_per_strategy_then_one_ready_in_the_screenings_cycle(self) -> None:
        recorder, _ = run([Fake("a", decision=all_in()), Fake("b")])

        trace = [
            t
            for t in recorder.trace
            if t[1] in {"ScreeningEvent", "SignalEvent", "SignalsReadyEvent"}
        ]
        assert [(t[1], t[2], t[4]) for t in trace] == [
            ("ScreeningEvent", "screening", "c1"),
            ("SignalEvent", "signals", "c1"),
            ("SignalEvent", "signals", "c1"),
            ("SignalsReadyEvent", "signals", "c1"),
        ]
        a, b = signals(recorder)
        assert (a.strategy_id, a.strategy_version, a.as_of) == ("a", "1", AS_OF)
        assert a.targets == (Target(SPY, Decimal(1), "all in"),)
        assert b.targets == ()
        assert ready(recorder).reported == ("a", "b")

    def test_an_empty_ranking_still_asks_every_strategy(self) -> None:
        strategy = Fake()

        recorder, _ = run([strategy], screening=ScreeningEvent(AS_OF, "s", ()))

        assert strategy.seen[0].instruments == ()
        assert ready(recorder).reported == ("fake",)


def boom(context: StrategyContext) -> Sequence[Target]:
    raise RuntimeError("division by zero in my indicator")


class TestAFailingStrategy:
    def test_is_recorded_and_the_others_still_report(self) -> None:
        recorder, _ = run([Fake("broken", decision=boom), Fake("fine", decision=all_in())])

        assert [s.strategy_id for s in signals(recorder)] == ["fine"]
        result = ready(recorder)
        assert result.reported == ("fine",)
        [failure] = result.failed
        assert failure.strategy_id == "broken"
        assert failure.error == "RuntimeError: division by zero in my indicator"

    def test_asking_for_history_it_was_not_given_is_a_failure(self) -> None:
        def peek(context: StrategyContext) -> Sequence[Target]:
            context.history.bars(QQQ, D1)
            return ()

        recorder, _ = run([Fake(lookback=4, decision=peek)], qqq_days=DAYS[2:])

        [failure] = ready(recorder).failed
        assert failure.error.startswith("HistoryError")

    @pytest.mark.parametrize(
        ("decision", "message"),
        [
            (
                lambda c: (Target(SPY, Decimal("0.7"), "a"), Target(QQQ, Decimal("0.4"), "b")),
                "add up to 1.1",
            ),
            (
                lambda c: (Target(SPY, Decimal("0.5"), "a"), Target(SPY, Decimal("0.5"), "b")),
                "more than once",
            ),
            (lambda c: ("SPY",), "not a Target"),
            (
                lambda c: (Target(SPY, Decimal(1), "a", Money.of("110", Currency.USD)),),
                "not below its last close 108.0",
            ),
        ],
    )
    def test_targets_that_break_the_contract_are_a_failure(
        self, decision: Decide, message: str
    ) -> None:
        recorder, _ = run([Fake(decision=decision)])

        assert signals(recorder) == []
        [failure] = ready(recorder).failed
        assert message in failure.error

    def test_targeting_an_instrument_it_was_not_offered_is_a_failure(self) -> None:
        recorder, _ = run(
            [Fake(lookback=4, decision=lambda c: (Target(QQQ, Decimal(1), "x"),))],
            qqq_days=DAYS[2:],
        )

        [failure] = ready(recorder).failed
        assert "not offered this cycle" in failure.error

    def test_a_stop_below_the_close_is_accepted(self) -> None:
        stop = Money.of("100", Currency.USD)

        recorder, _ = run([Fake(decision=lambda c: (Target(SPY, Decimal(1), "a", stop),))])

        [signal] = signals(recorder)
        assert signal.targets[0].stop_price == stop


class TestTheStageItself:
    def test_a_ranked_instrument_without_a_current_bar_halts_the_run(self) -> None:
        with pytest.raises(HandlerError) as raised:
            run([Fake()], qqq_days=DAYS[:-1])

        assert isinstance(raised.value.__cause__, SignalsError)
        assert "QQQ@XNAS is ranked" in str(raised.value.__cause__)

    def test_needs_at_least_one_strategy(self) -> None:
        with pytest.raises(SignalsError, match="at least one"):
            SignalsStage(EventBus(TickingClock().now), [])

    def test_ids_must_be_unique(self) -> None:
        with pytest.raises(SignalsError, match="unique"):
            SignalsStage(EventBus(TickingClock().now), [Fake("a"), Fake("a")])

    @pytest.mark.parametrize(
        ("strategy", "message"),
        [
            (Fake("Bad"), "invalid strategy id"),
            (Fake(version=" "), "needs a version"),
            (Fake(timeframe=Timeframe.H1), "daily only"),
            (Fake(lookback=0), "at least 1"),
        ],
    )
    def test_refuses_a_strategy_that_declares_itself_wrongly(
        self, strategy: Fake, message: str
    ) -> None:
        with pytest.raises(SignalsError, match=message):
            SignalsStage(EventBus(TickingClock().now), [strategy])


class TestStrategyContext:
    VIEW = HistoryView(AS_OF, {}, 1)

    def test_the_view_must_be_for_the_same_decision_time(self) -> None:
        with pytest.raises(ValueError, match="another decision time"):
            StrategyContext(close_of(DAYS[0]), (), (), self.VIEW)

    def test_a_position_cannot_appear_twice(self) -> None:
        held = StrategyPosition(SPY, Decimal(1), DAYS[0], Money.of("100", Currency.USD))

        with pytest.raises(ValueError, match="more than once"):
            StrategyContext(AS_OF, (), (), self.VIEW, (held, held))
