"""The two example strategies through the whole trading path (Phase 1, PR 18).

Two years of the real New York calendar, 2022 and 2023, with seeded random walks that
drift up and now and then drop sharply, so that dips are bought and some stops are hit.
These tests check that the framework carries each strategy's intent through to fills:
a stop placed after its entry and filled by the simulator, and a rotation that only
opens and closes positions at the open after the month's first session.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.support.costs import US_COSTS, usd
from tests.support.market import QQQ, SPY
from tests.support.profiles import US_PROFILE
from tests.support.risk import UNBOUND
from tests.support.walks import FIRST, GLD, LAST, NYSE, TLT, Walks
from tyche.core.backtest import BacktestResult, BacktestSettings, BacktestSpec, run_backtest
from tyche.core.domain import (
    Instrument,
    OrderType,
    Side,
)
from tyche.core.events import OrderEvent
from tyche.core.pipeline.signals import Strategy
from tyche.core.risk import RiskLimits
from tyche.strategies import MeanReversion, TrendRotation


def run(
    strategy: Strategy, instruments: tuple[Instrument, ...], *, risk: RiskLimits = UNBOUND
) -> BacktestResult:
    profile = replace(US_PROFILE, universe=replace(US_PROFILE.universe, instruments=instruments))
    spec = BacktestSpec(
        run_id="examples",
        code_version="0.0.0+gexamples",
        config_hash=None,
        profile=profile,
        costs=US_COSTS,
        strategies=(strategy,),
        budgets={strategy.strategy_id: Decimal(1)},
        risk=risk,
        settings=BacktestSettings(holdout_starts=date(2024, 1, 1), starting_cash=usd("10000")),
        first=FIRST,
        last=LAST,
    )
    result = run_backtest(spec, Walks(), {"XNYS": NYSE})
    assert result.run.completed, result.run.failure
    assert result.account == result.broker_account
    assert result.free_riding == ()
    return result


@pytest.fixture(scope="module")
def dips() -> BacktestResult:
    return run(MeanReversion((SPY, QQQ)), (SPY, QQQ))


@pytest.fixture(scope="module")
def rotation() -> BacktestResult:
    return run(TrendRotation((SPY, QQQ, TLT, GLD), holdings=2), (SPY, QQQ, TLT, GLD))


def test_mean_reversion_trades_dips_and_its_stops_are_hit(dips: BacktestResult) -> None:
    buys = [f for f in dips.fills if f.side is Side.BUY]
    stopped = [f for f in dips.fills if "-stop-" in f.client_order_id]

    assert len(buys) >= 10
    assert stopped, "no stop was hit; the scenario no longer exercises the stop path"
    assert all(f.side is Side.SELL for f in stopped)


def test_every_mean_reversion_entry_gets_its_stop_when_it_fills(dips: BacktestResult) -> None:
    stop_orders = [
        e.event.state.order
        for e in dips.journal.of_type(OrderEvent)
        if e.event.state.order.order_type is OrderType.STOP
    ]
    entries = [f for f in dips.fills if f.side is Side.BUY]

    assert stop_orders
    for entry in entries:
        assert any(o.client_order_id.startswith(f"{entry.fill_id}-stop-") for o in stop_orders), (
            entry
        )


def test_rotation_opens_and_closes_positions_only_after_a_month_turns(
    rotation: BacktestResult,
) -> None:
    # From the month before the run, so a run that starts on a month's first session
    # counts it as one.
    sessions = NYSE.sessions_between(date(2021, 12, 1), LAST)
    after_a_first_session = {
        later.day
        for earlier, first, later in zip(sessions, sessions[1:], sessions[2:], strict=False)
        if first.day.month != earlier.day.month
    }
    held: dict[Instrument, Decimal] = {}
    changes: list[date] = []
    for fill in rotation.fills:
        before = held.get(fill.instrument, Decimal(0))
        after = before + (fill.quantity if fill.side is Side.BUY else -fill.quantity)
        held[fill.instrument] = after
        if before == 0 or after == 0:
            changes.append(fill.trade_date)

    assert len(changes) >= 6
    assert set(changes) <= after_a_first_session
