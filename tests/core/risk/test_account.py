"""The account rules: the daily loss limit and the drawdown kill (ADR-0015, ADR-0035)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.support.risk import profile
from tyche.core.domain import Account, Currency, Money, RiskRule
from tyche.core.risk import AccountRules

FIRST = datetime(2008, 9, 1, 20, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


def closes(*equities: str, daily: str = "0.03", drawdown: str = "0.15") -> AccountRules:
    """Rules that have seen one close per equity, a day apart."""
    rules = AccountRules(profile(daily_loss=daily, drawdown=drawdown))
    for day, equity in enumerate(equities):
        rules.close(FIRST + timedelta(days=day), cash(equity))
    return rules


def cash(amount: str) -> Account:
    return Account.empty().deposit(usd(amount))


def at(day: int) -> datetime:
    return FIRST + timedelta(days=day)


class TestDailyLossLimit:
    def test_the_first_close_has_nothing_to_compare_with(self) -> None:
        rules = AccountRules(profile(daily_loss="0.03"))
        assert rules.close(FIRST, cash("10000")) == ()
        assert rules.daily_loss(FIRST) is None

    def test_triggers_on_a_loss_of_the_limit_or_more(self) -> None:
        rules = closes("10000")
        [found] = rules.close(at(1), cash("9700"))
        assert found.rule is RiskRule.DAILY_LOSS_LIMIT
        assert found.reference == usd("10000")
        assert found.equity == usd("9700")
        assert found.loss == Decimal("0.03")
        assert found.limit == Decimal("0.03")
        assert "no entries or additions" in found.reason
        assert rules.daily_loss(at(1)) == found

    def test_does_not_trigger_below_the_limit(self) -> None:
        rules = closes("10000")
        assert rules.close(at(1), cash("9701")) == ()

    def test_compares_with_the_previous_close_not_the_peak(self) -> None:
        # Down 2% then 2% again: 4% below the peak, but never 3% in a day.
        rules = closes("10000", "9800")
        assert rules.close(at(2), cash("9604")) == ()

    def test_lasts_for_its_own_close_only(self) -> None:
        rules = closes("10000", "9000")
        assert rules.daily_loss(at(1)) is not None
        rules.close(at(2), cash("9000"))
        assert rules.daily_loss(at(1)) is None
        assert rules.daily_loss(at(2)) is None


class TestDrawdownKill:
    def test_triggers_at_the_limit_below_the_highest_close(self) -> None:
        rules = closes("10000", "12000", "11000", "10300")
        assert rules.halt is None
        assert rules.peak(Currency.USD) == usd("12000")
        [found] = rules.close(at(4), cash("10200"))
        assert found.rule is RiskRule.DRAWDOWN_KILL
        assert found.reference == usd("12000")
        assert found.loss == Decimal("0.15")
        assert "until a manual restart" in found.reason
        assert rules.halt == found

    def test_is_a_latch_nothing_in_a_run_clears(self) -> None:
        rules = closes("10000", "8000")
        halt = rules.halt
        assert halt is not None
        assert rules.close(at(2), cash("20000")) == ()
        assert rules.close(at(3), cash("1000")) == ()
        assert rules.halt is halt

    def test_a_close_that_trips_both_reports_the_daily_loss_first(self) -> None:
        rules = closes("10000")
        found = rules.close(at(1), cash("8000"))
        assert [t.rule for t in found] == [RiskRule.DAILY_LOSS_LIMIT, RiskRule.DRAWDOWN_KILL]


def test_refuses_a_close_that_is_not_after_the_previous_one() -> None:
    rules = closes("10000")
    with pytest.raises(ValueError, match="not after"):
        rules.close(FIRST, cash("10000"))
