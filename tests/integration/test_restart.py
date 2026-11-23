"""A run stopped after a close and carried on from its checkpoint (Phase 2, PR 7).

The strongest test of a checkpoint is that nothing notices it: two years of the
example strategies in three sleeves, sharing instruments so that sleeves cross and
stops rest, run once
straight through and once cut in two, the second half carrying on from the first
half's checkpoint on a new bus with new stages. Every fill, every close, every plan and
every risk decision must be the same, and the two runs must end in the same state.

The simulator stands in for the broker, which keeps the account while Tyche is
stopped, so it carries on from its own state (``SimBroker.resume``).
"""

from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.support.costs import US_COSTS, usd
from tests.support.market import QQQ, SPY
from tests.support.profiles import US_PROFILE
from tests.support.risk import UNBOUND, guardrails, profile
from tests.support.walks import FIRST, GLD, LAST, NYSE, TLT, Walks
from tyche.adapters.storage import SqliteCheckpointStore, SqliteJournalStore, open_database
from tyche.core.backtest import (
    BacktestError,
    BacktestResult,
    BacktestSettings,
    BacktestSpec,
    Resume,
    run_backtest,
)
from tyche.core.domain import Checkpoint, OrderType
from tyche.core.events import (
    AccountEvent,
    ApprovedPortfolioEvent,
    Event,
    ExecutionPlanEvent,
    FillEvent,
    OrderEvent,
    RiskEvent,
)
from tyche.core.risk import RiskLimits
from tyche.strategies import MeanReversion, TrendRotation

INSTRUMENTS = (SPY, QQQ, TLT, GLD)
HALTING = RiskLimits(guardrails(), profile("halting", daily_loss="0.02", drawdown="0.06"))
"""Limits the walks reach: losing sessions block entries, and the drawdown kill halts."""


def run(
    first: date,
    last: date,
    *,
    risk: RiskLimits = UNBOUND,
    resume: Resume | None = None,
    run_id: str = "whole",
) -> BacktestResult:
    spec = BacktestSpec(
        run_id=run_id,
        code_version="0.0.0+grestart",
        config_hash=None,
        profile=replace(US_PROFILE, universe=replace(US_PROFILE.universe, instruments=INSTRUMENTS)),
        costs=US_COSTS,
        strategies=(
            MeanReversion((SPY, QQQ)),
            TrendRotation(INSTRUMENTS, holdings=2),
            TrendRotation(INSTRUMENTS, holdings=1, momentum_sessions=21, strategy_id="fast"),
        ),
        budgets={
            "mean_reversion": Decimal("0.4"),
            "trend_rotation": Decimal("0.3"),
            "fast": Decimal("0.3"),
        },
        risk=risk,
        settings=BacktestSettings(holdout_starts=date(2024, 1, 1), starting_cash=usd("10000")),
        first=first,
        last=last,
    )
    result = run_backtest(spec, Walks(), {"XNYS": NYSE}, resume=resume)
    assert result.run.completed, result.run.failure
    assert result.account == result.broker_account
    return result


def cut_in_two(cut: date, *, risk: RiskLimits = UNBOUND) -> tuple[BacktestResult, BacktestResult]:
    """The same range run up to ``cut``, then carried on from its checkpoint."""
    before = run(FIRST, cut, risk=risk, run_id="before")
    assert before.checkpoint is not None
    assert before.broker_state is not None
    after = run(
        NYSE.next_session(cut).day,
        LAST,
        risk=risk,
        resume=Resume(before.checkpoint, before.broker_state),
        run_id="after",
    )
    return before, after


def events[E: Event](result: BacktestResult, kind: type[E]) -> list[E]:
    return [envelope.event for envelope in result.journal.of_type(kind)]


def require_same(whole: BacktestResult, before: BacktestResult, after: BacktestResult) -> None:
    for kind in (FillEvent, AccountEvent, ExecutionPlanEvent, RiskEvent, ApprovedPortfolioEvent):
        assert events(whole, kind) == events(before, kind) + events(after, kind), kind.__name__
    orders = [e.state for e in events(whole, OrderEvent)]
    assert orders == [e.state for e in events(before, OrderEvent) + events(after, OrderEvent)]
    assert after.account == whole.account
    assert after.broker_state == whole.broker_state
    assert after.free_riding == whole.free_riding == ()
    assert whole.checkpoint is not None
    assert after.checkpoint == replace(whole.checkpoint, run_id="after")


