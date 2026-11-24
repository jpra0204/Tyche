"""SystemClock reads the real time, so this is the one place a test does too."""

from datetime import UTC, datetime, timedelta

import pytest

from tyche.adapters.clocks import SystemClock
from tyche.core.ports import Clock, PacedClock


def test_tells_the_current_time_in_utc() -> None:
    clock: Clock = SystemClock()

    before = datetime.now(UTC)
    now = clock.now()
    after = datetime.now(UTC)

    assert now.tzinfo is UTC
    assert before - timedelta(seconds=1) <= now <= after + timedelta(seconds=1)


class FakeTime:
    """A wall clock a test controls: sleeping moves it forward by the time slept."""

    def __init__(self, start: datetime) -> None:
        self.current = start
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.current += timedelta(seconds=seconds)


T0 = datetime(2026, 11, 24, 23, 0, tzinfo=UTC)


def test_is_a_paced_clock() -> None:
    clock: PacedClock = SystemClock()

    clock.wait_until(datetime(2000, 1, 1, tzinfo=UTC))  # long past: returns at once


def test_waits_until_a_future_moment() -> None:
    fake = FakeTime(T0)
    clock = SystemClock(now=fake.now, sleep=fake.sleep)

    clock.wait_until(T0 + timedelta(minutes=5))

    assert fake.slept == [300.0]
    assert clock.now() == T0 + timedelta(minutes=5)


def test_keeps_sleeping_when_woken_early() -> None:
    fake = FakeTime(T0)
    asked: list[float] = []

    def sleep(seconds: float) -> None:
        asked.append(seconds)
        fake.current += timedelta(seconds=seconds / 2 if len(asked) == 1 else seconds)

    SystemClock(now=fake.now, sleep=sleep).wait_until(T0 + timedelta(seconds=10))

    assert asked == [10.0, 5.0]


def test_a_moment_already_passed_returns_without_sleeping() -> None:
    # The daily feed stamps an input when it became known; by the time the engine asks
    # to wait for it, that moment has passed (ADR-0043).
    fake = FakeTime(T0)
    clock = SystemClock(now=fake.now, sleep=fake.sleep)

    clock.wait_until(T0 - timedelta(seconds=1))

    assert fake.slept == []


def test_refuses_a_naive_moment() -> None:
    with pytest.raises(ValueError, match="UTC"):
        SystemClock().wait_until(datetime(2026, 11, 24, 23, 0))  # noqa: DTZ001


def test_never_goes_backwards_when_the_system_clock_does() -> None:
    fake = FakeTime(T0)
    clock = SystemClock(now=fake.now, sleep=fake.sleep)
    clock.now()

    fake.current = T0 - timedelta(seconds=2)  # an NTP correction

    assert clock.now() == T0
