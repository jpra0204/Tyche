"""Execution under the guardrails' money caps (ADR-0034).

The caps apply when a run is given them (paper and live; research backtests are not):
weights are sized on the account's equity or the capital cap, whichever is lower, and
each purchase is cut to fit the order cap and what is left under the capital cap.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from tests.core.pipeline.execution.test_stage import (
    RULES,
    TUE,
    WED,
    Desk,
    decided,
    ohlc,
    wants,
)
from tests.support.costs import usd
from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    Currency,
    MoneyLimits,
    OrderAdjustment,
    PlanNote,
    RiskAction,
    RiskRule,
    RiskScope,
    Side,
)
from tyche.core.events import Event, ExecutionPlanEvent, RiskEvent

D = Decimal
THU = date(2024, 1, 4)


def caps(capital: str, order: str) -> dict[Currency, MoneyLimits]:
    return {Currency.USD: MoneyLimits(usd(capital), usd(order))}


def cuts(events: list[Event]) -> list[OrderAdjustment]:
    found = [e.adjustment for e in events if isinstance(e, RiskEvent)]
    assert all(isinstance(a, OrderAdjustment) for a in found)
    return [a for a in found if isinstance(a, OrderAdjustment)]


def bought(desk: Desk, events: list[Event]) -> dict[str, Decimal]:
    return {
        order_id.split("-")[1]: quantity
        for order_id, side, quantity, _ in desk.submitted(events)
        if side is Side.BUY
    }


class TestSizingOnTheCapitalCap:
    def test_weights_are_sized_on_the_cap_when_the_account_holds_more(self) -> None:
        desk = Desk("10000", money=caps("690", "690"))
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))

        assert bought(desk, caused) == {"SPY.ARCX": D(3)}  # 0.5 x 690 / 100
        [plan] = [e for e in caused if isinstance(e, ExecutionPlanEvent)]
        assert plan.sized_on == (usd("690"),)
        assert cuts(caused) == []

    def test_an_account_below_the_cap_is_sized_on_its_own_equity(self) -> None:
        desk = Desk("500", money=caps("690", "690"))
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "0.5", None)))

        assert bought(desk, caused) == {"SPY.ARCX": D(2)}


class TestTheOrderCap:
    def test_a_purchase_over_the_order_cap_shrinks_to_the_shares_that_fit(self) -> None:
        desk = Desk("10000", money=caps("5000", "690"))
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "1", None)))

        assert bought(desk, caused) == {"SPY.ARCX": D(6)}
        [cut] = cuts(caused)
        assert (cut.rule, cut.scope, cut.action, cut.before, cut.after) == (
            RiskRule.MAX_ORDER_VALUE,
            RiskScope.ORDER,
            RiskAction.SHRINK,
            D(50),
            D(6),
        )
        assert cut.limit == usd("690")
        [line] = desk.plan(caused)
        assert (line.target, line.ordered, line.note) == (D(50), D(6), PlanNote.CAPPED)

    def test_each_cut_is_published_before_the_plan_with_the_profile(self) -> None:
        desk = Desk("10000", money=caps("5000", "690"))
        desk.trade(TUE, ohlc(TUE, "100"))

        caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", "1", None)))

        kinds = [type(e).__name__ for e in caused]
        assert kinds.index("RiskEvent") < kinds.index("ExecutionPlanEvent")
        [risk] = [e for e in caused if isinstance(e, RiskEvent)]
        assert risk.profile == "pass-through"  # the approved portfolio's, in these tests


class TestTheCapitalCap:
    def hold_spy(self, desk: Desk) -> None:
        """Buy 3 SPY at 100 (half of 690), then SPY doubles: 600 invested."""
        desk.trade(TUE, ohlc(TUE, "100"), ohlc(TUE, "30", instrument=QQQ))
        desk.decide(TUE, (decided("a", "1", SPY, QQQ),), wants(SPY, ("a", "0.5", None)))
        desk.trade(WED, ohlc(WED, "100", "100", "200"), ohlc(WED, "30", instrument=QQQ))

    def test_purchases_shrink_to_what_is_left_under_the_cap(self) -> None:
        desk = Desk("10000", money=caps("690", "690"))
        self.hold_spy(desk)

        # SPY is kept (not decided on); QQQ wants half of 690: 11 shares, 330.
        caused = desk.decide(WED, (decided("a", "1", QQQ),), wants(QQQ, ("a", "0.5", None)))

        assert bought(desk, caused) == {"QQQ.XNAS": D(3)}  # 690 - 600 = 90, at 30
        [cut] = cuts(caused)
        assert (cut.rule, cut.action, cut.before, cut.after) == (
            RiskRule.MAX_TOTAL_CAPITAL,
            RiskAction.SHRINK,
            D(11),
            D(3),
        )

    def test_a_purchase_not_one_share_of_which_fits_is_blocked(self) -> None:
        desk = Desk("10000", money=caps("620", "620"))
        self.hold_spy(desk)

        caused = desk.decide(WED, (decided("a", "1", QQQ),), wants(QQQ, ("a", "0.5", None)))

        assert bought(desk, caused) == {}
        [cut] = cuts(caused)
        assert (cut.action, cut.after) == (RiskAction.BLOCK, D(0))
        [line] = [line for line in desk.plan(caused) if line.instrument == QQQ]
        assert line.note is PlanNote.CAPPED

    def test_sales_are_never_cut_and_free_room_for_purchases(self) -> None:
        desk = Desk("10000", money=caps("690", "690"))
        self.hold_spy(desk)

        # Sell all SPY (600 at the close) and buy QQQ with the room it frees.
        caused = desk.decide(WED, (decided("a", "1", SPY, QQQ),), wants(QQQ, ("a", "0.5", None)))

        sells = [q for _, side, q, _ in desk.submitted(caused) if side is Side.SELL]
        assert sells == [D(3)]
        assert bought(desk, caused) == {"QQQ.XNAS": D(11)}
        assert cuts(caused) == []


BUFFERED = replace(RULES, price_buffer=D("0.02"))


@given(
    cash=st.integers(100, 50_000),
    capital=st.integers(50, 20_000),
    order_share=st.decimals(D("0.05"), D(1), places=2),
    price=st.decimals(D(5), D(800), places=2),
    weight=st.decimals(D("0.01"), D(1), places=2),
)
def test_no_purchase_ever_breaks_a_money_cap(
    cash: int, capital: int, order_share: Decimal, price: Decimal, weight: Decimal
) -> None:
    order = max((capital * order_share).quantize(D("0.01")), D("0.01"))
    desk = Desk(str(cash), rules=BUFFERED, money=caps(str(capital), str(order)))
    desk.trade(TUE, ohlc(TUE, str(price)))

    caused = desk.decide(TUE, (decided("a", "1", SPY),), wants(SPY, ("a", str(weight), None)))

    reference = price * D("1.02")  # the last close plus the price buffer
    for quantity in bought(desk, caused).values():
        assert quantity * reference <= order
        assert quantity * reference <= capital
    [plan] = [e for e in caused if isinstance(e, ExecutionPlanEvent)]
    assert plan.sized_on == (usd(str(min(cash, capital))),)
