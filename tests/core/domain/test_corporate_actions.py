"""Dividends and splits: validated on creation, like every value object."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from tests.support.market import QQQ, SPY, dividend, split
from tyche.core.domain import CashDistribution, Currency, DistributionKind, Money, Split


class TestCashDistribution:
    def test_holds_its_fields(self) -> None:
        paid = dividend(date(2024, 3, 15), "1.595")

        assert paid.instrument == SPY
        assert paid.amount_per_share == Money.of("1.595", Currency.USD)
        assert paid.kind is DistributionKind.DIVIDEND
        assert str(paid) == "SPY@ARCX dividend 1.595 USD ex 2024-03-15"

    def test_amount_is_exact(self) -> None:
        assert dividend(date(2024, 3, 15), "0.123456789").amount_per_share.amount == Decimal(
            "0.123456789"
        )

    @pytest.mark.parametrize("amount", ["0", "-1.5"])
    def test_amount_must_be_positive(self, amount: str) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            dividend(date(2024, 3, 15), amount)

    def test_must_be_paid_in_the_instruments_currency(self) -> None:
        with pytest.raises(ValueError, match="paid in CAD, but SPY@ARCX trades in USD"):
            CashDistribution(
                SPY, date(2024, 3, 15), Money.of("1", Currency.CAD), DistributionKind.DIVIDEND
            )


class TestSplit:
    def test_forward_and_reverse_splits(self) -> None:
        assert split(date(2024, 6, 10), "10").ratio == Decimal(10)
        assert split(date(2024, 6, 10), "0.1").ratio == Decimal("0.1")
        assert (
            str(split(date(2024, 6, 10), "10", instrument=QQQ))
            == "QQQ@XNAS split 10-for-1 ex 2024-06-10"
        )

    @pytest.mark.parametrize("ratio", ["0", "-2", "1", "NaN", "Infinity"])
    def test_ratio_must_be_a_real_change(self, ratio: str) -> None:
        with pytest.raises(ValueError, match="ratio must be positive and not 1"):
            split(date(2024, 6, 10), ratio)

    def test_ratio_must_be_exact(self) -> None:
        not_a_decimal: Any = 10.0
        with pytest.raises(TypeError, match="must be a Decimal"):
            Split(SPY, date(2024, 6, 10), not_a_decimal)
