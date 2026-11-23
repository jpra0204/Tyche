"""Trading costs: IBKR's own published examples, the edge cases, and properties."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.support.costs import NO_FEES, TIERED, US_COSTS, US_TIERED_COSTS, usd
from tyche.core.domain import (
    Currency,
    Money,
    RegulatoryFees,
    Side,
    TieredSchedule,
    TradeCost,
    affordable_shares,
    whole_shares,
)

FIXED = US_COSTS.commission
NO_SLIPPAGE = replace(US_COSTS, slippage_bps=Decimal(0))
COMMISSION_ONLY = replace(NO_SLIPPAGE, regulatory_fees=NO_FEES)


class TestCommission:
    # IBKR Canada's published Fixed examples, read on 2026-11-17.
    @pytest.mark.parametrize(
        ("shares", "price", "expected"),
        [
            ("100", "25", "1.00"),  # 0.50 by shares, raised to the minimum
            ("1000", "25", "5.00"),  # by shares
            ("1000", "0.25", "2.50"),  # 5.00 by shares, capped at 1% of 250
            ("10", "0.20", "0.02"),  # the cap wins even below the minimum
        ],
    )
    def test_matches_ibkr_published_examples(self, shares: str, price: str, expected: str) -> None:
        assert FIXED.commission(Decimal(shares), usd(price)) == usd(expected)

    def test_a_small_order_pays_one_percent(self) -> None:
        assert FIXED.commission(Decimal(1), usd("50")) == usd("0.50")

    def test_rounds_to_the_cent(self) -> None:
        # 333 x 0.005 = 1.665: halves go to the even cent.
        assert FIXED.commission(Decimal(333), usd("50")) == usd("1.66")

    def test_refuses_a_price_in_another_currency(self) -> None:
        with pytest.raises(ValueError, match="price is in CAD"):
            FIXED.commission(Decimal(1), Money.of("10", Currency.CAD))

    @pytest.mark.parametrize("quantity", ["0", "-1", "NaN"])
    def test_refuses_a_quantity_that_is_not_positive(self, quantity: str) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            FIXED.commission(Decimal(quantity), usd("10"))

    def test_refuses_a_price_that_is_not_positive(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            FIXED.commission(Decimal(1), usd("0"))

    def test_schedule_needs_one_currency(self) -> None:
        with pytest.raises(ValueError, match="same currency"):
            replace(FIXED, minimum=Money.of("1", Currency.CAD))

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("per_share", usd("-0.001"), "per_share must be zero or more"),
            ("minimum", usd("-1"), "minimum must be zero or more"),
            ("maximum_rate", Decimal("-0.01"), "maximum_rate must be zero or more"),
            ("maximum_rate", Decimal("1.5"), "maximum_rate must be at most 1"),
        ],
    )
    def test_schedule_refuses_impossible_rates(self, field: str, value: Any, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            replace(FIXED, **{field: value})


class TestTiered:
    # Worked by hand from IBKR Canada's Tiered rates, read on 2026-11-22: commission
    # 0.0035 a share (min 0.35, max 1%), pass-through 0.000738 of the commission,
    # clearing 0.0002 a share (max 0.5%), and the assumed exchange fee of 0.0030.
    @pytest.mark.parametrize(
        ("shares", "price", "expected"),
        [
            # 0.35 minimum + fees 0.02 clearing + 0.30 exchange + 0.0003 pass-through.
            ("100", "25", "0.68"),
            # 3.50 + fees 0.20 + 3.00 + 0.0026, rounded up.
            ("1000", "25", "6.71"),
            # The 1% cap: 0.02, + fees 0.002 + 0.03 + a fraction of a cent, rounded up.
            ("10", "0.20", "0.06"),
        ],
    )
    def test_adds_third_party_fees_to_the_commission(
        self, shares: str, price: str, expected: str
    ) -> None:
        assert TIERED.commission(Decimal(shares), usd(price)) == usd(expected)

    def test_clearing_is_capped_at_half_a_percent(self) -> None:
        no_exchange = replace(TIERED, exchange_fee_per_share=usd("0"))
        # 1,000 shares at USD 0.02: clearing would be 0.20, capped at 0.10; the
        # commission is capped at 1% of 20, 0.20.
        assert no_exchange.commission(Decimal(1000), usd("0.02")) == usd("0.31")

    def test_costs_less_than_fixed_on_a_small_order(self) -> None:
        tiered = US_TIERED_COSTS.cost_of(Side.BUY, Decimal(3), usd("100")).total
        fixed = US_COSTS.cost_of(Side.BUY, Decimal(3), usd("100")).total

        assert tiered < fixed

    def test_refuses_mixed_currencies(self) -> None:
        with pytest.raises(ValueError, match="per_share and exchange_fee_per_share"):
            replace(TIERED, exchange_fee_per_share=Money.of("0.003", Currency.CAD))

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("per_share", usd("-0.01"), "tiered per_share must be zero or more"),
            ("clearing_maximum_rate", Decimal(2), "clearing_maximum_rate must be at most 1"),
            ("nyse_pass_through_rate", Decimal(-1), "nyse_pass_through_rate must be zero"),
        ],
    )
    def test_refuses_impossible_rates(self, field: str, value: Any, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            replace(TIERED, **{field: value})

    def test_is_a_pricing_plan_for_trading_costs(self) -> None:
        assert isinstance(US_TIERED_COSTS.commission, TieredSchedule)
        assert US_TIERED_COSTS.currency is Currency.USD


class TestRegulatoryFees:
    def test_a_buy_pays_only_the_audit_trail_fee_rounded_up(self) -> None:
        # 3 x 0.000003 = 0.000009, rounded up to a cent.
        assert US_COSTS.regulatory_fees.fees(Side.BUY, Decimal(3), usd("50")) == usd("0.01")

    def test_a_sale_also_pays_the_sec_fee_and_the_taf(self) -> None:
        fees = RegulatoryFees(
            sec_fee_rate=Decimal("0.0000206"),
            taf_per_share_sold=usd("0.0002"),
            cat_per_share=usd("0.000003"),
        )
        # SEC 100,000 x 0.0000206 = 2.06; TAF 1,000 x 0.0002 = 0.20; CAT 0.003.
        assert fees.fees(Side.SELL, Decimal(1000), usd("100")) == usd("2.27")
        assert fees.fees(Side.BUY, Decimal(1000), usd("100")) == usd("0.01")

    def test_zero_rates_cost_nothing(self) -> None:
        assert NO_FEES.fees(Side.SELL, Decimal(10), usd("10")) == usd("0")

    def test_fees_need_one_currency(self) -> None:
        with pytest.raises(ValueError, match="same currency"):
            replace(NO_FEES, cat_per_share=Money.of("0", Currency.CAD))

    def test_refuse_a_negative_rate(self) -> None:
        with pytest.raises(ValueError, match="sec_fee_rate must be zero or more"):
            replace(NO_FEES, sec_fee_rate=Decimal("-0.1"))


class TestTradingCosts:
    def test_cost_of_adds_commission_and_fees(self) -> None:
        cost = US_COSTS.cost_of(Side.BUY, Decimal(3), usd("50"))

        assert cost == TradeCost(commission=usd("1.00"), regulatory_fees=usd("0.01"))
        assert cost.total == usd("1.01")

    def test_slippage_moves_a_buy_up_and_a_sale_down(self) -> None:
        assert US_COSTS.fill_price(Side.BUY, usd("100")) == usd("100.05")
        assert US_COSTS.fill_price(Side.SELL, usd("100")) == usd("99.95")

    def test_no_slippage_fills_at_the_reference(self) -> None:
        assert NO_SLIPPAGE.fill_price(Side.BUY, usd("100")) == usd("100")

    def test_commission_and_fees_must_share_a_currency(self) -> None:
        cad = Money.of("0", Currency.CAD)
        with pytest.raises(ValueError, match="commission is in USD, regulatory fees in CAD"):
            replace(
                US_COSTS,
                regulatory_fees=RegulatoryFees(Decimal(0), cad, cad),
            )

    @pytest.mark.parametrize("bps", ["-1", "10001", "NaN"])
    def test_refuses_impossible_slippage(self, bps: str) -> None:
        with pytest.raises(ValueError, match="slippage_bps"):
            replace(US_COSTS, slippage_bps=Decimal(bps))

    def test_refuses_negative_settlement(self) -> None:
        with pytest.raises(ValueError, match="settlement_days must be zero or more"):
            replace(US_COSTS, settlement_days=-1)


class TestWholeShares:
    @pytest.mark.parametrize(
        ("budget", "price", "expected"),
        [
            ("150", "50", 3),
            ("149.99", "50", 2),
            ("49.99", "50", 0),
            ("0", "50", 0),
            ("-5", "50", 0),
        ],
    )
    def test_rounds_down_to_whole_shares(self, budget: str, price: str, expected: int) -> None:
        assert whole_shares(usd(budget), usd(price)) == Decimal(expected)

    def test_refuses_mixed_currencies(self) -> None:
        with pytest.raises(ValueError, match="budget is in CAD"):
            whole_shares(Money.of("100", Currency.CAD), usd("10"))

    def test_refuses_a_price_that_is_not_positive(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            whole_shares(usd("100"), usd("0"))


class TestAffordableShares:
    def test_leaves_room_for_the_commission(self) -> None:
        # Three shares at 50 fit 150 before costs, but not with the 1.00 commission.
        assert affordable_shares(usd("150"), usd("50"), COMMISSION_ONLY) == Decimal(2)
        assert affordable_shares(usd("151"), usd("50"), COMMISSION_ONLY) == Decimal(3)

    def test_includes_slippage_and_fees(self) -> None:
        # 3 x 50.025 = 150.075, plus 1.00 commission and 0.01 fees = 151.085.
        assert affordable_shares(usd("151.08"), usd("50"), US_COSTS) == Decimal(2)
        assert affordable_shares(usd("151.09"), usd("50"), US_COSTS) == Decimal(3)

    def test_nothing_when_one_share_is_out_of_reach(self) -> None:
        assert affordable_shares(usd("50"), usd("50"), COMMISSION_ONLY) == Decimal(0)


prices = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(2000), places=2)
cash_amounts = st.decimals(min_value=Decimal(0), max_value=Decimal(50_000), places=2)
quantities = st.integers(min_value=1, max_value=100_000).map(Decimal)


@given(quantity=quantities, price=prices)
def test_commission_never_exceeds_the_cap(quantity: Decimal, price: Decimal) -> None:
    value = usd(str(price)) * quantity
    commission = FIXED.commission(quantity, usd(str(price)))

    assert usd("0") <= commission
    # The cap, plus at most half a cent of rounding.
    assert commission <= value * Decimal("0.01") + usd("0.005")


@given(cash=cash_amounts, price=prices)
def test_affordable_shares_never_overspend_and_leave_no_affordable_share(
    cash: Decimal, price: Decimal
) -> None:
    available = usd(str(cash))
    reference = usd(str(price))
    shares = affordable_shares(available, reference, US_COSTS)

    def needed(n: Decimal) -> Money:
        fill = US_COSTS.fill_price(Side.BUY, reference)
        return fill * n + US_COSTS.cost_of(Side.BUY, n, fill).total

    assert shares >= 0
    assert shares == shares.to_integral_value()
    if shares > 0:
        assert needed(shares) <= available
    assert needed(shares + 1) > available


@given(price=prices, side=st.sampled_from(Side))
def test_slippage_is_always_against_the_order(price: Decimal, side: Side) -> None:
    reference = usd(str(price))
    fill = US_COSTS.fill_price(side, reference)

    if side is Side.BUY:
        assert fill > reference
    else:
        assert fill < reference
