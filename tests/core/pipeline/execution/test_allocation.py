"""The allocation rules: pro-rata splits in whole shares, and purchases fitted to cash or caps."""

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.support.costs import NO_FEES, US_COSTS, usd
from tests.support.market import QQQ, SPY
from tyche.core.domain import Instrument
from tyche.core.pipeline.execution.allocation import (
    cap_order,
    fit_to_cash,
    fit_to_value,
    purchase_cost,
    split_pro_rata,
)

D = Decimal
PLAIN = replace(US_COSTS, slippage_bps=D(0), regulatory_fees=NO_FEES)


class TestSplitProRata:
    def test_splits_in_proportion_to_each_need(self) -> None:
        assert split_pro_rata(D(6), {"a": D(8), "b": D(4)}) == {"a": D(4), "b": D(2)}

    def test_leftover_shares_go_to_the_largest_remainders(self) -> None:
        # Exact shares 2.5, 1.5 and 1: the two halves are tied, so "a" gets the spare one.
        assert split_pro_rata(D(5), {"a": D(5), "b": D(3), "c": D(2)}) == {
            "a": D(3),
            "b": D(1),
            "c": D(1),
        }

    def test_ties_go_to_the_earlier_strategy_id(self) -> None:
        assert split_pro_rata(D(1), {"b": D(1), "a": D(1)}) == {"a": D(1), "b": D(0)}

    def test_zero_gives_nothing_to_anyone(self) -> None:
        assert split_pro_rata(D(0), {"a": D(3)}) == {"a": D(0)}

    def test_refuses_more_than_is_owed_fractions_and_empty_needs(self) -> None:
        with pytest.raises(ValueError, match="cannot split 4"):
            split_pro_rata(D(4), {"a": D(3)})
        with pytest.raises(ValueError, match="whole number"):
            split_pro_rata(D("1.5"), {"a": D(3)})
        with pytest.raises(ValueError, match="positive"):
            split_pro_rata(D(0), {"a": D(0)})

    @given(
        needs=st.dictionaries(
            st.sampled_from(["a", "b", "c", "d", "e"]),
            st.integers(min_value=1, max_value=10_000),
            min_size=1,
        ),
        fraction=st.fractions(min_value=0, max_value=1),
    )
    def test_gives_out_exactly_the_total_and_never_more_than_a_need(
        self, needs: dict[str, int], fraction: object
    ) -> None:
        owed = {k: D(v) for k, v in needs.items()}
        total = D(int(sum(needs.values()) * fraction))  # type: ignore[operator]

        given_out = split_pro_rata(total, owed)

        assert sum(given_out.values()) == total
        assert all(0 <= given_out[k] <= owed[k] for k in owed)


class TestFitToCash:
    def test_purchases_that_fit_are_unchanged(self) -> None:
        wanted = {SPY: D(5), QQQ: D(4)}

        assert fit_to_cash(wanted, {SPY: usd("100"), QQQ: usd("100")}, PLAIN, usd("902")) == wanted

    def test_purchases_shrink_in_proportion_until_they_fit(self) -> None:
        # 10 + 10 shares at 100 need 2,002 with two minimum commissions. Scaled by
        # 1,000 / 2,002 and rounded down, that is 4 + 4: rounding down can leave cash over.
        references = {SPY: usd("100"), QQQ: usd("100")}
        plan = fit_to_cash({SPY: D(10), QQQ: D(10)}, references, PLAIN, usd("1000"))

        assert plan == {SPY: D(4), QQQ: D(4)}
        assert sum(
            (purchase_cost(q, usd("100"), PLAIN) for q in plan.values()), start=usd("0")
        ) <= usd("1000")

    def test_costs_that_do_not_scale_are_cut_from_the_largest(self) -> None:
        plan = fit_to_cash({SPY: D(10)}, {SPY: usd("100")}, PLAIN, usd("1000"))

        assert plan == {SPY: D(9)}  # 9 shares and the 1.00 minimum: 901

    def test_when_scaling_is_not_enough_one_share_at_a_time_is_cut(self) -> None:
        # 900.90 is exactly 0.9 of 1,001: scaled, 9 shares, which need 901 with the minimum.
        assert fit_to_cash({SPY: D(10)}, {SPY: usd("100")}, PLAIN, usd("900.90")) == {SPY: D(8)}

    def test_no_cash_buys_nothing(self) -> None:
        assert fit_to_cash({SPY: D(1)}, {SPY: usd("100")}, PLAIN, usd("0")) == {SPY: D(0)}

    def test_slippage_and_fees_are_part_of_the_cost(self) -> None:
        # With 5 bp of slippage and the fees, 10 shares at 100 need a little over 1,001.
        assert fit_to_cash({SPY: D(10)}, {SPY: usd("100")}, US_COSTS, usd("1001")) == {SPY: D(9)}


class TestCapOrder:
    def test_keeps_a_purchase_within_the_cap(self) -> None:
        assert cap_order(D(3), usd("100"), usd("350")) == D(3)

    def test_cuts_a_purchase_to_the_whole_shares_within_the_cap(self) -> None:
        assert cap_order(D(10), usd("100"), usd("350")) == D(3)

    def test_a_share_dearer_than_the_cap_buys_nothing(self) -> None:
        assert cap_order(D(1), usd("704"), usd("690")) == D(0)

    def test_needs_whole_shares_and_a_price(self) -> None:
        with pytest.raises(ValueError, match="whole number"):
            cap_order(D("1.5"), usd("100"), usd("350"))
        with pytest.raises(ValueError, match="positive reference"):
            cap_order(D(1), usd("0"), usd("350"))


REFS = {SPY: usd("100"), QQQ: usd("50")}


class TestFitToValue:
    def test_purchases_within_the_room_are_unchanged(self) -> None:
        assert fit_to_value({SPY: D(2), QQQ: D(2)}, REFS, usd("300")) == {
            SPY: D(2),
            QQQ: D(2),
        }

    def test_purchases_shrink_in_proportion_to_the_room(self) -> None:
        # Worth 1,000; room for 500: half of each.
        assert fit_to_value({SPY: D(6), QQQ: D(8)}, REFS, usd("500")) == {
            SPY: D(3),
            QQQ: D(4),
        }

    def test_no_room_buys_nothing(self) -> None:
        assert fit_to_value({SPY: D(2)}, REFS, usd("-50")) == {SPY: D(0)}

    @given(
        spy=st.integers(0, 50),
        qqq=st.integers(0, 50),
        room=st.decimals(D(-100), D(10000), places=2),
    )
    def test_never_exceeds_the_room_nor_buys_more_than_wanted(
        self, spy: int, qqq: int, room: Decimal
    ) -> None:
        wanted = {SPY: D(spy), QQQ: D(qqq)}
        fitted = fit_to_value(wanted, REFS, usd(str(room)))

        def value(plan: dict[Instrument, Decimal]) -> Decimal:
            return sum((REFS[i].amount * q for i, q in plan.items()), start=D(0))

        assert value(fitted) <= max(room, D(0))
        assert all(0 <= fitted[i] <= wanted[i] for i in wanted)
        if value(wanted) <= room:
            assert fitted == wanted
