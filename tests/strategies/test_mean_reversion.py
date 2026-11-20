"""The mean reversion and its stop, decided on contexts built by hand.

Tests use a 20-session trend average so a dip can sit inside an uptrend: sixteen
sessions rising by one, then four falling by one. The four drops take RSI(2) to 6.25
(see ``test_indicators``), below the entry level of 10, while the close of 115 stays
above the 20-session average of 112.5.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

import pytest
from pydantic import ValidationError

from tests.support.market import QQQ, SPY, bar, close_of
from tyche.core.domain import (
    AssetClass,
    Bar,
    Currency,
    Instrument,
    Money,
    ScoredInstrument,
    StrategyPosition,
    Target,
    Timeframe,
)
from tyche.core.pipeline.signals import HistoryView, Strategy, StrategyContext
from tyche.strategies import PLUGINS, MeanReversion
from tyche.strategies.indicators import average_true_range

DIP = [float(c) for c in range(104, 120)] + [118.0, 117.0, 116.0, 115.0]
RISING = [float(c) for c in range(100, 120)]
FALLING = [float(c) for c in range(120, 100, -1)]
DAYS = [date(2024, 1, 1) + timedelta(days=n) for n in range(20)]
AS_OF = close_of(DAYS[-1])


def strategy(*instruments: Instrument) -> MeanReversion:
    return MeanReversion(instruments or (SPY,), trend_sessions=20, exit_sessions=5)


def bars(instrument: Instrument, closes: Sequence[float]) -> tuple[Bar, ...]:
    return tuple(
        bar(day, close, instrument=instrument) for day, close in zip(DAYS, closes, strict=True)
    )


def context(
    closes: Mapping[Instrument, Sequence[float]], positions: tuple[StrategyPosition, ...] = ()
) -> StrategyContext:
    windows = {(i, Timeframe.D1): bars(i, series) for i, series in closes.items()}
    ranked = tuple(ScoredInstrument(i, 1.0) for i in closes)
    return StrategyContext(AS_OF, ranked, (), HistoryView(AS_OF, windows, 20), positions)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


def held(stop: str | None, instrument: Instrument = SPY) -> StrategyPosition:
    return StrategyPosition(
        instrument,
        Decimal(10),
        DAYS[-2],
        usd("116"),
        None if stop is None else usd(stop),
    )


def expected_stop(closes: Sequence[float]) -> Money:
    atr = average_true_range(bars(SPY, closes), 14)
    price = Decimal(repr(closes[-1])) - Decimal("2.5") * Decimal(repr(atr))
    return usd(str(price.quantize(Decimal("0.01"), ROUND_FLOOR)))


def test_satisfies_the_strategy_contract() -> None:
    mine: Strategy = strategy()

    assert (mine.strategy_id, mine.timeframe, mine.lookback) == ("mean_reversion", Timeframe.D1, 20)
    assert MeanReversion((SPY,)).lookback == 200


def test_buys_a_dip_in_an_uptrend_with_a_stop_below_the_close() -> None:
    [target] = strategy().decide(context({SPY: DIP}))

    assert target.weight == 1
    assert target.stop_price == expected_stop(DIP)
    assert target.stop_price is not None
    assert usd("100") < target.stop_price < usd("115")
    assert target.reason == "RSI(2) 6.2 in an uptrend; stop 2.5 x ATR(14) below the close"


def test_does_not_buy_without_a_dip() -> None:
    [target] = strategy().decide(context({SPY: RISING}))

    assert target == Target(SPY, Decimal(0), "RSI(2) 100.0, no dip")


def test_does_not_buy_a_dip_in_a_downtrend() -> None:
    [target] = strategy().decide(context({SPY: FALLING}))

    assert target == Target(SPY, Decimal(0), "close at or below its 20-session average")


def test_sells_the_rebound() -> None:
    rebound = [*DIP[:-1], 118.0]  # above the 5-session average of 116.6

    [target] = strategy().decide(context({SPY: rebound}, (held("105.00"),)))

    assert target == Target(SPY, Decimal(0), "close above its 5-session average")


def test_holds_with_the_stop_it_set_at_entry() -> None:
    [target] = strategy().decide(context({SPY: DIP}, (held("105.00"),)))

    assert target == Target(SPY, Decimal(1), "hold the dip until it rebounds", usd("105.00"))


def test_sells_when_the_close_is_already_through_the_stop() -> None:
    # The stop works from the session after the entry fill; this close beat it to it.
    [target] = strategy().decide(context({SPY: DIP}, (held("115.00"),)))

    assert target == Target(SPY, Decimal(0), "close at or below the stop before it could work")


def test_a_held_position_with_no_stop_gets_one_from_todays_close() -> None:
    [target] = strategy().decide(context({SPY: DIP}, (held(None),)))

    assert target.weight == 1
    assert target.stop_price == expected_stop(DIP)


def test_each_instrument_has_an_equal_share_and_only_its_own_are_traded() -> None:
    other = Instrument("IWM", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)

    targets = strategy(SPY, QQQ).decide(context({SPY: DIP, other: DIP, QQQ: RISING}))

    assert [(t.instrument, t.weight) for t in targets] == [
        (SPY, Decimal("0.5")),
        (QQQ, Decimal(0)),
    ]


PARAMETERS: dict[str, object] = {
    "instruments": [{"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"}]
}
"""A valid ``[parameters]`` table; each test changes one key."""


class TestPlugin:
    @staticmethod
    def lookup(symbol: str, exchange: str, asset_class: AssetClass) -> Instrument:
        return {"SPY": SPY, "QQQ": QQQ}[symbol]

    def test_is_built_with_the_agreed_defaults(self) -> None:
        built = PLUGINS["mean_reversion"].create("dips", PARAMETERS, self.lookup)

        assert isinstance(built, MeanReversion)
        assert built.strategy_id == "dips"
        assert built.instruments == (SPY,)
        assert (
            built.trend_sessions,
            built.rsi_sessions,
            built.entry_rsi,
            built.exit_sessions,
            built.atr_sessions,
            built.stop_atrs,
        ) == (200, 2, Decimal(10), 5, 14, Decimal("2.5"))

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            ({"stop_atrs": 2.5}, "write decimals as strings"),
            ({"stop_atrs": "0"}, "greater than 0"),
            ({"entry_rsi": "100"}, "less than 100"),
            ({"rsi_sessions": 0}, "greater than or equal to 1"),
            (
                {
                    "instruments": [
                        {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"},
                        {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"},
                    ]
                },
                "listed more than once",
            ),
        ],
    )
    def test_parameters_are_checked(self, change: dict[str, object], problem: str) -> None:
        with pytest.raises(ValidationError, match=problem):
            PLUGINS["mean_reversion"].create("dips", {**PARAMETERS, **change}, self.lookup)


def test_no_entry_when_the_stop_would_be_at_or_below_zero() -> None:
    wide = MeanReversion((SPY,), trend_sessions=20, exit_sessions=5, stop_atrs=Decimal(100))

    [target] = wide.decide(context({SPY: DIP}))

    assert target == Target(SPY, Decimal(0), "no room for a stop above zero")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"instruments": ()}, "list each instrument once, at least one"),
        ({"instruments": (SPY, SPY)}, "list each instrument once, at least one"),
        ({"atr_sessions": 0}, "sessions must be at least 1"),
        ({"entry_rsi": Decimal(0)}, "entry_rsi must be between 0 and 100"),
        ({"stop_atrs": Decimal(0)}, "stop_atrs must be above 0"),
    ],
)
def test_the_constructor_refuses_nonsense(arguments: dict[str, object], message: str) -> None:
    kwargs: dict[str, object] = {"instruments": (SPY,), **arguments}
    with pytest.raises(ValueError, match=message):
        MeanReversion(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "problem"), [("ten", "not a decimal number"), ("Infinity", "finite")]
)
def test_decimal_parameters_must_be_finite_numbers(value: str, problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        PLUGINS["mean_reversion"].create(
            "dips", {**PARAMETERS, "stop_atrs": value}, TestPlugin.lookup
        )
