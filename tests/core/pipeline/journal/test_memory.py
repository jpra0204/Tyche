"""The in-memory journal: everything in order, searchable, and traceable to its cause."""

from dataclasses import dataclass
from datetime import UTC, datetime

from tyche.core.events import Envelope, Event, EventBus
from tyche.core.pipeline.journal import InMemoryJournal
from tyche.core.sim import SimClock


@dataclass(frozen=True, slots=True)
class BarishEvent(Event):
    n: int


@dataclass(frozen=True, slots=True)
class SignalishEvent(Event):
    n: int


@dataclass(frozen=True, slots=True)
class OrderishEvent(Event):
    n: int


def build() -> tuple[EventBus, InMemoryJournal]:
    bus = EventBus(SimClock(datetime(2024, 1, 2, 21, 0, tzinfo=UTC)).now)

    def signal(envelope: Envelope[BarishEvent]) -> None:
        bus.publish(SignalishEvent(envelope.event.n))

    def order(envelope: Envelope[SignalishEvent]) -> None:
        bus.publish(OrderishEvent(envelope.event.n))

    bus.subscribe(BarishEvent, signal, name="strategy")
    bus.subscribe(SignalishEvent, order, name="execution")
    return bus, InMemoryJournal(bus)


def test_records_every_event_in_delivery_order() -> None:
    bus, journal = build()
    bus.publish(BarishEvent(1), source="feed", cycle_id="c1")
    bus.publish(BarishEvent(2), source="feed", cycle_id="c2")
    bus.drain()

    assert len(journal) == 6
    assert [e.seq for e in journal.entries] == [1, 2, 3, 4, 5, 6]


def test_finds_events_by_type_and_by_cycle() -> None:
    bus, journal = build()
    bus.publish(BarishEvent(1), source="feed", cycle_id="c1")
    bus.publish(BarishEvent(2), source="feed", cycle_id="c2")
    bus.drain()

    assert [e.event.n for e in journal.of_type(OrderishEvent)] == [1, 2]
    assert [type(e.event).__name__ for e in journal.in_cycle("c2")] == [
        "BarishEvent",
        "SignalishEvent",
        "OrderishEvent",
    ]


def test_traces_an_event_back_to_the_input_that_caused_it() -> None:
    bus, journal = build()
    bus.publish(BarishEvent(7), source="feed")
    bus.drain()
    [order] = journal.of_type(OrderishEvent)

    chain = journal.causes_of(order)

    assert [(type(e.event).__name__, e.source) for e in chain] == [
        ("OrderishEvent", "execution"),
        ("SignalishEvent", "strategy"),
        ("BarishEvent", "feed"),
    ]
