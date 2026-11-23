"""Minimum viable capital: the size penalty, the rule, and the round-trip arithmetic."""

from decimal import Decimal

import pytest

from tests.support.costs import US_COSTS, US_TIERED_COSTS, usd
from tyche.core.backtest import (
    CapitalError,
    SizedResult,
    is_viable,
    minimum_viable,
    round_trip_cost,
    size_penalty,
)

TOLERANCE = Decimal("0.005")
REFERENCE = Decimal("0.08")


def results(*pairs: tuple[str, str | None]) -> list[SizedResult]:
    return [SizedResult(Decimal(a), Decimal(c) if c is not None else None) for a, c in pairs]


class TestSizePenalty:
    def test_is_the_reference_minus_the_amount(self) -> None:
        assert size_penalty(Decimal("0.06"), REFERENCE) == Decimal("0.02")

    def test_is_negative_when_the_small_account_did_better(self) -> None:
        assert size_penalty(Decimal("0.09"), REFERENCE) == Decimal("-0.01")

    def test_is_unknown_without_both_figures(self) -> None:
        assert size_penalty(None, REFERENCE) is None
        assert size_penalty(Decimal("0.06"), None) is None


class TestViable:
    @pytest.mark.parametrize(
        ("cagr", "viable"),
        [
            ("0.08", True),
            ("0.075", True),  # exactly the tolerance below
            ("0.0749", False),
            ("0.085", True),  # exactly the tolerance above
            # Far better than the large account is not viable either: whole shares made
            # it a different strategy, and its lead is luck.
            ("0.0851", False),
        ],
    )
    def test_within_the_tolerance_either_way(self, cagr: str, viable: bool) -> None:
        assert is_viable(Decimal(cagr), REFERENCE, TOLERANCE) is viable

    def test_an_unmeasured_run_is_not_viable(self) -> None:
        assert not is_viable(None, REFERENCE, TOLERANCE)
        assert not is_viable(REFERENCE, None, TOLERANCE)


class TestMinimumViable:
    def test_the_smallest_amount_from_which_all_are_viable(self) -> None:
        found = results(("500", "0.02"), ("1000", "0.06"), ("2000", "0.077"), ("5000", "0.079"))

        assert minimum_viable(found, REFERENCE, TOLERANCE) == Decimal(2000)

    def test_a_lucky_amount_below_a_failing_one_does_not_count(self) -> None:
        found = results(("500", "0.079"), ("1000", "0.06"), ("2000", "0.078"))

        assert minimum_viable(found, REFERENCE, TOLERANCE) == Decimal(2000)

    def test_the_order_given_does_not_matter(self) -> None:
        found = results(("2000", "0.078"), ("500", "0.02"), ("1000", "0.079"))

        assert minimum_viable(found, REFERENCE, TOLERANCE) == Decimal(1000)

    def test_none_when_the_largest_amount_is_not_viable(self) -> None:
        found = results(("500", "0.079"), ("1000", "0.05"))

        assert minimum_viable(found, REFERENCE, TOLERANCE) is None

    def test_none_without_a_measured_reference(self) -> None:
        assert minimum_viable(results(("500", "0.08")), None, TOLERANCE) is None

    def test_an_unmeasured_amount_breaks_the_run_of_viable_ones(self) -> None:
        found = results(("500", "0.08"), ("1000", None), ("2000", "0.08"))

        assert minimum_viable(found, REFERENCE, TOLERANCE) == Decimal(2000)

    @pytest.mark.parametrize(
        ("found", "tolerance", "message"),
        [
            ([], TOLERANCE, "no amounts to test"),
            (
                results(("500", "0.08"), ("500", "0.07")),
                TOLERANCE,
                "each amount may be tested once",
            ),
            (results(("500", "0.08")), Decimal("-0.01"), "the tolerance must be zero or more"),
        ],
    )
    def test_refuses_what_cannot_be_judged(
        self, found: list[SizedResult], tolerance: Decimal, message: str
    ) -> None:
        with pytest.raises(CapitalError, match=message):
            minimum_viable(found, REFERENCE, tolerance)


class TestRoundTripCost:
    def test_a_small_position_pays_two_minimums_and_the_slippage(self) -> None:
        # USD 500 at USD 100 buys 4 shares at 100.05 with room for the commission. Each
        # order pays the USD 1.00 minimum plus a cent of fees, rounded up; the slippage
        # is 0.10 a share across both fills: 2.42 on 400.
        cost = round_trip_cost(US_COSTS, usd("500"), usd("100"))

        assert cost == Decimal("2.42") / Decimal(400)

    def test_tiered_costs_less_on_a_small_position(self) -> None:
        fixed = round_trip_cost(US_COSTS, usd("500"), usd("100"))
        tiered = round_trip_cost(US_TIERED_COSTS, usd("500"), usd("100"))

        assert fixed is not None
        assert tiered is not None
        assert tiered < fixed

    def test_falls_as_the_position_grows(self) -> None:
        small = round_trip_cost(US_COSTS, usd("200"), usd("100"))
        large = round_trip_cost(US_COSTS, usd("20000"), usd("100"))

        assert small is not None
        assert large is not None
        assert large < small

    def test_none_when_a_position_cannot_buy_one_share(self) -> None:
        assert round_trip_cost(US_COSTS, usd("100"), usd("100")) is None
