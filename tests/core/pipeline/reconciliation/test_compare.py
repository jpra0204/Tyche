"""The comparison of a checkpoint with the broker's record (ADR-0044).

The checkpoint is ``tests.support.reconciliation.agreeing``: see there.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.support.checkpoints import market_order
from tests.support.costs import usd
from tests.support.ledger import order
from tests.support.market import QQQ, SPY
from tests.support.reconciliation import AT, BUY, RULES, STOP, USD, agreeing, broker_record
from tyche.core.domain import (
    Account,
    CashOutcome,
    Currency,
    DifferenceKind,
    EndedOrder,
    ExecutionState,
    InferredFill,
    Money,
    OrderState,
    OrderType,
    OwedShares,
    PendingCash,
    ReconciliationState,
    ReconciliationStatus,
    Side,
    WorkingOrder,
)
from tyche.core.pipeline.reconciliation import reconcile

tyche = agreeing


def kinds(found: object) -> list[DifferenceKind]:
    return [d.kind for d in found.differences]  # type: ignore[attr-defined]


class TestAgreement:
    def test_the_same_records_match(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine), RULES, USD, AT)

        assert found.status is ReconciliationStatus.MATCH
        assert (found.differences, found.inferred, found.ended) == ((), (), ())
        (cash,) = found.cash
        assert cash.outcome is CashOutcome.MATCH
        assert cash.tyche == usd("5299")

    def test_cash_is_compared_as_a_total_not_by_settlement_date(self) -> None:
        mine = tyche()

        # The broker has settled the purchase already: same total, different schedule.
        found = reconcile(mine, broker_record(mine, cash=usd("5299")), RULES, USD, AT)

        assert found.status is ReconciliationStatus.MATCH

    def test_a_currency_tyche_does_not_trade_is_not_compared(self) -> None:
        mine = tyche()
        theirs = broker_record(mine)
        cad = Account.reported(
            settled=(*(theirs.account.cash(c).settled for c in USD), Money.of("50", Currency.CAD)),
            pending=theirs.account.cash(Currency.USD).pending,
            positions=theirs.account.positions,
            marks={p.instrument: usd("475") for p in theirs.account.positions},
        )

        found = reconcile(mine, replace(theirs, account=cad), RULES, USD, AT)

        assert found.status is ReconciliationStatus.MATCH
        assert [c.currency for c in found.cash] == [Currency.USD]


class TestPositions:
    def test_a_difference_nothing_explains_halts(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, shares={SPY: "12"}), RULES, USD, AT)

        assert found.status is ReconciliationStatus.MISMATCH
        assert kinds(found) == [DifferenceKind.POSITION]
        assert found.differences[0].detail == "Tyche holds 10, the broker 12"

    def test_an_instrument_only_the_broker_holds_halts(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, shares={QQQ: "1"}), RULES, USD, AT)

        assert kinds(found) == [DifferenceKind.POSITION]
        assert found.differences[0].subject == str(QQQ)


class TestOrders:
    def test_an_order_tyche_does_not_expect_halts(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, orders={"failed-run-1": "5"}), RULES, USD, AT)

        assert kinds(found) == [DifferenceKind.UNKNOWN_ORDER]
        assert found.differences[0].subject == "failed-run-1"

    def test_someone_elses_working_order_halts(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, foreign=2), RULES, USD, AT)

        assert kinds(found) == [DifferenceKind.FOREIGN_ORDER]

    def test_different_shares_remaining_halts(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, orders={BUY: "1"}), RULES, USD, AT)

        assert kinds(found) == [DifferenceKind.ORDER]
        assert found.differences[0].detail == "Tyche expects 3 shares to fill, the broker 1"

    def test_what_the_adapter_could_not_settle_halts(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, unresolved=("execution 0001.01 awaits a commission",))

        found = reconcile(mine, theirs, RULES, USD, AT)

        assert kinds(found) == [DifferenceKind.UNRESOLVED]


class TestEndedOrders:
    def test_a_stop_gone_with_no_shares_moved_is_corrected_not_halted(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, without=(STOP,)), RULES, USD, AT)

        assert found.status is ReconciliationStatus.CORRECTED
        assert found.ended == (EndedOrder(STOP, SPY, OrderType.STOP),)

    def test_a_market_order_that_did_not_trade_ended_too(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, without=(BUY, STOP)), RULES, USD, AT)

        assert [e.client_order_id for e in found.ended] == [BUY, STOP]
        assert found.status is ReconciliationStatus.CORRECTED


class TestMissedFills:
    def test_a_stop_that_sold_on_a_missed_day_is_explained_and_priced_from_cash(self) -> None:
        mine = tyche()
        # Sold 6 at 439.50 less USD 1 of commission: 2,636 more cash.
        theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("7935"), without=(STOP,))

        found = reconcile(mine, theirs, RULES, USD, AT)

        assert found.status is ReconciliationStatus.MISMATCH
        assert found.differences == ()
        (fill,) = found.inferred
        assert fill == InferredFill(STOP, SPY, Side.SELL, Decimal(6), usd("439.333333"))
        assert found.cash[0].outcome is CashOutcome.PRICED

    def test_a_purchase_on_a_missed_day_is_explained(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "13"}, cash=usd("3878"), without=(BUY,))

        found = reconcile(mine, theirs, RULES, USD, AT)

        (fill,) = found.inferred
        assert (fill.side, fill.quantity, fill.price) == (Side.BUY, Decimal(3), usd("473.666667"))

    def test_shares_that_do_not_match_the_missing_order_are_not_explained(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "5"}, cash=usd("7935"), without=(STOP,))

        found = reconcile(mine, theirs, RULES, USD, AT)

        assert found.inferred == ()
        assert kinds(found) == [DifferenceKind.POSITION, DifferenceKind.CASH]
        assert STOP in found.differences[0].detail

    def test_cash_that_moved_the_wrong_way_cannot_price_it(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("5000"), without=(STOP,))

        found = reconcile(mine, theirs, RULES, USD, AT)

        assert found.inferred == ()
        assert "no positive price" in found.differences[0].detail

    def test_two_missed_fills_in_one_currency_cannot_share_one_gap(self) -> None:
        qqq_buy = WorkingOrder(
            OrderState(order(Side.BUY, "2", instrument=QQQ, client_order_id="qqq-buy"))
            .submit()
            .accept(),
            owed=(OwedShares("beta", Decimal(2)),),
        )
        base = tyche()
        mine = replace(
            base,
            execution=replace(base.execution, orders=(*base.execution.orders, qqq_buy)),
        )
        theirs = broker_record(
            mine, shares={SPY: "4", QQQ: "2"}, cash=usd("7000"), without=(STOP, "qqq-buy")
        )

        found = reconcile(mine, theirs, RULES, USD, AT)

        assert found.inferred == ()
        assert all("several missed fills" in d.detail for d in found.differences[:2])
        assert found.status is ReconciliationStatus.MISMATCH


class TestCash:
    def test_a_gap_within_the_tolerance_is_adopted(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, cash=usd("5298.40")), RULES, USD, AT)

        assert found.status is ReconciliationStatus.CORRECTED
        (cash,) = found.cash
        assert (cash.outcome, cash.gap, cash.allowed) == (
            CashOutcome.ADOPTED,
            usd("-0.60"),
            usd("1.00"),
        )

    def test_a_gap_beyond_it_halts(self) -> None:
        mine = tyche()

        found = reconcile(mine, broker_record(mine, cash=usd("5297.99")), RULES, USD, AT)

        assert kinds(found) == [DifferenceKind.CASH]
        assert found.cash[0].outcome is CashOutcome.EXCEEDED

    def test_a_dividend_tyche_credited_and_the_broker_has_not_shown_is_allowed(self) -> None:
        base = tyche()
        mine = replace(base, account=base.account.receive_distribution("SPY:div", usd("18.00")))

        found = reconcile(mine, broker_record(base), RULES, USD, AT)

        assert found.cash[0].allowed == usd("19.00")
        assert found.cash[0].outcome is CashOutcome.ADOPTED

    def test_the_brokers_accrued_dividends_count_on_its_side(self) -> None:
        base = tyche()
        mine = replace(base, account=base.account.receive_distribution("SPY:div", usd("18.00")))

        found = reconcile(mine, broker_record(base, accrued=(usd("18.00"),)), RULES, USD, AT)

        assert found.status is ReconciliationStatus.MATCH

    def test_a_dividend_paid_net_of_withholding_is_allowed_by_last_checks_accrual(self) -> None:
        base = tyche()
        credited = base.account.receive_distribution("SPY:div", usd("18.00"))
        memory = ReconciliationState(
            last_at=datetime(2024, 1, 3, 0, 15, tzinfo=UTC),
            distributions=(usd("18.00"),),
            accrued=(usd("18.00"),),
        )
        mine = replace(base, account=credited, reconciliation=memory)

        # Paid today, 15% withheld: 15.30 arrives, nothing accrued any more.
        found = reconcile(mine, broker_record(base, cash=usd("5314.30")), RULES, USD, AT)

        assert found.cash[0].gap == usd("-2.70")
        assert found.cash[0].allowed == usd("19.00")
        assert found.status is ReconciliationStatus.CORRECTED

    def test_dividends_credited_before_the_last_check_are_no_longer_on_their_way(self) -> None:
        base = tyche()
        credited = base.account.receive_distribution("SPY:div", usd("18.00"))
        memory = ReconciliationState(
            last_at=datetime(2024, 1, 3, 0, 15, tzinfo=UTC), distributions=(usd("18.00"),)
        )
        mine = replace(base, account=credited, reconciliation=memory)

        found = reconcile(mine, broker_record(base), RULES, USD, AT)

        assert found.cash[0].allowed == usd("1.00")
        assert kinds(found) == [DifferenceKind.CASH]

    def test_pending_cash_counts_in_the_total(self) -> None:
        mine = tyche()
        theirs = broker_record(mine)
        pending = Account.reported(
            settled=(usd("5000"),),
            pending=(PendingCash(usd("299"), mine.saved_at.date(), "ibkr"),),
            positions=theirs.account.positions,
            marks={p.instrument: usd("475") for p in theirs.account.positions},
        )

        found = reconcile(mine, replace(theirs, account=pending), RULES, USD, AT)

        assert found.status is ReconciliationStatus.MATCH


class TestNothingHeld:
    def test_an_empty_account_against_an_empty_one_matches(self) -> None:
        base = tyche()
        empty = replace(
            base,
            account=Account.empty().deposit(usd("1000")),
            sleeves=replace(base.sleeves, holdings=(), stops=()),
            execution=ExecutionState(),
        )
        theirs = broker_record(empty)

        assert reconcile(empty, theirs, RULES, USD, AT).status is ReconciliationStatus.MATCH


def test_a_working_order_still_listed_is_never_ended() -> None:
    mine = tyche()
    assert market_order().state.order.client_order_id == BUY

    found = reconcile(mine, broker_record(mine, shares={SPY: "10"}), RULES, USD, AT)

    assert found.ended == ()


@pytest.mark.parametrize("tolerance", ["0", "2.50"])
def test_the_tolerance_is_the_profiles(tolerance: str) -> None:
    mine = tyche()
    rules_ = replace(RULES, cash_tolerance=Decimal(tolerance))

    found = reconcile(mine, broker_record(mine, cash=usd("5298")), rules_, USD, AT)

    expected = CashOutcome.ADOPTED if tolerance == "2.50" else CashOutcome.EXCEEDED
    assert found.cash[0].outcome is expected
