"""The portfolio stage: budgets times weights, one sleeve per strategy, holds made explicit."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.support.market import QQQ, SPY
from tests.support.recording import Recorder, TickingClock
from tyche.core.domain import (
    Contribution,
    Currency,
    Instrument,
    InstrumentTarget,
    Money,
    Sleeve,
    SleeveStatus,
    StrategyFailure,
    Target,
)
from tyche.core.events import (
    Event,
    EventBus,
    HandlerError,
    SignalEvent,
    SignalsReadyEvent,
    TargetPortfolioEvent,
)
from tyche.core.pipeline.portfolio import PortfolioError, PortfolioStage

AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)
BUDGETS = {"trend": Decimal("0.6"), "hold": Decimal("0.4")}
STOP = Money.of("95", Currency.USD)


def signal(
    strategy_id: str,
    *targets: Target,
    offered: tuple[Instrument, ...] = (SPY, QQQ),
    as_of: datetime = AS_OF,
) -> SignalEvent:
    return SignalEvent(as_of, strategy_id, "1", offered, targets)


def construct(
    *events: Event, budgets: dict[str, Decimal] = BUDGETS
) -> tuple[TargetPortfolioEvent, Recorder]:
    bus = EventBus(TickingClock().now)
    PortfolioStage(bus, budgets)
    recorder = Recorder(bus)
    for event in events:
        bus.publish(event, source="signals", cycle_id="c1")
    bus.drain()
    [portfolio] = [e for e in recorder.events if isinstance(e, TargetPortfolioEvent)]
    return portfolio, recorder


def test_a_strategys_weights_are_scaled_by_its_budget() -> None:
    portfolio, _ = construct(
        signal("trend", Target(SPY, Decimal("0.5"), "up"), Target(QQQ, Decimal("0.5"), "up")),
        signal("hold"),
        SignalsReadyEvent(AS_OF, ("hold", "trend")),
    )

    assert portfolio.as_of == AS_OF
    assert portfolio.targets == (
        InstrumentTarget(QQQ, (Contribution("trend", Decimal("0.30"), "up"),)),
        InstrumentTarget(SPY, (Contribution("trend", Decimal("0.30"), "up"),)),
    )


def test_strategies_on_one_instrument_add_up_and_each_keeps_its_own_stop() -> None:
    portfolio, _ = construct(
        signal("trend", Target(SPY, Decimal("0.5"), "breakout", STOP)),
        signal("hold", Target(SPY, Decimal(1), "benchmark")),
        SignalsReadyEvent(AS_OF, ("trend", "hold")),
    )

    [spy] = portfolio.targets
    assert spy.weight == Decimal("0.70")
    assert spy.contributions == (
        Contribution("hold", Decimal("0.4"), "benchmark"),
        Contribution("trend", Decimal("0.30"), "breakout", STOP),
    )


def test_every_strategy_gets_a_sleeve_saying_what_it_decided_on() -> None:
    portfolio, _ = construct(
        signal("trend", offered=(SPY,)),
        signal("hold"),
        SignalsReadyEvent(AS_OF, ("trend", "hold")),
    )

    assert portfolio.sleeves == (
        Sleeve("hold", Decimal("0.4"), SleeveStatus.DECIDED, (SPY, QQQ), "1"),
        Sleeve("trend", Decimal("0.6"), SleeveStatus.DECIDED, (SPY,), "1"),
    )
    assert portfolio.targets == ()


def test_an_exit_is_a_zero_contribution_with_its_reason() -> None:
    portfolio, _ = construct(
        signal("trend", Target(SPY, Decimal(0), "trend broke")),
        signal("hold"),
        SignalsReadyEvent(AS_OF, ("trend", "hold")),
    )

    [spy] = portfolio.targets
    assert spy.contributions == (Contribution("trend", Decimal("0.0"), "trend broke"),)


def test_a_failed_strategy_gets_a_failed_sleeve_so_its_holdings_are_kept() -> None:
    portfolio, _ = construct(
        signal("hold", Target(SPY, Decimal(1), "benchmark")),
        SignalsReadyEvent(AS_OF, ("hold",), (StrategyFailure("trend", "RuntimeError: boom"),)),
    )

    trend = portfolio.sleeve("trend")
    assert trend.status is SleeveStatus.FAILED
    assert trend.error == "RuntimeError: boom"
    assert trend.decided_on == ()
    assert [c.strategy_id for t in portfolio.targets for c in t.contributions] == ["hold"]


def test_nothing_is_carried_from_one_cycle_to_the_next() -> None:
    later = datetime(2024, 1, 8, 21, 0, tzinfo=UTC)
    bus = EventBus(TickingClock().now)
    PortfolioStage(bus, {"hold": Decimal(1)})
    recorder = Recorder(bus)
    for event in (
        signal("hold", Target(SPY, Decimal(1), "x")),
        SignalsReadyEvent(AS_OF, ("hold",)),
        signal("hold", offered=(), as_of=later),
        SignalsReadyEvent(later, ("hold",)),
    ):
        bus.publish(event, source="signals")
    bus.drain()

    first, second = [e for e in recorder.events if isinstance(e, TargetPortfolioEvent)]
    assert len(first.targets) == 1
    assert second.targets == ()
    assert second.sleeve("hold").decided_on == ()


def test_is_published_by_portfolio_in_the_cycle_of_the_signals() -> None:
    _, recorder = construct(
        signal("trend"), signal("hold"), SignalsReadyEvent(AS_OF, ("trend", "hold"))
    )

    last = recorder.envelopes[-1]
    assert isinstance(last.event, TargetPortfolioEvent)
    assert (last.source, last.cycle_id, last.caused_by) == ("portfolio", "c1", 3)


class TestWiringMistakesHaltTheRun:
    @pytest.mark.parametrize(
        ("events", "message"),
        [
            ((signal("other"),), "a signal from other, which has no budget"),
            ((signal("trend"), signal("trend")), "two signals from trend"),
            (
                (signal("trend"), signal("hold"), SignalsReadyEvent(AS_OF, ("trend",))),
                "do not match strategies with a budget",
            ),
            (
                (signal("trend"), SignalsReadyEvent(AS_OF, ("trend", "hold"))),
                "but ['hold', 'trend'] reported",
            ),
            (
                (
                    signal("trend", as_of=datetime(2024, 1, 4, 21, 0, tzinfo=UTC)),
                    signal("hold"),
                    SignalsReadyEvent(AS_OF, ("trend", "hold")),
                ),
                "trend's signal is for 2024-01-04",
            ),
        ],
    )
    def test_inputs_that_do_not_fit(self, events: tuple[Event, ...], message: str) -> None:
        bus = EventBus(TickingClock().now)
        PortfolioStage(bus, BUDGETS)
        for event in events:
            bus.publish(event, source="signals")

        with pytest.raises(HandlerError) as raised:
            bus.drain()

        assert isinstance(raised.value.__cause__, PortfolioError)
        assert message in str(raised.value.__cause__)

    def test_invalid_budgets_are_refused_at_construction(self) -> None:
        with pytest.raises(PortfolioError, match=r"add up to 1\.2"):
            PortfolioStage(EventBus(TickingClock().now), {"a": Decimal("0.6"), "b": Decimal("0.6")})
