"""A reconciliation halt in the risk gate and on the approval (ADR-0044, decision 6)."""

from datetime import date, timedelta

import pytest

from tests.core.risk.test_gate import AS_OF, FakeHoldings, proposal, usd
from tests.support.kill import ScriptedKillSwitch, kill
from tests.support.market import QQQ, SPY, bar
from tests.support.reconciliation import mismatch
from tests.support.recording import Recorder, TickingClock
from tests.support.risk import DEFAULT
from tyche.core.domain import Account, Reconciliation
from tyche.core.events import (
    KEEP,
    AccountEvent,
    ApprovedPortfolioEvent,
    BarEvent,
    EventBus,
    TargetPortfolioEvent,
)
from tyche.core.risk import RiskGate, RiskGateError

HALT = mismatch(AS_OF - timedelta(hours=20))


class TestUnreconciledApproval:
    def test_keeps_everything(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        held = ApprovedPortfolioEvent(AS_OF, proposed.sleeves, (), "default", unreconciled=HALT)

        assert held.keeps_everything
        assert held.wanted("a", SPY) is KEEP

    def test_a_flatten_waits(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        both = ApprovedPortfolioEvent(
            AS_OF, proposed.sleeves, (), "default", kill=kill(flatten=True), unreconciled=HALT
        )

        assert not both.flattens
        assert both.keeps_everything
        assert both.wanted("a", QQQ) is KEEP

    def test_approves_nothing(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        with pytest.raises(ValueError, match="approves nothing"):
            ApprovedPortfolioEvent(
                AS_OF, proposed.sleeves, proposed.targets, "default", unreconciled=HALT
            )

    def test_only_a_mismatch_halts(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        with pytest.raises(ValueError, match="does not halt"):
            ApprovedPortfolioEvent(
                AS_OF, proposed.sleeves, (), "default", unreconciled=Reconciliation(at=AS_OF)
            )

    def test_never_halted_by_a_later_check(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        with pytest.raises(ValueError, match="after it"):
            ApprovedPortfolioEvent(
                AS_OF,
                proposed.sleeves,
                (),
                "default",
                unreconciled=mismatch(AS_OF + timedelta(minutes=1)),
            )


class TestTheGate:
    def decide(self, gate_args: dict[str, object], days: int) -> list[ApprovedPortfolioEvent]:
        bus = EventBus(TickingClock().now)
        RiskGate(bus, DEFAULT, FakeHoldings({("a", SPY): "20"}), **gate_args)  # type: ignore[arg-type]
        recorder = Recorder(bus)
        bus.publish(BarEvent(bar(date(2024, 1, 5), 100.0)), source="feed")
        wanted = proposal({SPY: {"a": "0.5"}})
        for day in range(days):
            at = AS_OF + timedelta(days=day)
            bus.publish(AccountEvent(at, Account.empty().deposit(usd("10000"))), source="account")
            bus.publish(
                TargetPortfolioEvent(at, wanted.sleeves, wanted.targets), source="portfolio"
            )
            bus.drain()
        return [e.event for e in recorder if isinstance(e.event, ApprovedPortfolioEvent)]

    def test_every_decision_of_the_run_carries_the_halt(self) -> None:
        approvals = self.decide({"unreconciled": HALT}, 3)

        assert [a.unreconciled for a in approvals] == [HALT] * 3
        assert all(a.targets == () and a.adjustments == () for a in approvals)

    def test_with_the_kill_switch_too(self) -> None:
        switch = ScriptedKillSwitch(kill(flatten=True))

        (approval,) = self.decide({"unreconciled": HALT, "kill_switch": switch}, 1)

        assert approval.kill == kill(flatten=True)
        assert not approval.flattens

    def test_refuses_a_reconciliation_that_does_not_halt(self) -> None:
        with pytest.raises(RiskGateError, match="does not halt"):
            RiskGate(
                EventBus(TickingClock().now),
                DEFAULT,
                FakeHoldings({}),
                unreconciled=Reconciliation(at=AS_OF),
            )
