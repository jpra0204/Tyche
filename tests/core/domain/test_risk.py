"""``RiskAdjustment``: one change the risk gate made, and why (ADR-0033)."""

from decimal import Decimal
from typing import Any

import pytest

from tests.support.costs import usd
from tests.support.market import SPY
from tyche.core.domain import (
    Currency,
    Money,
    MoneyLimits,
    OrderAdjustment,
    RiskAction,
    RiskAdjustment,
    RiskRule,
    RiskScope,
)


def adjustment(
    before: str = "0.5", after: str = "0.2", action: RiskAction = RiskAction.SHRINK
) -> RiskAdjustment:
    return RiskAdjustment(
        RiskRule.MAX_POSITION_SIZE,
        RiskScope.ACCOUNT,
        action,
        "a",
        SPY,
        Decimal(before),
        Decimal(after),
        Decimal("0.2"),
        "too big",
    )


def test_a_shrink_lowers_a_weight() -> None:
    assert adjustment().after == Decimal("0.2")


def test_a_block_approves_nothing() -> None:
    assert adjustment(after="0", action=RiskAction.BLOCK).after == 0


@pytest.mark.parametrize(
    ("before", "after", "action", "message"),
    [
        ("0.2", "0.2", RiskAction.SHRINK, "only lowers"),
        ("0.2", "0.3", RiskAction.SHRINK, "only lowers"),
        ("0.5", "0", RiskAction.SHRINK, "only a block"),
        ("0.5", "0.2", RiskAction.BLOCK, "only a block"),
        ("0.5", "-0.1", RiskAction.SHRINK, "at least 0"),
    ],
)
def test_refuses_what_is_not_a_cut(
    before: str, after: str, action: RiskAction, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        adjustment(before, after, action)


def test_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="needs a reason"):
        RiskAdjustment(
            RiskRule.MAX_POSITION_SIZE,
            RiskScope.ACCOUNT,
            RiskAction.SHRINK,
            "a",
            SPY,
            Decimal("0.5"),
            Decimal("0.2"),
            Decimal("0.2"),
            " ",
        )


def test_an_order_rule_is_not_a_risk_adjustment() -> None:
    with pytest.raises(ValueError, match="recorded as an OrderAdjustment"):
        RiskAdjustment(
            RiskRule.MAX_ORDER_VALUE,
            RiskScope.ACCOUNT,
            RiskAction.SHRINK,
            "a",
            SPY,
            Decimal("0.5"),
            Decimal("0.2"),
            Decimal("0.2"),
            "too big",
        )


class TestMoneyLimits:
    def test_sizes_on_the_lower_of_equity_and_the_capital_cap(self) -> None:
        limits = MoneyLimits(usd("690"), usd("690"))
        assert limits.trading_equity(usd("3000")) == usd("690")
        assert limits.trading_equity(usd("500")) == usd("500")

    @pytest.mark.parametrize(
        ("capital", "order", "message"),
        [
            (usd("690"), Money.of("690", Currency.CAD), "in USD, the order cap in CAD"),
            (usd("0"), usd("0"), "above 0"),
            (usd("300"), usd("690"), "above the capital cap"),
        ],
    )
    def test_refuses_caps_that_do_not_fit_together(
        self, capital: Money, order: Money, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            MoneyLimits(capital, order)


def order_cut(
    before: str = "50",
    after: str = "6",
    action: RiskAction = RiskAction.SHRINK,
    rule: RiskRule = RiskRule.MAX_ORDER_VALUE,
) -> OrderAdjustment:
    return OrderAdjustment(
        rule, action, SPY, Decimal(before), Decimal(after), usd("690"), "over the cap"
    )


class TestOrderAdjustment:
    def test_is_an_order_scoped_cut_in_shares(self) -> None:
        cut = order_cut()
        assert (cut.scope, cut.before, cut.after) == (RiskScope.ORDER, Decimal(50), Decimal(6))

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"rule": RiskRule.MAX_POSITION_SIZE}, "not an order rule"),
            ({"after": "6.5"}, "whole shares"),
            ({"after": "50"}, "only lowers"),
            ({"after": "0"}, "only a block"),
            ({"action": RiskAction.BLOCK}, "only a block"),
        ],
    )
    def test_refuses_what_is_not_a_cut_of_a_purchase(
        self, changes: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            order_cut(**changes)

    def test_its_limit_is_in_the_instruments_currency(self) -> None:
        with pytest.raises(ValueError, match="positive USD amount"):
            OrderAdjustment(
                RiskRule.MAX_ORDER_VALUE,
                RiskAction.SHRINK,
                SPY,
                Decimal(50),
                Decimal(6),
                Money.of("690", Currency.CAD),
                "over the cap",
            )
