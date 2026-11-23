"""The kill switch in the risk gate and on the approval it publishes (ADR-0039)."""

from datetime import date, timedelta

import pytest

from tests.core.risk.test_gate import AS_OF, FakeHoldings, drawdown, proposal, usd
from tests.support.kill import ScriptedKillSwitch, kill
from tests.support.market import QQQ, SPY, bar
from tests.support.recording import Recorder, TickingClock
from tests.support.risk import DEFAULT
from tyche.core.domain import Account, Kill
from tyche.core.events import (
    KEEP,
    AccountEvent,
    ApprovedPortfolioEvent,
    BarEvent,
    EventBus,
    RiskEvent,
    TargetPortfolioEvent,
)
from tyche.core.risk import RiskGate


class TestKilledApproval:
    def test_without_flatten_keeps_everything(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        killed = ApprovedPortfolioEvent(AS_OF, proposed.sleeves, (), "default", kill=kill())
        assert killed.wanted("a", SPY) is KEEP
        assert killed.keeps_everything
        assert not killed.flattens

    def test_with_flatten_every_sleeve_and_instrument_goes_to_zero(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        flat = ApprovedPortfolioEvent(
            AS_OF, proposed.sleeves, (), "default", kill=kill(flatten=True)
        )
        assert flat.wanted("a", SPY) is None
        assert flat.wanted("a", QQQ) is None  # not decided on: still sold
        assert flat.wanted("not-listed", SPY) is None  # a sleeve with no budget now
        assert flat.flattens
        assert not flat.keeps_everything

    def test_a_flatten_sells_under_the_halt_too(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        both = ApprovedPortfolioEvent(
            AS_OF, proposed.sleeves, (), "default", halt=drawdown(), kill=kill(flatten=True)
        )
        assert both.wanted("a", SPY) is None

    def test_approves_nothing(self) -> None:
        proposed = proposal({SPY: {"a": "0.1"}})
        with pytest.raises(ValueError, match="approves nothing"):
            ApprovedPortfolioEvent(
                AS_OF, proposed.sleeves, proposed.targets, "default", kill=kill()
            )


class TestKill:
    def test_needs_a_reason(self) -> None:
        with pytest.raises(ValueError, match="needs a reason"):
            Kill(" ")

    def test_flatten_must_be_a_boolean(self) -> None:
        with pytest.raises(ValueError, match="true or false"):
            Kill("x", flatten=1)  # type: ignore[arg-type]

    def test_engaged_at_must_be_utc(self) -> None:
        with pytest.raises(ValueError, match="UTC"):
            Kill("x", engaged_at=AS_OF.replace(tzinfo=None))


class TestTheGateReadsTheSwitchAtEveryDecision:
    def setup_gate(self, switch: ScriptedKillSwitch) -> tuple[EventBus, Recorder]:
        bus = EventBus(TickingClock().now)
        RiskGate(bus, DEFAULT, FakeHoldings({("a", SPY): "20"}), kill_switch=switch)
        recorder = Recorder(bus)
        bus.publish(BarEvent(bar(date(2024, 1, 5), 100.0)), source="feed")
        return bus, recorder

    def decide(self, bus: EventBus, day: int, wanted: TargetPortfolioEvent) -> None:
        at = AS_OF + timedelta(days=day)
        bus.publish(AccountEvent(at, Account.empty().deposit(usd("10000"))), source="account")
        bus.publish(TargetPortfolioEvent(at, wanted.sleeves, wanted.targets), source="portfolio")
        bus.drain()

    def approvals(self, recorder: Recorder) -> list[ApprovedPortfolioEvent]:
        return [e.event for e in recorder if isinstance(e.event, ApprovedPortfolioEvent)]

    def test_engaged_mid_run_then_released(self) -> None:
        switch = ScriptedKillSwitch(kill(), first=2, until=3)
        bus, recorder = self.setup_gate(switch)
        wanted = proposal({SPY: {"a": "0.5"}})  # 50% is above default's 20%: a cut

        for day in range(3):
            self.decide(bus, day, wanted)

        before, killed, after = self.approvals(recorder)
        assert switch.reads == 3
        assert before.kill is None
        assert before.adjustments
        assert killed.kill == kill()
        assert (killed.targets, killed.adjustments) == ((), ())
        assert killed.sleeves == wanted.sleeves
        assert after.kill is None
        assert after.targets
        cuts = [e.event for e in recorder if isinstance(e.event, RiskEvent)]
        assert len(cuts) == 2  # none at the killed decision

    def test_the_halt_and_the_switch_can_both_be_on(self) -> None:
        switch = ScriptedKillSwitch(kill(flatten=True))
        bus = EventBus(TickingClock().now)
        gate = RiskGate(bus, DEFAULT, FakeHoldings({}), kill_switch=switch)
        recorder = Recorder(bus)
        bus.publish(BarEvent(bar(date(2024, 1, 5), 100.0)), source="feed")
        wanted = proposal({SPY: {"a": "0.1"}})
        for day, equity in enumerate(("10000", "8000")):
            at = AS_OF + timedelta(days=day)
            account = Account.empty().deposit(usd(equity))
            bus.publish(AccountEvent(at, account), source="account")
            bus.publish(
                TargetPortfolioEvent(at, wanted.sleeves, wanted.targets), source="portfolio"
            )
            bus.drain()

        last = self.approvals(recorder)[-1]
        assert gate.halt is not None
        assert last.halt == gate.halt
        assert last.kill == kill(flatten=True)
        assert last.flattens
        assert last.targets == ()