@pytest.fixture(scope="module")
def whole() -> BacktestResult:
    return run(FIRST, LAST)


def _market_orders(checkpoint: Checkpoint) -> bool:
    return any(o.state.order.order_type is OrderType.MARKET for o in checkpoint.execution.orders)


def _resting_stops_and_two_sleeves(checkpoint: Checkpoint) -> bool:
    sleeves = {h.strategy_id for h in checkpoint.sleeves.holdings}
    return bool(checkpoint.sleeves.stops) and len(sleeves) == 2


def test_the_scenario_crosses_sleeves_and_hits_stops(whole: BacktestResult) -> None:
    plans = events(whole, ExecutionPlanEvent)
    assert any(line.crossed for plan in plans for line in plan.lines)
    assert any("-stop-" in fill.client_order_id for fill in whole.fills)


@pytest.mark.parametrize(
    ("cut", "found"),
    [(date(2022, 1, 3), _market_orders), (date(2022, 8, 5), _resting_stops_and_two_sleeves)],
    ids=["market-orders-working", "stops-resting-in-two-sleeves"],
)
def test_a_restart_carries_on_exactly_as_one_run_would(
    whole: BacktestResult, cut: date, found: Callable[[Checkpoint], bool]
) -> None:
    before, after = cut_in_two(cut)

    assert before.checkpoint is not None
    assert found(before.checkpoint), "the cut no longer leaves the state this test needs"
    require_same(whole, before, after)


@pytest.mark.parametrize("cut", [date(2022, 6, 30), date(2023, 3, 31), date(2023, 9, 29)])
def test_a_restart_at_any_month_end_carries_on_exactly(whole: BacktestResult, cut: date) -> None:
    before, after = cut_in_two(cut)

    require_same(whole, before, after)


def test_the_account_rules_and_a_halt_carry_across_a_restart() -> None:
    whole = run(FIRST, LAST, risk=HALTING)
    halts = [t for t in whole.triggers if t.rule.name == "DRAWDOWN_KILL"]
    assert halts, "the scenario no longer halts"
    halted_on = halts[0].at.date()
    assert halted_on < LAST

    for cut in (NYSE.previous_session(halted_on).day, halted_on):
        before, after = cut_in_two(cut, risk=HALTING)

        require_same(whole, before, after)
        assert after.checkpoint is not None
        assert after.checkpoint.rules.halt == halts[0]
    assert len([t for t in whole.triggers if t.rule.name == "DAILY_LOSS_LIMIT"]) >= 1


def test_refuses_to_carry_on_into_days_already_run(whole: BacktestResult) -> None:
    before = run(FIRST, date(2022, 6, 30), run_id="before")
    assert before.checkpoint is not None
    assert before.broker_state is not None

    with pytest.raises(BacktestError, match="cannot carry on from before's checkpoint"):
        run(
            date(2022, 6, 30),
            LAST,
            resume=Resume(before.checkpoint, before.broker_state),
            run_id="again",
        )


def test_a_restart_from_the_state_database_carries_on_exactly(
    whole: BacktestResult, tmp_path: Path
) -> None:
    before = run(FIRST, date(2022, 8, 5), run_id="before")
    assert before.checkpoint is not None
    assert before.broker_state is not None
    with closing(open_database(tmp_path / "tyche.db")) as connection:
        journal = SqliteJournalStore(connection)
        for envelope in before.journal.entries:
            journal.append("before", envelope)
        SqliteCheckpointStore(connection).save(before.checkpoint)
    with closing(open_database(tmp_path / "tyche.db")) as connection:
        stored = SqliteCheckpointStore(connection).latest()

    assert stored == before.checkpoint
    assert stored is not None
    after = run(
        NYSE.next_session(date(2022, 8, 5)).day,
        LAST,
        resume=Resume(stored, before.broker_state),
        run_id="after",
    )
    require_same(whole, before, after)
