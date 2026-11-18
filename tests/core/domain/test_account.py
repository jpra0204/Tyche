"""The ledger: cash moves through settlement, positions at average cost, no shorts, no margin."""

from datetime import date
from decimal import Decimal

import pytest

from tests.support.ledger import TRADE_DAY, fill
from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    Account,
    AssetClass,
    Currency,
    Instrument,
    LedgerError,
    Money,
    Position,
    Side,
)

XIU = Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)
NEXT_DAY = date(2024, 1, 3)


def usd(amount: str) -> Money:
    return Money.of(amount, Currency.USD)


def funded(amount: str = "10000") -> Account:
    return Account.empty().deposit(usd(amount))


class TestCash:
    def test_a_deposit_is_settled_at_once(self) -> None:
        cash = funded().cash(Currency.USD)

        assert cash.settled == usd("10000")
        assert cash.unsettled == usd("0")
        assert cash.total == usd("10000")

    def test_a_currency_never_touched_is_zero(self) -> None:
        assert funded().cash(Currency.CAD).total == Money.zero(Currency.CAD)

    def test_a_deposit_must_be_positive(self) -> None:
        with pytest.raises(LedgerError, match="deposit must be positive"):
            Account.empty().deposit(usd("0"))

    def test_a_purchase_is_unsettled_until_its_settlement_date(self) -> None:
        account = funded().apply_fill(fill(Side.BUY, "10", "100", commission="1"))

        assert account.cash(Currency.USD).settled == usd("10000")
        assert account.cash(Currency.USD).unsettled == usd("-1001")
        assert account.cash(Currency.USD).total == usd("8999")

        settled = account.settle(through=NEXT_DAY)

        assert settled.cash(Currency.USD).settled == usd("8999")
        assert settled.cash(Currency.USD).pending == ()

    def test_settling_early_changes_nothing(self) -> None:
        account = funded().apply_fill(fill(Side.BUY, "10", "100"))

        assert account.settle(through=TRADE_DAY) == account

    def test_settlement_is_per_fill_date(self) -> None:
        account = (
            funded()
            .apply_fill(fill(Side.BUY, "1", "100", commission="0", settle_days=1))
            .apply_fill(fill(Side.BUY, "1", "100", commission="0", settle_days=3))
            .settle(through=NEXT_DAY)
        )

        assert account.cash(Currency.USD).settled == usd("9900")
        assert account.cash(Currency.USD).unsettled == usd("-100")

    def test_currencies_are_kept_apart(self) -> None:
        account = (
            funded()
            .deposit(Money.of("5000", Currency.CAD))
            .apply_fill(fill(Side.BUY, "10", "30", instrument=XIU))
        )

        assert account.cash(Currency.USD).total == usd("10000")
        assert account.cash(Currency.CAD).total == Money.of("4699", Currency.CAD)
        assert account.currencies == (Currency.CAD, Currency.USD)


class TestPositions:
    def test_a_purchase_opens_a_position_at_cost_including_commission(self) -> None:
        position = funded().apply_fill(fill(Side.BUY, "10", "100", commission="1")).position(SPY)

        assert position is not None
        assert position.quantity == Decimal(10)
        assert position.cost == usd("1001")
        assert position.average_cost == usd("100.1")

    def test_buying_more_averages_the_cost(self) -> None:
        account = (
            funded()
            .apply_fill(fill(Side.BUY, "10", "100", commission="0"))
            .apply_fill(fill(Side.BUY, "10", "110", commission="0"))
        )

        position = account.position(SPY)
        assert position is not None
        assert position.average_cost == usd("105")

    def test_a_partial_sale_realises_profit_at_average_cost(self) -> None:
        account = (
            funded()
            .apply_fill(fill(Side.BUY, "10", "100", commission="1"))
            .apply_fill(fill(Side.SELL, "4", "120", commission="1"))
        )

        position = account.position(SPY)
        assert position is not None
        assert position.quantity == Decimal(6)
        assert position.cost == usd("600.6")  # 6 shares at 100.10
        # Sold for 480 - 1 = 479; those 4 shares cost 400.40.
        assert account.realized_pnl(Currency.USD) == usd("78.6")

    def test_selling_everything_closes_the_position(self) -> None:
        account = (
            funded()
            .apply_fill(fill(Side.BUY, "10", "100", commission="1"))
            .apply_fill(fill(Side.SELL, "10", "90", commission="1"))
        )

        assert account.position(SPY) is None
        assert account.mark_of(SPY) is None
        assert account.positions == ()
        assert account.realized_pnl(Currency.USD) == usd("-102")

    def test_positions_are_listed_in_a_fixed_order(self) -> None:
        account = (
            funded()
            .apply_fill(fill(Side.BUY, "1", "100", instrument=SPY))
            .apply_fill(fill(Side.BUY, "1", "100", instrument=QQQ))
        )

        assert [p.instrument.symbol for p in account.positions] == ["QQQ", "SPY"]


