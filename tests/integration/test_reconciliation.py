"""A backtest's own records reconcile with its simulated broker's (ADR-0044, decision 9).

Both come from the same ledger, so at the end of any run, whatever it left working,
reconciliation must find a match and change nothing. The runs are the restart test's:
three sleeves of the example strategies sharing four instruments over two years.
"""

from datetime import date

import pytest

from tests.integration.test_restart import _market_orders, _resting_stops_and_two_sleeves, run
from tests.support.costs import US_COSTS
from tests.support.reconciliation import RULES, USD
from tests.support.recording import TickingClock
from tests.support.walks import FIRST, NYSE
from tyche.core.domain import ReconciliationStatus
from tyche.core.events import EventBus
from tyche.core.pipeline.reconciliation import correct, reconcile
from tyche.core.sim import SimBroker


@pytest.mark.parametrize(
    "last",
    [date(2022, 1, 3), date(2022, 8, 5), date(2023, 3, 31), date(2023, 12, 29)],
    ids=["market-orders-working", "stops-resting-in-two-sleeves", "quarter-end", "two-years"],
)
def test_a_backtest_reconciles_with_its_broker(last: date) -> None:
    result = run(FIRST, last, run_id=f"to-{last}")
    assert result.checkpoint is not None
    assert result.broker_state is not None
    broker = SimBroker.resume(
        EventBus(TickingClock().now), result.broker_state, US_COSTS, {"XNYS": NYSE}
    )

    found = reconcile(
        result.checkpoint,
        broker.record(),
        RULES,
        USD,
        result.checkpoint.saved_at,
        calendars={"XNYS": NYSE},
    )

    assert found.status is ReconciliationStatus.MATCH, found
    after = correct(result.checkpoint, found)
    assert (after.account, after.sleeves, after.execution) == (
        result.checkpoint.account,
        result.checkpoint.sleeves,
        result.checkpoint.execution,
    )


def test_the_runs_cover_working_orders_and_resting_stops() -> None:
    working = run(FIRST, date(2022, 1, 3), run_id="working").checkpoint
    resting = run(FIRST, date(2022, 8, 5), run_id="resting").checkpoint
    assert working is not None
    assert resting is not None

    assert _market_orders(working)
    assert _resting_stops_and_two_sleeves(resting)
