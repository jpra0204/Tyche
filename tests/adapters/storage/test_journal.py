"""The SQLite journal: append-only, in order, with its causes, and read back exactly."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.support.events import rare_events
from tyche.adapters.storage import SqliteJournalStore, open_database
from tyche.core.events import (
    CancelRequestEvent,
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

T0 = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class HomemadeEvent(Event):
    n: int


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "tyche.db"


@pytest.fixture
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(open_database(path)) as opened:
        yield opened


@pytest.fixture
def store(connection: sqlite3.Connection) -> SqliteJournalStore:
    return SqliteJournalStore(connection)


def envelope(seq: int, event: Event, *, caused_by: int | None = None) -> Envelope[Event]:
    return Envelope(seq, T0, "test", event, caused_by=caused_by, cycle_id="c1")


def cancel(n: int) -> CancelRequestEvent:
    return CancelRequestEvent(f"o-{n}", "replaced")


def test_is_a_journal_store(store: SqliteJournalStore) -> None:
    typed: JournalStore = store
    assert typed.run_ids() == ()
    assert typed.read("nothing") == ()


def test_reads_back_what_it_stored_in_order(store: SqliteJournalStore) -> None:
    stored = (envelope(1, cancel(1)), envelope(2, cancel(2), caused_by=1))
    for item in stored:
        store.append("run-1", item)

    assert store.read("run-1") == stored


def test_keeps_runs_apart_and_lists_them_oldest_first(store: SqliteJournalStore) -> None:
    store.append("b", Envelope(1, T0, "test", cancel(1)))
    store.append("a", Envelope(1, T0.replace(hour=22), "test", cancel(2)))
    store.append("b", envelope(2, cancel(3)))

    assert store.run_ids() == ("b", "a")
    assert [e.seq for e in store.read("b")] == [1, 2]


def test_every_rare_event_survives_the_database(store: SqliteJournalStore) -> None:
    stored = tuple(envelope(i, event) for i, event in enumerate(rare_events(), start=1))
    for item in stored:
        store.append("run-1", item)

    assert store.read("run-1") == stored


def test_survives_closing_and_reopening(path: Path) -> None:
    with closing(open_database(path)) as first:
        SqliteJournalStore(first).append("run-1", envelope(1, cancel(1)))

    with closing(open_database(path)) as second:
        assert SqliteJournalStore(second).read("run-1") == (envelope(1, cancel(1)),)


def test_refuses_a_seq_twice_and_keeps_working(store: SqliteJournalStore) -> None:
    store.append("run-1", envelope(1, cancel(1)))

    with pytest.raises(JournalStoreError, match="used once"):
        store.append("run-1", envelope(1, cancel(9)))
    store.append("run-1", envelope(2, cancel(2)))

    assert [e.event for e in store.read("run-1")] == [cancel(1), cancel(2)]


def test_refuses_a_cause_that_is_not_stored(store: SqliteJournalStore) -> None:
    store.append("run-1", envelope(1, cancel(1)))

    with pytest.raises(JournalStoreError, match="cause"):
        store.append("run-1", envelope(3, cancel(3), caused_by=2))


def test_refuses_an_event_it_could_not_read_back(store: SqliteJournalStore) -> None:
    with pytest.raises(JournalStoreError, match="not exported"):
        store.append("run-1", envelope(1, HomemadeEvent(1)))
    assert store.read("run-1") == ()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE journal SET source = 'someone'", "DELETE FROM journal"],
)
def test_rows_are_never_changed_or_removed(
    store: SqliteJournalStore, connection: sqlite3.Connection, statement: str
) -> None:
    store.append("run-1", envelope(1, cancel(1)))

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(statement)
    connection.rollback()

    assert store.read("run-1") == (envelope(1, cancel(1)),)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [("format", 99, "format 99"), ("event_type", "FillEvent", "labelled FillEvent")],
)
def test_refuses_to_read_a_row_it_does_not_understand(
    store: SqliteJournalStore,
    connection: sqlite3.Connection,
    column: str,
    value: object,
    message: str,
) -> None:
    store.append("run-1", envelope(1, cancel(1)))
    columns = [d[1] for d in connection.execute("PRAGMA table_info(journal)").fetchall()]
    values = list(connection.execute("SELECT * FROM journal").fetchone())
    row = dict(zip(columns, values, strict=True))
    row.update(run_id="run-2", **{column: value})
    connection.execute(
        f"INSERT INTO journal ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
        tuple(row.values()),
    )
    connection.commit()

    with pytest.raises(JournalStoreError, match=message):
        store.read("run-2")


def test_needs_a_connection_from_open_database(path: Path) -> None:
    raw = closing(sqlite3.connect(path.parent.parent / "raw.db", autocommit=True))
    with raw as connection, pytest.raises(JournalStoreError, match="open_database"):
        SqliteJournalStore(connection)


def test_a_run_on_the_bus_is_stored_and_explained(store: SqliteJournalStore) -> None:
    bus = EventBus(SimClock(T0).now)
    StoredJournal(bus, store, "paper-1")

    def broker(handled: Envelope[CancelRequestEvent]) -> None:
        if handled.event.client_order_id == "o-1":
            bus.publish(cancel(2))

    bus.subscribe(CancelRequestEvent, broker, name="broker")
    bus.publish(RunEvent("paper-1", RunMode.PAPER, RunStage.STARTED, "0.0.0"), source="engine")
    bus.publish(cancel(1), source="execution", cycle_id="2024-01-02")
    bus.drain()

    view = JournalView(store.read("paper-1"))
    last = view.entries[-1]
    assert len(view) == 3
    assert last.source == "broker"
    assert [e.seq for e in view.causes_of(last)] == [3, 2]
    assert view.in_cycle("2024-01-02") == list(view.entries[1:])


def test_a_second_run_with_the_same_id_halts_its_bus(store: SqliteJournalStore) -> None:
    for attempt in (1, 2):
        bus = EventBus(SimClock(T0).now)
        StoredJournal(bus, store, "paper-1")
        bus.publish(cancel(attempt), source="execution")
        if attempt == 1:
            bus.drain()
        else:
            with pytest.raises(HandlerError):
                bus.drain()

    assert [e.event for e in store.read("paper-1")] == [cancel(1)]
