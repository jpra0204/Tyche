"""Portfolio types: budgets, sleeves and contributions refuse what cannot be traded."""

from decimal import Decimal

import pytest

from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    Contribution,
    Currency,
    InstrumentTarget,
    Money,
    Sleeve,
    SleeveStatus,
    require_budgets,
)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


class TestBudgets:
    def test_budgets_may_leave_cash(self) -> None:
        require_budgets({"a": Decimal("0.6"), "b": Decimal("0.3")})

    @pytest.mark.parametrize(
        ("budgets", "message"),
        [
            ({}, "at least one"),
            ({"a": Decimal("0.6"), "b": Decimal("0.5")}, "add up to 1.1"),
            ({"a": Decimal(0)}, "above 0"),
            ({"a": Decimal("1.01")}, "at most 1"),
            ({"a": Decimal("NaN")}, "finite"),
            ({"A": Decimal("0.5")}, "invalid strategy id"),
        ],
    )
    def test_invalid_budgets(self, budgets: dict[str, Decimal], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            require_budgets(budgets)


class TestSleeve:
    def test_a_decided_sleeve_says_what_it_decided_on(self) -> None:
        sleeve = Sleeve("a", Decimal("0.5"), SleeveStatus.DECIDED, (SPY, QQQ), "1")

        assert sleeve.decided_on == (SPY, QQQ)

    def test_a_decided_sleeve_needs_a_version_and_no_error(self) -> None:
        with pytest.raises(ValueError, match="version and no error"):
            Sleeve("a", Decimal("0.5"), SleeveStatus.DECIDED, (SPY,))
        with pytest.raises(ValueError, match="version and no error"):
            Sleeve("a", Decimal("0.5"), SleeveStatus.DECIDED, (SPY,), "1", "boom")

    def test_a_failed_sleeve_has_an_error_and_decided_on_nothing(self) -> None:
        Sleeve("a", Decimal("0.5"), SleeveStatus.FAILED, error="boom")

        with pytest.raises(ValueError, match="failed sleeve"):
            Sleeve("a", Decimal("0.5"), SleeveStatus.FAILED, (SPY,), error="boom")
        with pytest.raises(ValueError, match="failed sleeve"):
            Sleeve("a", Decimal("0.5"), SleeveStatus.FAILED)

    def test_an_instrument_cannot_be_repeated(self) -> None:
        with pytest.raises(ValueError, match="repeated"):
            Sleeve("a", Decimal("0.5"), SleeveStatus.DECIDED, (SPY, SPY), "1")


class TestInstrumentTarget:
    def test_its_weight_is_the_sum_of_its_contributions_each_with_its_own_stop(self) -> None:
        target = InstrumentTarget(
            SPY,
            (
                Contribution("a", Decimal("0.3"), "trend", usd("95")),
                Contribution("b", Decimal("0.2"), "hold"),
            ),
        )

        assert target.weight == Decimal("0.5")
        contribution = target.contribution_of("a")
        assert contribution is not None
        assert contribution.stop_price == usd("95")
        assert target.contribution_of("c") is None

    def test_contributions_are_one_per_strategy_by_id(self) -> None:
        a, b = Contribution("a", Decimal("0.1"), "x"), Contribution("b", Decimal("0.1"), "y")

        with pytest.raises(ValueError, match="one per strategy"):
            InstrumentTarget(SPY, (b, a))
        with pytest.raises(ValueError, match="one per strategy"):
            InstrumentTarget(SPY, (a, a))
        with pytest.raises(ValueError, match="at least one"):
            InstrumentTarget(SPY, ())

    def test_a_stop_must_be_in_the_instruments_currency(self) -> None:
        cad = Contribution("a", Decimal("0.1"), "x", Money.of("95", Currency.CAD))

        with pytest.raises(ValueError, match="CAD"):
            InstrumentTarget(SPY, (cad,))

    def test_cannot_exceed_the_whole_account(self) -> None:
        with pytest.raises(ValueError, match="more than 1"):
            InstrumentTarget(
                SPY,
                (Contribution("a", Decimal("0.6"), "x"), Contribution("b", Decimal("0.6"), "y")),
            )


class TestContribution:
    @pytest.mark.parametrize("weight", ["-0.1", "1.1", "NaN"])
    def test_weight_must_be_a_fraction(self, weight: str) -> None:
        with pytest.raises(ValueError, match="weight"):
            Contribution("a", Decimal(weight), "x")

    def test_a_stop_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Contribution("a", Decimal("0.5"), "x", usd("0"))
