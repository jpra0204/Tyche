"""The buy-and-hold benchmark, tested as every strategy can be: by building a context."""

from datetime import date
from decimal import Decimal

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of
from tyche.core.domain import (
    Currency,
    Money,
    ScoredInstrument,
    StrategyPosition,
    Target,
    Timeframe,
    WarmingUp,
)
from tyche.core.pipeline.signals import HistoryView, Strategy, StrategyContext
from tyche.strategies import BuyAndHold

AS_OF = close_of(JANUARY_2024[0])


def context(
    *ranked: ScoredInstrument,
    warming_up: tuple[WarmingUp, ...] = (),
    positions: tuple[StrategyPosition, ...] = (),
) -> StrategyContext:
    windows = {
        (s.instrument, Timeframe.D1): (bar(JANUARY_2024[0], instrument=s.instrument),)
        for s in ranked
    }
    return StrategyContext(AS_OF, ranked, warming_up, HistoryView(AS_OF, windows, 1), positions)


def test_satisfies_the_strategy_contract() -> None:
    strategy: Strategy = BuyAndHold(SPY)

    assert (strategy.strategy_id, strategy.timeframe, strategy.lookback) == (
        "buy_and_hold",
        Timeframe.D1,
        1,
    )


def test_puts_the_whole_budget_in_its_instrument() -> None:
    targets = BuyAndHold(SPY).decide(
        context(ScoredInstrument(QQQ, 2.0), ScoredInstrument(SPY, 1.0))
    )

    assert targets == (Target(SPY, Decimal(1), "buy and hold SPY@ARCX: enter"),)


def test_says_hold_once_it_holds_the_position() -> None:
    held = StrategyPosition(SPY, Decimal(2), date(2023, 12, 1), Money.of("455", Currency.USD))

    [target] = BuyAndHold(SPY).decide(context(ScoredInstrument(SPY, 1.0), positions=(held,)))

    assert target.weight == 1
    assert target.reason == "buy and hold SPY@ARCX: hold since 2023-12-01"


def test_returns_nothing_while_its_instrument_is_not_eligible() -> None:
    # Returning nothing is not a sell: portfolio construction keeps the position (ADR-0021).
    assert BuyAndHold(SPY).decide(context(ScoredInstrument(QQQ, 1.0))) == ()


def test_another_instance_can_hold_another_instrument() -> None:
    strategy = BuyAndHold(QQQ, strategy_id="hold_qqq")

    [target] = strategy.decide(context(ScoredInstrument(QQQ, 1.0)))

    assert strategy.strategy_id == "hold_qqq"
    assert target.instrument == QQQ
