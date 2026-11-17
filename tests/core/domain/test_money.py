"""Money is exact, immutable and never mixes currencies."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest

from tyche.core.domain import Currency, CurrencyMismatchError, Money

USD = Currency.USD
CAD = Currency.CAD


def usd(amount: str) -> Money:
    return Money.of(amount, USD)


def cad(amount: str) -> Money:
    return Money.of(amount, CAD)


class TestConstruction:
    def test_of_accepts_string_int_and_decimal(self) -> None:
        assert Money.of("12.34", USD).amount == Decimal("12.34")
        assert Money.of(12, USD).amount == Decimal(12)
        assert Money.of(Decimal("0.005"), USD).amount == Decimal("0.005")

    def test_zero(self) -> None:
        assert Money.zero(CAD) == cad("0")
        assert Money.zero(CAD).is_zero

    @pytest.mark.parametrize("bad", [1.1, True])
    def test_of_rejects_float_and_bool(self, bad: Any) -> None:
        with pytest.raises(TypeError, match=r"does not accept"):
            Money.of(bad, USD)

    def test_of_rejects_text_that_is_not_a_number(self) -> None:
        with pytest.raises(ValueError, match="not a valid decimal amount"):
            Money.of("twelve", USD)

    def test_constructor_rejects_a_float_that_slipped_past_the_type_checker(self) -> None:
        not_a_decimal: Any = 0.1
        with pytest.raises(TypeError, match="must be a Decimal, got float"):
            Money(not_a_decimal, USD)

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
    def test_rejects_non_finite_amounts(self, bad: str) -> None:
        with pytest.raises(ValueError, match="must be finite"):
            Money.of(bad, USD)

    def test_is_immutable(self) -> None:
        money: Any = usd("1")
        with pytest.raises(FrozenInstanceError):
            money.amount = Decimal(2)


class TestExactness:
    def test_the_sum_that_floats_get_wrong(self) -> None:
        assert 0.1 + 0.2 != 0.3  # the reason this class exists
        assert usd("0.10") + usd("0.20") == usd("0.30")

    def test_many_small_amounts_do_not_drift(self) -> None:
        total = sum((usd("0.01") for _ in range(10_000)), Money.zero(USD))
        assert total == usd("100")

    def test_arithmetic_does_not_round(self) -> None:
        assert usd("10") / 4 == usd("2.5")
        assert usd("1.005") * 3 == usd("3.015")


class TestEqualityAndHashing:
    def test_equal_amounts_with_different_precision_are_equal(self) -> None:
        assert usd("1.5") == usd("1.50")
        assert hash(usd("1.5")) == hash(usd("1.50"))

    def test_same_amount_in_another_currency_is_not_equal(self) -> None:
        assert usd("1") != cad("1")

    def test_usable_as_a_dictionary_key(self) -> None:
        assert {usd("1.5"): "a"}[usd("1.50")] == "a"


class TestArithmetic:
    def test_add_and_subtract(self) -> None:
        assert usd("5") + usd("2.50") == usd("7.50")
        assert usd("5") - usd("7.50") == usd("-2.50")

    def test_negate_and_absolute_value(self) -> None:
        assert -usd("3") == usd("-3")
        assert abs(usd("-3")) == usd("3")

    def test_multiply_by_int_or_decimal_from_either_side(self) -> None:
        assert usd("2.50") * 3 == usd("7.50")
        assert 3 * usd("2.50") == usd("7.50")
        assert usd("200") * Decimal("0.01") == usd("2")

    def test_divide_by_a_number_gives_money(self) -> None:
        assert usd("9") / 3 == usd("3")
        assert usd("9") / Decimal("0.5") == usd("18")

    def test_divide_by_money_gives_a_plain_ratio(self) -> None:
        weight = usd("200") / usd("1000")
        assert weight == Decimal("0.2")
        assert isinstance(weight, Decimal)

    def test_divide_by_zero_fails(self) -> None:
        with pytest.raises(ZeroDivisionError):
            usd("1") / 0
        with pytest.raises(ZeroDivisionError):
            usd("1") / Money.zero(USD)

    def test_sign_properties(self) -> None:
        assert usd("1").is_positive
        assert not usd("1").is_negative
        assert usd("-1").is_negative
        assert not usd("-1").is_positive
        assert not Money.zero(USD).is_positive
        assert not Money.zero(USD).is_negative
        assert not usd("1").is_zero

    def test_str(self) -> None:
        assert str(usd("12.50")) == "12.50 USD"


class TestNoFloatsAllowed:
    """A float anywhere in money arithmetic is a TypeError, not a silent conversion."""

    def test_multiplying_by_float_fails(self) -> None:
        factor: Any = 1.1
        with pytest.raises(TypeError):
            usd("1") * factor
        with pytest.raises(TypeError):
            factor * usd("1")

    def test_dividing_by_float_fails(self) -> None:
        divisor: Any = 2.0
        with pytest.raises(TypeError):
            usd("1") / divisor

    def test_multiplying_by_bool_fails(self) -> None:
        flag: Any = True
        with pytest.raises(TypeError):
            usd("1") * flag

    def test_adding_a_bare_number_fails(self) -> None:
        number: Any = 1
        with pytest.raises(TypeError):
            usd("1") + number
        with pytest.raises(TypeError):
            usd("1") - number

    def test_comparing_with_a_bare_number_fails(self) -> None:
        number: Any = 1
        with pytest.raises(TypeError):
            _ = usd("1") < number
        with pytest.raises(TypeError):
            _ = usd("1") <= number
        with pytest.raises(TypeError):
            _ = usd("1") > number
        with pytest.raises(TypeError):
            _ = usd("1") >= number


class TestCurrenciesNeverMix:
    def test_add_and_subtract(self) -> None:
        with pytest.raises(CurrencyMismatchError, match="cannot combine USD with CAD"):
            usd("1") + cad("1")
        with pytest.raises(CurrencyMismatchError):
            usd("1") - cad("1")

    def test_ratio(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            usd("1") / cad("1")

    def test_ordering(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            _ = usd("1") < cad("2")
        with pytest.raises(CurrencyMismatchError):
            _ = usd("1") <= cad("2")
        with pytest.raises(CurrencyMismatchError):
            _ = usd("1") > cad("2")
        with pytest.raises(CurrencyMismatchError):
            _ = usd("1") >= cad("2")

    def test_the_error_names_both_currencies(self) -> None:
        with pytest.raises(CurrencyMismatchError) as caught:
            usd("1") + cad("1")
        assert caught.value.left is USD
        assert caught.value.right is CAD

    def test_summing_mixed_currencies_fails(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            sum([usd("1"), cad("1")], Money.zero(USD))


class TestOrdering:
    def test_same_currency_orders_by_amount(self) -> None:
        assert usd("1") < usd("2")
        assert usd("2") <= usd("2")
        assert usd("3") > usd("2")
        assert usd("2") >= usd("2")
        assert not usd("2") < usd("2")

    def test_sorting_and_max(self) -> None:
        amounts = [usd("3"), usd("-1"), usd("2")]
        assert sorted(amounts) == [usd("-1"), usd("2"), usd("3")]
        assert max(amounts) == usd("3")


class TestRounding:
    def test_rounds_half_to_even(self) -> None:
        assert usd("0.125").round_to(2) == usd("0.12")
        assert usd("0.135").round_to(2) == usd("0.14")
        assert usd("-0.125").round_to(2) == usd("-0.12")

    def test_rounds_to_whole_units(self) -> None:
        assert usd("2.5").round_to(0) == usd("2")

    def test_keeps_the_currency(self) -> None:
        assert cad("1.239").round_to(2) == cad("1.24")

    def test_places_cannot_be_negative(self) -> None:
        with pytest.raises(ValueError, match="zero or more"):
            usd("1").round_to(-1)
