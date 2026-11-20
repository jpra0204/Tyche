"""The trend rotation, decided on contexts built by hand.

Tests use short windows (a 2-session return, a 3-session average) so every number can
be checked by eye. The windows end on 1 February 2024, the first session of a month,
or on 31 January, which is not.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.support.market import QQQ, SPY, bar, close_of
from tyche.core.domain import (
    AssetClass,
    Currency,
    Instrument,
    Money,
    ScoredInstrument,
    StrategyPosition,
    Target,
    Timeframe,
)
from tyche.core.pipeline.signals import HistoryView, Strategy, StrategyContext
from tyche.strategies import PLUGINS, TrendRotation

TLT = Instrument("TLT", "XNAS", Currency.USD, "XNYS", AssetClass.ETF)
GLD = Instrument("GLD", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)

FEBRUARY_1 = [date(2024, 1, 30), date(2024, 1, 31), date(2024, 2, 1)]
JANUARY_31 = [date(2024, 1, 29), date(2024, 1, 30), date(2024, 1, 31)]
THIRD = Decimal(1) / Decimal(3)


def rotation(*instruments: Instrument, holdings: int = 2) -> TrendRotation:
    return TrendRotation(
        instruments or (SPY, QQQ, TLT, GLD),
        holdings=holdings,
        momentum_sessions=2,
        trend_sessions=3,
    )


def context(
    closes: Mapping[Instrument, Sequence[float]],
    days: Sequence[date] = FEBRUARY_1,
    positions: tuple[StrategyPosition, ...] = (),
) -> StrategyContext:
    as_of = close_of(days[-1])
    windows = {
        (i, Timeframe.D1): tuple(
            bar(day, close, instrument=i) for day, close in zip(days, series, strict=True)
        )
        for i, series in closes.items()
    }
    ranked = tuple(ScoredInstrument(i, 1.0) for i in closes)
    return StrategyContext(as_of, ranked, (), HistoryView(as_of, windows, len(days)), positions)


def held(instrument: Instrument) -> StrategyPosition:
    return StrategyPosition(instrument, Decimal(5), date(2024, 1, 2), Money.of("100", Currency.USD))


def test_satisfies_the_strategy_contract() -> None:
    strategy: Strategy = rotation()

    assert (strategy.strategy_id, strategy.timeframe, strategy.lookback) == (
        "trend_rotation",
        Timeframe.D1,
        3,
    )
    assert TrendRotation((SPY, QQQ, TLT)).lookback == 200


def test_on_the_first_session_of_a_month_holds_the_best_performers() -> None:
    targets = rotation().decide(
        context(
            {
                SPY: [100.0, 104.0, 110.0],  # +10%, above its average
                QQQ: [100.0, 101.0, 102.0],  # +2%
                TLT: [100.0, 103.0, 105.0],  # +5%, above its average
                GLD: [100.0, 99.0, 98.0],  # -2%
            }
        )
    )

    assert [(t.instrument, t.weight) for t in targets] == [
        (SPY, Decimal("0.5")),
        (TLT, Decimal("0.5")),
        (QQQ, Decimal(0)),
        (GLD, Decimal(0)),
    ]
    assert targets[0].reason == (
        "rank 1 of 4 by 2-session return (+10.0%), close above its 3-session average"
    )
    assert targets[2].reason == "rank 3 of 4 by 2-session return (+2.0%)"


def test_a_top_performer_below_its_average_leaves_its_share_in_cash() -> None:
    # TLT rose over two sessions but sits below its 3-session average.
    [spy, tlt, qqq] = rotation(SPY, QQQ, TLT).decide(
        context(
            {
                SPY: [100.0, 104.0, 110.0],
                QQQ: [100.0, 100.0, 100.0],
                TLT: [100.0, 120.0, 101.0],
            }
        )
    )

    assert (spy.instrument, spy.weight) == (SPY, Decimal("0.5"))
    assert (tlt.instrument, tlt.weight) == (TLT, Decimal(0))
    assert tlt.reason.endswith(
        "but close at or below its 3-session average: its share stays in cash"
    )
    assert qqq.weight == 0


def test_ties_are_broken_by_symbol() -> None:
    same = [100.0, 101.0, 102.0]
    targets = rotation(SPY, QQQ, TLT, holdings=1).decide(context({TLT: same, SPY: same, QQQ: same}))

    assert [t.instrument for t in targets] == [QQQ, SPY, TLT]
    assert targets[0].weight == 1


def test_three_holdings_never_add_up_to_more_than_the_budget() -> None:
    rising = [100.0, 101.0, 103.0]
    targets = rotation(holdings=3).decide(
        context({SPY: rising, QQQ: rising, TLT: rising, GLD: rising})
    )

    assert [t.weight for t in targets] == [THIRD, THIRD, THIRD, Decimal(0)]
    assert sum(t.weight for t in targets) <= 1


def test_between_rebalances_keeps_what_it_holds() -> None:
    closes = {SPY: [100.0, 90.0, 80.0], QQQ: [100.0, 110.0, 120.0]}

    targets = rotation(SPY, QQQ).decide(context(closes, JANUARY_31, positions=(held(SPY),)))

    # SPY is falling and QQQ rising, but nothing changes until the month turns.
    assert targets == (Target(SPY, Decimal("0.5"), "hold until the next monthly rebalance"),)


def test_between_rebalances_with_nothing_held_does_nothing() -> None:
    closes = {SPY: [100.0, 101.0, 102.0], QQQ: [100.0, 101.0, 102.0]}

    assert rotation(SPY, QQQ).decide(context(closes, JANUARY_31)) == ()


def test_ignores_instruments_that_are_not_its_own() -> None:
    closes = {SPY: [100.0, 104.0, 110.0], GLD: [100.0, 120.0, 140.0]}

    targets = rotation(SPY, QQQ).decide(context(closes))

    assert [t.instrument for t in targets] == [SPY]
    assert rotation(QQQ, TLT).decide(context(closes)) == ()


PARAMETERS: dict[str, object] = {
    "holdings": 1,
    "instruments": [
        {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"},
        {"symbol": "QQQ", "exchange": "XNAS", "asset_class": "etf"},
    ],
}
"""A valid ``[parameters]`` table; each test changes one key."""


class TestPlugin:
    @staticmethod
    def lookup(symbol: str, exchange: str, asset_class: AssetClass) -> Instrument:
        return {"SPY": SPY, "QQQ": QQQ}[symbol]

    def test_is_built_from_its_parameters_with_the_agreed_defaults(self) -> None:
        strategy = PLUGINS["trend_rotation"].create("rotation", PARAMETERS, self.lookup)

        assert isinstance(strategy, TrendRotation)
        assert strategy.strategy_id == "rotation"
        assert strategy.instruments == (SPY, QQQ)
        assert (strategy.holdings, strategy.momentum_sessions, strategy.trend_sessions) == (
            1,
            126,
            200,
        )

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            ({"holdings": 3}, "holdings: 3 is more than the 2 instruments listed"),
            ({"holdings": 0}, "greater than or equal to 1"),
            ({"momentum_sessions": 0}, "greater than or equal to 1"),
            ({"instruments": []}, "at least 1 item"),
            (
                {
                    "instruments": [
                        {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"},
                        {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"},
                    ]
                },
                "listed more than once",
            ),
            ({"lots": 2}, "Extra inputs are not permitted"),
        ],
    )
    def test_parameters_are_checked(self, change: dict[str, object], problem: str) -> None:
        with pytest.raises(ValidationError, match=problem):
            PLUGINS["trend_rotation"].create("rotation", {**PARAMETERS, **change}, self.lookup)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"instruments": (SPY, SPY)}, "listed more than once"),
        ({"holdings": 3}, "holdings must be from 1 to the 2 instruments listed, got 3"),
        ({"trend_sessions": 0}, "sessions must be at least 1"),
    ],
)
def test_the_constructor_refuses_nonsense(arguments: dict[str, object], message: str) -> None:
    kwargs: dict[str, object] = {"instruments": (SPY, QQQ), "holdings": 1, **arguments}
    with pytest.raises(ValueError, match=message):
        TrendRotation(**kwargs)  # type: ignore[arg-type]
