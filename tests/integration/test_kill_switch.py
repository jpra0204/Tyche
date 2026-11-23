"""The kill switch and the manual restart over two years of three sleeves (ADR-0039).

The scenario of the restart tests: sleeves that share instruments, cross and hold
resting stops. A switch engaged mid-run must stop every new order (or, with flatten,
leave the account in cash with no stop working) and let trading start again once
released. A drawdown halt lifted by hand (``AccountRulesState.resumed``) must trade
again from the restart, with the peak counted from there.
"""

from dataclasses import replace
from datetime import date

from tests.integration.test_restart import HALTING, events, run
from tests.support.kill import ScriptedKillSwitch, kill
from tests.support.walks import FIRST, LAST, NYSE
from tyche.core.backtest import BacktestResult, Resume
from tyche.core.domain import Currency, OrderStatus, OrderType, PlanNote, Side
from tyche.core.events import (
    AccountEvent,
    ApprovedPortfolioEvent,
    CancelRequestEvent,
    ExecutionPlanEvent,
    OrderEvent,
)

USD = Currency.USD

ENGAGE = 260
"""The decision the switch is engaged at: about a year in, with positions held and a
stop resting."""


def submitted(result: BacktestResult, *, after: date) -> list[OrderEvent]:
    return [
        e
        for e in events(result, OrderEvent)
        if e.state.status is OrderStatus.SUBMITTED and e.state.order.created_at.date() > after
    ]


def engaged_on(result: BacktestResult) -> date:
    approvals = events(result, ApprovedPortfolioEvent)
    assert approvals[ENGAGE - 1].kill is not None
    assert approvals[ENGAGE - 2].kill is None
    return approvals[ENGAGE - 1].as_of.date()


def test_without_flatten_no_order_goes_out_and_holdings_stay() -> None:
    result = run(FIRST, LAST, kill_switch=ScriptedKillSwitch(kill(), first=ENGAGE))
    day = engaged_on(result)
    held = next(e.account for e in events(result, AccountEvent) if e.as_of.date() == day)
    assert held.positions, "the scenario holds nothing when the switch is engaged"

    assert submitted(result, after=day) == []
    killed = [p for p in events(result, ExecutionPlanEvent) if p.as_of.date() >= day]
    assert {line.note for plan in killed for line in plan.lines} <= {PlanNote.KILLED}
    # Positions only ever shrink from here: resting stops may still sell.
    for later in (e.account for e in events(result, AccountEvent) if e.as_of.date() > day):
        for position in later.positions:
            before = held.position(position.instrument)
            assert before is not None
            assert position.quantity <= before.quantity


def test_a_flatten_leaves_cash_and_no_stop_working() -> None:
    result = run(FIRST, LAST, kill_switch=ScriptedKillSwitch(kill(flatten=True), first=ENGAGE))
    day = engaged_on(result)

    [flattening] = [p for p in events(result, ExecutionPlanEvent) if p.as_of.date() == day]
    assert flattening.lines
    assert {line.note for line in flattening.lines} == {PlanNote.FLATTENED}
    [approval] = [
        e
        for e in result.journal.of_type(ApprovedPortfolioEvent)
        if e.event.as_of == flattening.as_of
    ]
    orders = [
        e.event
        for e in result.journal.of_type(OrderEvent)
        if e.seq > approval.seq
        and e.cycle_id == approval.cycle_id
        and e.event.state.status is OrderStatus.SUBMITTED
    ]
    assert orders
    assert all(e.state.order.side is Side.SELL for e in orders)
    assert all(e.state.order.order_type is OrderType.MARKET for e in orders)
    assert result.account.positions == ()
    assert result.checkpoint is not None
    assert result.checkpoint.execution.orders == ()
    assert result.checkpoint.sleeves.holdings == ()
    assert result.broker_account == result.account
    assert result.free_riding == ()


def test_a_flatten_cancels_the_stops_before_its_sales() -> None:
    result = run(FIRST, LAST, kill_switch=ScriptedKillSwitch(kill(flatten=True), first=ENGAGE))
    day = engaged_on(result)
    cycle = [
        e
        for e in result.journal.entries
        if e.cycle_id is not None and e.cycle_id.startswith(f"XNYS:{day.isoformat()}")
    ]
    kinds = [type(e.event) for e in cycle]
    assert CancelRequestEvent in kinds, "no stop was resting when the switch was engaged"
    last_cancel = max(i for i, k in enumerate(kinds) if k is CancelRequestEvent)
    assert last_cancel < kinds.index(OrderEvent)


def test_released_the_run_trades_again() -> None:
    until = ENGAGE + 40
    result = run(
        FIRST, LAST, kill_switch=ScriptedKillSwitch(kill(flatten=True), first=ENGAGE, until=until)
    )
    approvals = events(result, ApprovedPortfolioEvent)
    released_on = approvals[until - 1].as_of.date()
    assert approvals[until - 1].kill is None

    assert any(e.state.order.side is Side.BUY for e in submitted(result, after=released_on))
    assert result.account.positions


def test_a_halt_lifted_by_hand_trades_again_with_a_new_peak() -> None:
    whole = run(FIRST, LAST, risk=HALTING)
    [halt] = [t for t in whole.triggers if t.rule.name == "DRAWDOWN_KILL"]
    cut = NYSE.next_session(halt.at.date()).day
    before = run(FIRST, cut, risk=HALTING, run_id="before")
    assert before.checkpoint is not None
    assert before.broker_state is not None
    assert before.checkpoint.rules.halt == halt

    restart = Resume(
        replace(before.checkpoint, run_id="resumed", rules=before.checkpoint.rules.resumed()),
        before.broker_state,
    )
    after = run(NYSE.next_session(cut).day, LAST, risk=HALTING, resume=restart, run_id="after")

    assert any(e.state.status is OrderStatus.SUBMITTED for e in events(after, OrderEvent))
    # The old peak would halt again at the first close; the new one starts there.
    closes = events(after, AccountEvent)
    assert closes[0].account.equity(USD) < halt.reference * (1 - HALTING.profile.drawdown_kill)
    again = next((t for t in after.triggers if t.rule is halt.rule), None)
    assert again is None or again.at > closes[0].as_of
    measured = [c for c in closes if again is None or c.as_of <= again.at]
    assert after.checkpoint is not None
    assert after.checkpoint.rules.peak == (max(c.account.equity(USD) for c in measured),)
