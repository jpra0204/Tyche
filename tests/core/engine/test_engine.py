"""The engine: clock to each input, publish, drain; stop cleanly when a subscriber fails."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from tyche.core.engine import Engine
from tyche.core.events import Envelope, Event, EventBus, RunEvent, RunMode, RunStage
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.ports import FeedInput
from tyche.core.sim import SimClock

T0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TickEvent(Event):
    n: int


@dataclass(frozen=True, slots=True)
class EchoEvent(Event):
    n: int


class ListFeed:
    """A feed that plays a fixed list and records how far it was read."""

    def __init__(self, *items: FeedInput) -> None:
        self.items = list(items)
        self.taken = 0

    def inputs(self) -> Iterator[FeedInput]:
        for item in self.items:
            self.taken += 1
            yield item


def tick(n: int, minutes: int, *, cycle: str | None = None) -> FeedInput:
    return FeedInput(T0 + timedelta(minutes=minutes), TickEvent(n), "feed", cycle)


@pytest.fixture
def clock() -> SimClock:
    return SimClock(T0)


@pytest.fixture
def bus(clock: SimClock) -> EventBus:
    return EventBus(clock.now)


def engine(bus: EventBus, clock: SimClock) -> Engine:
    return Engine(
        bus,
        clock,
        run_id="run-1",
        mode=RunMode.BACKTEST,
        code_version="0.0.1",
        config_hash="sha256:abc",
    )


def test_announces_the_run_around_every_input(bus: EventBus, clock: SimClock) -> None:
    journal = InMemoryJournal(bus)

    result = engine(bus, clock).run(ListFeed(tick(1, 0), tick(2, 5)))

    assert [type(e.event).__name__ for e in journal.entries] == [
        "RunEvent",
        "TickEvent",
        "TickEvent",
        "RunEvent",
    ]
    started, completed = journal.of_type(RunEvent)
    assert started.event == RunEvent(
        "run-1", RunMode.BACKTEST, RunStage.STARTED, "0.0.1", "sha256:abc"
    )
    assert completed.event.stage is RunStage.COMPLETED
    assert result.completed
    assert (result.inputs, result.events, result.failure) == (2, 4, None)


def test_the_clock_reaches_each_input_before_it_is_published(
    bus: EventBus, clock: SimClock
) -> None:
    journal = InMemoryJournal(bus)

    engine(bus, clock).run(ListFeed(tick(1, 0), tick(2, 5), tick(3, 5), tick(4, 90)))

    ticks = journal.of_type(TickEvent)
    assert [e.occurred_at - T0 for e in ticks] == [
        timedelta(0),
        timedelta(minutes=5),
        timedelta(minutes=5),
        timedelta(minutes=90),
    ]
    assert clock.now() == T0 + timedelta(minutes=90)


def test_everything_an_input_causes_is_handled_before_the_next_input(
    bus: EventBus, clock: SimClock
) -> None:
    def echo(envelope: Envelope[TickEvent]) -> None:
        bus.publish(EchoEvent(envelope.event.n))

    bus.subscribe(TickEvent, echo, name="echo")
    journal = InMemoryJournal(bus)

    engine(bus, clock).run(ListFeed(tick(1, 0), tick(2, 5)))

    assert [type(e.event).__name__ for e in journal.entries[1:-1]] == [
        "TickEvent",
        "EchoEvent",
        "TickEvent",
        "EchoEvent",
    ]


def test_an_input_can_start_a_decision_cycle(bus: EventBus, clock: SimClock) -> None:
    journal = InMemoryJournal(bus)

    engine(bus, clock).run(ListFeed(tick(1, 0, cycle="XNYS:2024-01-02:1d")))

    assert [type(e.event).__name__ for e in journal.in_cycle("XNYS:2024-01-02:1d")] == ["TickEvent"]


def test_an_empty_feed_still_starts_and_completes(bus: EventBus, clock: SimClock) -> None:
    journal = InMemoryJournal(bus)

    result = engine(bus, clock).run(ListFeed())

    assert [e.event.stage for e in journal.of_type(RunEvent)] == [
        RunStage.STARTED,
        RunStage.COMPLETED,
    ]
    assert result.completed


def test_a_failing_subscriber_stops_the_run_without_raising(bus: EventBus, clock: SimClock) -> None:
    def fail_on_two(envelope: Envelope[TickEvent]) -> None:
        if envelope.event.n == 2:
            raise RuntimeError("strategy crashed")

    bus.subscribe(TickEvent, fail_on_two, name="strategy")
    journal = InMemoryJournal(bus)
    feed = ListFeed(tick(1, 0), tick(2, 5), tick(3, 10))

    result = engine(bus, clock).run(feed)

    assert not result.completed
    assert result.inputs == 1
    assert result.failure is not None
    assert "subscriber 'strategy' failed handling TickEvent" in result.failure
    assert feed.taken == 2  # the third input was never taken
    assert journal.of_type(RunEvent)[-1].event.stage is RunStage.STARTED  # no "completed"
    assert bus.halted


def test_a_feed_that_goes_back_in_time_stops_the_run(bus: EventBus, clock: SimClock) -> None:
    result = engine(bus, clock).run(ListFeed(tick(1, 10), tick(2, 5)))

    assert not result.completed
    assert result.inputs == 1
    assert result.failure is not None
    assert "after the clock had reached" in result.failure
