"""The pass-through gate approves every proposed portfolio unchanged (Phase 1)."""

from datetime import UTC, datetime
from decimal import Decimal

from tests.support.market import SPY
from tests.support.recording import Recorder, TickingClock
from tyche.core.domain import Contribution, InstrumentTarget, Sleeve, SleeveStatus
from tyche.core.events import ApprovedPortfolioEvent, EventBus, TargetPortfolioEvent
from tyche.core.risk import PASS_THROUGH, PassThroughGate

AS_OF = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)


def test_approves_the_proposed_portfolio_as_it_is_and_says_so() -> None:
    bus = EventBus(TickingClock().now)
    PassThroughGate(bus)
    recorder = Recorder(bus)
    sleeves = (Sleeve("a", Decimal(1), SleeveStatus.DECIDED, (SPY,), "1"),)
    targets = (InstrumentTarget(SPY, (Contribution("a", Decimal(1), "hold"),)),)

    bus.publish(TargetPortfolioEvent(AS_OF, sleeves, targets), source="portfolio")
    bus.drain()

    [approved] = [e for e in recorder if isinstance(e.event, ApprovedPortfolioEvent)]
    assert approved.event == ApprovedPortfolioEvent(AS_OF, sleeves, targets, PASS_THROUGH)
    assert approved.source == "risk"
    assert approved.caused_by == recorder.envelopes[0].seq
