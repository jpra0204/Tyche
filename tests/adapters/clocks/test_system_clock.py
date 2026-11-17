"""SystemClock reads the real time, so this is the one place a test does too."""

from datetime import UTC, datetime, timedelta

from tyche.adapters.clocks import SystemClock
from tyche.core.ports import Clock


def test_tells_the_current_time_in_utc() -> None:
    clock: Clock = SystemClock()

    before = datetime.now(UTC)
    now = clock.now()
    after = datetime.now(UTC)

    assert now.tzinfo is UTC
    assert before - timedelta(seconds=1) <= now <= after + timedelta(seconds=1)
