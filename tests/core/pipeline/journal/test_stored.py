"""The stored journal: every envelope handed to the store, first, and nothing lost silently."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from tyche.core.events import (
    Envelope,
    Event,
    EventBus,
    HandlerError,
    RunEvent,
    RunMode,
    RunStage,
)
from tyche.core.pipeline.journal import JournalView, StoredJournal
from tyche.core.ports import JournalStore, JournalStoreError
from tyche.core.sim import SimClock


@dataclass(frozen=True, slots=True)
class PingEvent(Event):
    n: int


@dataclass(frozen=True, slots=True)
class PongEvent(Event):
    n: int


class ListStore:
    """A ``JournalStore`` in a list, refusing a seq it already holds, as the real one does."""

    def __init__(self, *, fail_at: int | None = None) -> None:
        self.rows: list[tuple[str, Envelope[Event]]] = []
        self._fail_at = fail_at

    def append(self, run_id: str, envelope: Envelope[Event]) -> None:
        if envelope.seq == self._fail_at:
            raise JournalStoreError("disk full")
        if any(r == run_id and e.seq == envelope.seq for r, e in self.rows):
            raise JournalStoreError("seq already stored")
        self.rows.append((run_id, envelope))

    def read(self, run_id: str) -> tuple[Envelope[Event], ...]:
        return tuple(e for r, e in self.rows if r == run_id)

    def run_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r for r, _ in self.rows))


def new_bus() -> EventBus:
    return EventBus(SimClock(datetime(2024, 1, 2, 21, 0, tzinfo=UTC)).now)


def started(run_id: str) -> RunEvent:
    return RunEvent(run_id, RunMode.PAPER, RunStage.STARTED, "0.0.0")


def test_list_store_is_a_journal_store() -> None:
    store: JournalStore = ListStore()
    assert store.run_ids() == ()


def test_stores_every_envelope_under_its_run_in_order() -> None:
    bus, store = new_bus(), ListStore()
    journal = StoredJournal(bus, store, "run-1")

    def pong(envelope: Envelope[PingEvent]) -> None:
        bus.publish(PongEvent(envelope.event.n))

    bus.subscribe(PingEvent, pong, name="ponger")

    bus.publish(started("run-1"), source="engine")
    bus.publish(PingEvent(1), source="feed", cycle_id="c1")
    bus.drain()

    assert len(journal) == 3
    assert [r for r, _ in store.rows] == ["run-1"] * 3
    view = JournalView(store.read("run-1"))
    answer = view.of_type(PongEvent)[0]
    assert [type(e.event).__name__ for e in view.causes_of(answer)] == ["PongEvent", "PingEvent"]
    assert answer.cycle_id == "c1"


def test_an_event_is_stored_before_a_failing_handler_sees_it() -> None:
    bus, store = new_bus(), ListStore()
    StoredJournal(bus, store, "run-1")

    def explode(envelope: Envelope[PingEvent]) -> None:
        raise RuntimeError("boom")

    bus.subscribe(PingEvent, explode, name="strategy")
    bus.publish(PingEvent(7), source="feed")

    with pytest.raises(HandlerError):
        bus.drain()
    assert [e.event for _, e in store.rows] == [PingEvent(7)]


def test_a_store_that_refuses_halts_the_bus() -> None:
    bus, store = new_bus(), ListStore(fail_at=2)
    StoredJournal(bus, store, "run-1")
    bus.publish(PingEvent(1), source="feed")
    bus.publish(PingEvent(2), source="feed")
    bus.publish(PingEvent(3), source="feed")

    with pytest.raises(HandlerError) as raised:
        bus.drain()

    assert isinstance(raised.value.__cause__, JournalStoreError)
    assert bus.halted
    assert [e.seq for _, e in store.rows] == [1]


def test_refuses_a_run_event_for_another_run() -> None:
    bus, store = new_bus(), ListStore()
    StoredJournal(bus, store, "run-1")
    bus.publish(started("run-2"), source="engine")

    with pytest.raises(HandlerError) as raised:
        bus.drain()

    assert "run-2" in str(raised.value.__cause__)
    assert store.rows == []


def test_needs_a_run_id() -> None:
    with pytest.raises(ValueError, match="run id"):
        StoredJournal(new_bus(), ListStore(), "  ")


def test_a_view_refuses_entries_out_of_order() -> None:
    bus, store = new_bus(), ListStore()
    StoredJournal(bus, store, "run-1")
    bus.publish(PingEvent(1), source="feed")
    bus.publish(PingEvent(2), source="feed")
    bus.drain()

    with pytest.raises(ValueError, match="seq order"):
        JournalView(reversed(store.read("run-1")))
