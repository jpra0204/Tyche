"""The signal types refuse values a strategy should never be able to express."""

from datetime import date
from decimal import Decimal

import pytest

from tests.support.market import SPY
from tyche.core.domain import (
    Currency,
    Money,
    StrategyFailure,
    StrategyPosition,
    Target,
    WarmingUp,
    require_strategy_id,
)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


class TestTarget:
    def test_holds_a_weight_a_reason_and_an_optional_stop(self) -> None:
        target = Target(SPY, Decimal("0.5"), "trend is up", usd("400"))

        assert target.weight == Decimal("0.5")
        assert target.stop_price == usd("400")

    @pytest.mark.parametrize("weight", ["-0.01", "1.01", "NaN", "Infinity"])
    def test_weight_must_be_between_zero_and_one(self, weight: str) -> None:
        with pytest.raises(ValueError, match="weight"):
            Target(SPY, Decimal(weight), "x")

    def test_zero_and_one_are_allowed(self) -> None:
        assert Target(SPY, Decimal(0), "exit").weight == 0
        assert Target(SPY, Decimal(1), "all in").weight == 1

    def test_a_float_weight_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Decimal"):
            Target(SPY, 0.5, "x")  # type: ignore[arg-type]

    def test_needs_a_reason(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            Target(SPY, Decimal(1), "  ")

    def test_stop_must_be_positive_and_in_the_instruments_currency(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Target(SPY, Decimal(1), "x", usd("0"))
        with pytest.raises(ValueError, match="CAD"):
            Target(SPY, Decimal(1), "x", Money.of("400", Currency.CAD))


class TestStrategyPosition:
    def test_holds_entry_and_stop(self) -> None:
        position = StrategyPosition(SPY, Decimal(3), date(2024, 3, 1), usd("412.10"), usd("395"))

        assert position.entry_date == date(2024, 3, 1)
        assert position.stop_price == usd("395")

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="quantity"):
            StrategyPosition(SPY, Decimal(0), date(2024, 3, 1), usd("412"))

    def test_entry_price_must_be_positive_and_in_the_instruments_currency(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            StrategyPosition(SPY, Decimal(1), date(2024, 3, 1), usd("0"))
        with pytest.raises(ValueError, match="CAD"):
            StrategyPosition(SPY, Decimal(1), date(2024, 3, 1), Money.of("412", Currency.CAD))


class TestWarmingUp:
    def test_describes_how_far_along_the_window_is(self) -> None:
        assert str(WarmingUp(SPY, 30, 200)) == "SPY@ARCX warming up: 30 of 200 bars"

    def test_a_full_window_is_not_warming_up(self) -> None:
        with pytest.raises(ValueError, match="not warming up"):
            WarmingUp(SPY, 200, 200)


def test_a_failure_says_which_strategy_and_why() -> None:
    assert str(StrategyFailure("trend", "ValueError: boom")) == "trend: ValueError: boom"


@pytest.mark.parametrize("strategy_id", ["buy_and_hold", "trend-2", "a"])
def test_valid_strategy_ids(strategy_id: str) -> None:
    require_strategy_id(strategy_id)


@pytest.mark.parametrize("strategy_id", ["", "Trend", "2trend", "../x", "trend rotation"])
def test_invalid_strategy_ids(strategy_id: str) -> None:
    with pytest.raises(ValueError, match="invalid strategy id"):
        require_strategy_id(strategy_id)
