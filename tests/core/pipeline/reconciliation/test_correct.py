"""Applying a reconciliation: after each check (``correct``) and on resume (``resolve``)."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.support.costs import usd
from tests.support.market import SPY
from tests.support.reconciliation import AT, BUY, RULES, STOP, USD, broker_record
from tests.support.reconciliation import agreeing as tyche
from tyche.core.domain import (
    Currency,
    ReconciliationState,
    ReconciliationStatus,
    SleeveHolding,
)
from tyche.core.pipeline.reconciliation import ReconciliationError, correct, reconcile, resolve

LATER = AT + timedelta(days=1)
TWELVE = {SPY: "12"}


class TestCorrect:
    def test_a_match_is_remembered_and_changes_nothing_else(self) -> None:
        mine = tyche()
        found = reconcile(mine, broker_record(mine), RULES, USD, AT)

        after = correct(mine, found)

        assert (after.account, after.sleeves, after.execution) == (
            mine.account,
            mine.sleeves,
            mine.execution,
        )
        assert after.reconciliation == ReconciliationState(
            last_at=AT, distributions=(usd("0"),), accrued=(usd("0"),)
        )
        assert after.saved_at == AT  # dated by the check, which came after the checkpoint
        assert after.run_id == mine.run_id

    def test_cash_within_the_tolerance_becomes_the_brokers(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, cash=usd("5298.40"), accrued=(usd("0.50"),))
        found = reconcile(mine, theirs, RULES, USD, AT)

        after = correct(mine, found)

        cash = after.account.cash(Currency.USD)
        assert (cash.settled, cash.pending) == (usd("5298.90"), ())
        assert after.reconciliation.accrued == (usd("0.50"),)
        assert after.account.positions == mine.account.positions

    def test_an_ended_stop_leaves_the_orders_and_the_sleeve(self) -> None:
        mine = tyche()
        found = reconcile(mine, broker_record(mine, without=(STOP,)), RULES, USD, AT)

        after = correct(mine, found)

        assert [o.state.order.client_order_id for o in after.execution.orders] == [BUY]
        assert after.sleeves.stops == ()
        assert after.execution.wanted_stops == mine.execution.wanted_stops  # placed again

    def test_a_mismatch_changes_nothing_but_the_halt(self) -> None:
        mine = tyche()
        found = reconcile(mine, broker_record(mine, shares={SPY: "12"}), RULES, USD, AT)

        after = correct(mine, found)

        assert after.reconciliation == ReconciliationState(halt=found)
        assert (after.account, after.sleeves, after.execution) == (
            mine.account,
            mine.sleeves,
            mine.execution,
        )

    def test_a_check_that_agrees_does_not_lift_a_halt(self) -> None:
        mine = tyche()
        halted = correct(
            mine, reconcile(mine, broker_record(mine, shares={SPY: "12"}), RULES, USD, AT)
        )

        after = correct(halted, reconcile(halted, broker_record(halted), RULES, USD, LATER))

        assert after.reconciliation.halt == halted.reconciliation.halt
        assert after.reconciliation.last_at == LATER
        assert not after.reconciliation.halt_is_current

    def test_a_later_mismatch_replaces_the_halt(self) -> None:
        mine = tyche()
        first = reconcile(mine, broker_record(mine, shares={SPY: "12"}), RULES, USD, AT)
        halted = correct(mine, first)
        second = reconcile(halted, broker_record(halted, shares={SPY: "11"}), RULES, USD, LATER)

        assert correct(halted, second).reconciliation.halt == second


class TestResolve:
    def test_a_stop_that_sold_on_a_missed_day_is_applied_to_its_sleeve(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("7935"), without=(STOP,))
        halted = correct(mine, reconcile(mine, theirs, RULES, USD, AT))

        lifted = resolve(halted, LATER)

        assert lifted.reconciliation.halt is None
        assert lifted.reconciliation.last_at == AT
        assert [(h.strategy_id, h.quantity) for h in lifted.sleeves.holdings] == [
            ("beta", Decimal(4))
        ]
        assert lifted.sleeves.stops == ()
        assert [o.state.order.client_order_id for o in lifted.execution.orders] == [BUY]
        position = lifted.account.position(SPY)
        assert position is not None
        assert position.quantity == Decimal(4)
        assert lifted.account.cash(Currency.USD).total == usd("7935")
        # Commission folded into the price: 6 x (439.333333 - 470.10) of realised loss.
        assert lifted.account.realized_pnl(Currency.USD) == usd("-184.600002")
        # And now the records agree.
        again = reconcile(lifted, theirs, RULES, USD, LATER)
        assert again.status is ReconciliationStatus.MATCH

    def test_a_purchase_on_a_missed_day_goes_to_the_sleeves_it_was_for(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "13"}, cash=usd("3878"), without=(BUY,))
        halted = correct(mine, reconcile(mine, theirs, RULES, USD, AT))

        lifted = resolve(halted, LATER)

        beta = next(h for h in lifted.sleeves.holdings if h.strategy_id == "beta")
        assert beta == SleeveHolding(
            "beta", SPY, Decimal(7), usd("1880") + usd("473.666667") * 3, date(2024, 1, 2)
        )
        assert reconcile(lifted, theirs, RULES, USD, LATER).status is ReconciliationStatus.MATCH

    def test_a_new_holding_starts_on_the_day_of_the_check(self) -> None:
        base = tyche()
        mine = replace(
            base,
            sleeves=replace(
                base.sleeves,
                holdings=(
                    *(h for h in base.sleeves.holdings if h.strategy_id == "alpha"),
                    SleeveHolding("gamma", SPY, Decimal(4), usd("1880"), date(2024, 1, 2)),
                ),
            ),
        )
        # Beta held nothing in this book (gamma did): the purchase is beta's first.
        theirs = broker_record(mine, shares={SPY: "13"}, cash=usd("3878"), without=(BUY,))
        halted = correct(mine, reconcile(mine, theirs, RULES, USD, AT))

        lifted = resolve(halted, LATER)

        beta = next(h for h in lifted.sleeves.holdings if h.strategy_id == "beta")
        assert (beta.quantity, beta.entry_date) == (Decimal(3), AT.date())

    def test_unexplained_differences_are_only_lifted(self) -> None:
        mine = tyche()
        halted = correct(
            mine, reconcile(mine, broker_record(mine, shares={SPY: "12"}), RULES, USD, AT)
        )

        lifted = resolve(halted, LATER)

        assert lifted.account.positions == mine.account.positions
        assert lifted.reconciliation.halt is None

    def test_after_a_check_that_agreed_nothing_is_applied(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("7935"), without=(STOP,))
        halted = correct(mine, reconcile(mine, theirs, RULES, USD, AT))
        # Pablo put the account back by hand; the next check agreed.
        agreed = correct(halted, reconcile(halted, broker_record(halted), RULES, USD, LATER))

        lifted = resolve(agreed, LATER + timedelta(hours=1))

        assert lifted.account == agreed.account
        assert lifted.sleeves == agreed.sleeves
        assert lifted.reconciliation == replace(agreed.reconciliation, halt=None)

    def test_nothing_to_lift_is_refused(self) -> None:
        with pytest.raises(ReconciliationError, match="no reconciliation halt"):
            resolve(tyche(), LATER)

    def test_an_explanation_that_does_not_fit_the_checkpoint_is_refused(self) -> None:
        mine = tyche()
        theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("7935"), without=(STOP,))
        halted = correct(mine, reconcile(mine, theirs, RULES, USD, AT))
        gone = replace(
            halted,
            execution=replace(halted.execution, orders=halted.execution.orders[:1]),
            sleeves=replace(halted.sleeves, stops=()),
        )

        with pytest.raises(ReconciliationError, match="not one of the checkpoint's working orders"):
            resolve(gone, LATER)


def test_the_checkpoint_refuses_a_reconciliation_after_it_was_saved() -> None:
    mine = tyche()
    found = reconcile(mine, broker_record(mine), RULES, USD, AT)

    with pytest.raises(ValueError, match="comes after it was saved"):
        replace(mine, reconciliation=ReconciliationState(halt=None, last_at=found.at))


def test_a_check_dated_in_another_time_zone_still_applies() -> None:
    mine = tyche()
    theirs = broker_record(mine, shares={SPY: "4"}, cash=usd("7935"), without=(STOP,))
    eastern = AT.astimezone(ZoneInfo("America/New_York"))
    halted = correct(mine, reconcile(mine, theirs, RULES, USD, eastern))

    lifted = resolve(halted, LATER)

    assert lifted.account.position(SPY) is not None