class TestValuation:
    def test_a_purchase_marks_the_position_at_its_fill_price(self) -> None:
        account = funded().apply_fill(fill(Side.BUY, "10", "100", commission="1"))

        assert account.mark_of(SPY) == usd("100")
        assert account.market_value(Currency.USD) == usd("1000")
        assert account.equity(Currency.USD) == usd("9999")

    def test_marking_revalues_the_position(self) -> None:
        account = (
            funded().apply_fill(fill(Side.BUY, "10", "100", commission="1")).mark(SPY, usd("110"))
        )

        assert account.equity(Currency.USD) == usd("10099")

    def test_only_a_held_instrument_can_be_marked(self) -> None:
        with pytest.raises(LedgerError, match="it is not held"):
            funded().mark(SPY, usd("100"))

    def test_a_mark_must_be_a_positive_price_in_the_right_currency(self) -> None:
        account = funded().apply_fill(fill(Side.BUY, "10", "100"))

        with pytest.raises(LedgerError, match="cannot mark"):
            account.mark(SPY, Money.of("100", Currency.CAD))
        with pytest.raises(LedgerError, match="cannot mark"):
            account.mark(SPY, usd("0"))


class TestCashAccountRules:
    def test_a_sale_of_more_than_is_held_is_refused(self) -> None:
        account = funded().apply_fill(fill(Side.BUY, "10", "100"))

        with pytest.raises(LedgerError, match="only 10 held would be a short sale"):
            account.apply_fill(fill(Side.SELL, "11", "100"))

    def test_a_sale_of_something_not_held_is_refused(self) -> None:
        with pytest.raises(LedgerError, match="only 0 held would be a short sale"):
            funded().apply_fill(fill(Side.SELL, "1", "100"))

    def test_a_purchase_beyond_the_cash_is_refused(self) -> None:
        with pytest.raises(LedgerError, match=r"would leave -2\.00 USD in a cash account"):
            funded("1000").apply_fill(fill(Side.BUY, "10", "100.10", commission="1"))

    def test_a_purchase_of_exactly_the_cash_is_allowed(self) -> None:
        account = funded("1001").apply_fill(fill(Side.BUY, "10", "100", commission="1"))

        assert account.cash(Currency.USD).total == usd("0")

    def test_the_same_fill_cannot_be_applied_twice(self) -> None:
        bought = fill(Side.BUY, "1", "100", fill_id="exec-1")
        account = funded().apply_fill(bought)

        with pytest.raises(LedgerError, match="exec-1 has already been applied"):
            account.apply_fill(bought)

    def test_a_refused_operation_leaves_the_account_unchanged(self) -> None:
        before = funded("1000")

        with pytest.raises(LedgerError):
            before.apply_fill(fill(Side.BUY, "100", "100"))

        assert before == funded("1000")


class TestPositionRules:
    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            Position(SPY, Decimal(0), usd("0"))

    def test_cost_must_be_in_the_instruments_currency(self) -> None:
        with pytest.raises(ValueError, match="cost must be in its currency"):
            Position(SPY, Decimal(1), Money.of("100", Currency.CAD))


def test_market_value_counts_only_positions_in_that_currency() -> None:
    account = (
        funded()
        .deposit(Money.of("5000", Currency.CAD))
        .apply_fill(fill(Side.BUY, "10", "100", commission="0"))
        .apply_fill(fill(Side.BUY, "10", "30", commission="0", instrument=XIU))
    )

    assert account.market_value(Currency.USD) == usd("1000")
    assert account.market_value(Currency.CAD) == Money.of("300", Currency.CAD)
    assert account.equity(Currency.CAD) == Money.of("5000", Currency.CAD)


class TestDistributions:
    def test_a_distribution_is_settled_cash_and_counted_as_income(self) -> None:
        account = funded("100").receive_distribution("SPY:2024-01-03:dividend", usd("5.55"))

        assert account.cash(Currency.USD).settled == usd("105.55")
        assert account.distributions_received(Currency.USD) == usd("5.55")
        assert account.realized_pnl(Currency.USD) == usd("0")

    def test_nothing_received_reads_as_zero(self) -> None:
        assert funded().distributions_received(Currency.CAD) == Money.of("0", Currency.CAD)

    def test_the_same_payment_is_refused_twice(self) -> None:
        account = funded().receive_distribution("p-1", usd("1"))

        with pytest.raises(LedgerError, match="p-1 has already been received"):
            account.receive_distribution("p-1", usd("1"))

    def test_needs_a_payment_id(self) -> None:
        with pytest.raises(LedgerError, match="needs a payment id"):
            funded().receive_distribution(" ", usd("1"))

    @pytest.mark.parametrize("amount", ["0", "-1"])
    def test_the_amount_must_be_positive(self, amount: str) -> None:
        with pytest.raises(LedgerError, match="amount must be positive"):
            funded().receive_distribution("p-1", usd(amount))
