"""SimClock: time that moves only when told to, and never backwards."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tyche.core.events import Event, EventBus
from tyche.core.ports import Clock
from tyche.core.sim import SimClock

CLOSE = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
NEXT_CLOSE = datetime(2024, 1, 3, 21, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SampleEvent(Event):
    n: int


def test_time_stands_still_until_advanced() -> None:
    clock = SimClock(CLOSE)

    assert clock.now() == CLOSE
    assert clock.now() == CLOSE


def test_advance_moves_time_forward() -> None:
    clock = SimClock(CLOSE)

    clock.advance_to(NEXT_CLOSE)

    assert clock.now() == NEXT_CLOSE


def test_advancing_to_the_same_instant_is_allowed() -> None:
    clock = SimClock(CLOSE)

    clock.advance_to(CLOSE)

    assert clock.now() == CLOSE


def test_time_cannot_go_backwards() -> None:
    clock = SimClock(NEXT_CLOSE)

    with pytest.raises(ValueError, match="cannot go backwards"):
        clock.advance_to(CLOSE)

    assert clock.now() == NEXT_CLOSE


def test_rejects_a_naive_start() -> None:
    naive = datetime(2024, 1, 2, 21, 0)  # noqa: DTZ001 - the mistake under test
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        SimClock(naive)


def test_rejects_advancing_to_a_local_time() -> None:
    clock = SimClock(CLOSE)
    local = datetime(2024, 1, 3, 16, 0, tzinfo=timezone(timedelta(hours=-5)))

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        clock.advance_to(local)


def test_sim_clock_satisfies_the_clock_port() -> None:
    def read(clock: Clock) -> datetime:
        return clock.now()

    # The assignment is checked by mypy: SimClock has no base class, only the right shape.
    assert read(SimClock(CLOSE)) == CLOSE


def test_the_bus_stamps_events_with_simulated_time() -> None:
    clock = SimClock(CLOSE)
    bus = EventBus(clock.now)

    first = bus.publish(SampleEvent(1), source="feed")
    clock.advance_to(NEXT_CLOSE)
    second = bus.publish(SampleEvent(2), source="feed")

    assert first.occurred_at == CLOSE
    assert second.occurred_at == NEXT_CLOSE
