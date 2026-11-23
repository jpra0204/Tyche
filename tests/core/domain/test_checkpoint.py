"""Checkpoint: its parts must agree, or it is refused (ADR-0038)."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from tests.support.checkpoints import (
    LAST_CLOSE,
    checkpoint,
    market_order,
    rules,
    sleeves,
    stop_order,
)
from tests.support.costs import usd
from tests.support.market import QQQ, SPY
from tyche.core.domain import (
    AccountRulesState,
    AccountTrigger,
    ExecutionState,
    OwedShares,
    RiskRule,
    SleeveHolding,
    SleeveState,
    SleeveStop,
    WorkingOrder,
)


def test_a_consistent_checkpoint_is_accepted() -> None:
    built = checkpoint()

    assert built.sleeves.total(SPY) == Decimal(10)
    assert built.rules.halt is not None


def test_refuses_sleeves_that_do_not_add_up_to_the_account() -> None:
    short_by_one = SleeveState(
        holdings=(
            SleeveHolding("alpha", SPY, Decimal(6), usd("2820"), LAST_CLOSE.date()),
            SleeveHolding("beta", SPY, Decimal(3), usd("1410"), LAST_CLOSE.date()),
        ),
        stops=sleeves().stops,
    )

    with pytest.raises(ValueError, match="the sleeves hold 9 SPY"):
        replace(checkpoint(), sleeves=short_by_one)


def test_refuses_a_sleeve_holding_what_the_account_does_not() -> None:
    extra = SleeveHolding("beta", QQQ, Decimal(1), usd("400"), LAST_CLOSE.date())
    book = replace(sleeves(), holdings=(*sleeves().holdings, extra))

    with pytest.raises(ValueError, match="the account 0"):
        replace(checkpoint(), sleeves=book)


def test_refuses_a_resting_stop_with_no_working_stop_order() -> None:
    no_stop = ExecutionState(orders=(market_order(),), last_decision=LAST_CLOSE)

    with pytest.raises(ValueError, match="is not a working stop order of that sleeve"):
        replace(checkpoint(), execution=no_stop)


def test_refuses_a_resting_stop_whose_order_protects_another_sleeve() -> None:
    wrong_sleeve = replace(stop_order(), strategy_id="beta")

    with pytest.raises(ValueError, match="is not a working stop order of that sleeve"):
        replace(checkpoint(), execution=ExecutionState(orders=(wrong_sleeve,)))


def test_a_market_order_owes_exactly_its_remaining_shares() -> None:
    with pytest.raises(ValueError, match="owes its sleeves 2 shares, but 3 remain"):
        replace(market_order(), owed=(OwedShares("beta", Decimal(2)),))


def test_an_order_is_either_a_stop_for_one_sleeve_or_a_market_order_owing_shares() -> None:
    with pytest.raises(ValueError, match="is a market order"):
        WorkingOrder(market_order().state, strategy_id="beta")
    with pytest.raises(ValueError, match="is a stop"):
        WorkingOrder(stop_order().state, owed=(OwedShares("alpha", Decimal(6)),))


def test_a_finished_order_is_not_working() -> None:
    filled = market_order().state.fill(Decimal(3))

    with pytest.raises(ValueError, match="has finished"):
        WorkingOrder(filled, owed=())


def test_refuses_two_entries_for_one_sleeve_and_instrument() -> None:
    holding = sleeves().holdings[0]
    with pytest.raises(ValueError, match="more than one holding of a sleeve"):
        SleeveState(holdings=(holding, holding))
    stop = SleeveStop("alpha", SPY, "s-1", usd("440"))
    with pytest.raises(ValueError, match="more than one stop of a sleeve"):
        SleeveState(stops=(stop, replace(stop, client_order_id="s-2")))
    with pytest.raises(ValueError, match="more than one working order"):
        ExecutionState(orders=(market_order(), market_order()))


def test_account_rules_with_no_close_have_no_memory() -> None:
    assert AccountRulesState() == AccountRulesState(last_close=None)
    with pytest.raises(ValueError, match="no close measured"):
        AccountRulesState(peak=(usd("100"),))


def test_only_the_drawdown_kill_halts_and_never_after_the_last_close() -> None:
    halt = rules(halted=True).halt
    assert halt is not None
    daily = AccountTrigger(
        RiskRule.DAILY_LOSS_LIMIT, LAST_CLOSE, usd("100"), usd("90"), Decimal("0.03"), "x"
    )

    with pytest.raises(ValueError, match="only the drawdown kill"):
        replace(rules(), halt=daily)
    with pytest.raises(ValueError, match="cannot come after"):
        replace(rules(), last_close=LAST_CLOSE - timedelta(days=1), halt=halt)


def test_times_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="saved_at must be timezone-aware"):
        replace(checkpoint(), saved_at=datetime(2024, 1, 3, 21, 0))  # noqa: DTZ001
    with pytest.raises(ValueError, match="last_close must be timezone-aware"):
        AccountRulesState(last_close=datetime(2024, 1, 3, 21, 0))  # noqa: DTZ001


def test_a_checkpoint_needs_a_run_id() -> None:
    with pytest.raises(ValueError, match="needs a run id"):
        replace(checkpoint(), run_id=" ")
