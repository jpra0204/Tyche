"""The SQLite checkpoint store: one per run, append-only, tied to a stored journal."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from tests.support.checkpoints import SAVED_AT, checkpoint
from tests.support.reconciliation import unreconciled
from tyche.adapters.storage import SqliteCheckpointStore, SqliteJournalStore, codec, open_database
from tyche.core.domain import ReconciliationState
from tyche.core.events import Envelope, RunEvent, RunMode, RunStage
from tyche.core.ports import CheckpointStore, CheckpointStoreError


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "tyche.db"


@pytest.fixture
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(open_database(path)) as opened:
        yield opened


@pytest.fixture
def store(connection: sqlite3.Connection) -> SqliteCheckpointStore:
    return SqliteCheckpointStore(connection)


def journal_run(connection: sqlite3.Connection, run_id: str) -> None:
    """Store a run's first envelope, as the paper cycle's journal will."""
    started = RunEvent(run_id, RunMode.PAPER, RunStage.STARTED, "0.1.0+gtest")
    SqliteJournalStore(connection).append(run_id, Envelope(1, SAVED_AT, "engine", started))


def test_is_a_checkpoint_store_and_starts_empty(store: SqliteCheckpointStore) -> None:
    typed: CheckpointStore = store
    assert typed.latest() is None
    assert typed.read("paper-2024-01-03") is None


def test_reads_back_the_same_checkpoint(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-2024-01-03")
    saved = checkpoint()

    store.save(saved)

    assert store.latest() == saved
    assert store.read("paper-2024-01-03") == saved


def test_survives_closing_and_reopening_the_file(path: Path) -> None:
    with closing(open_database(path)) as connection:
        journal_run(connection, "paper-2024-01-03")
        SqliteCheckpointStore(connection).save(checkpoint())

    with closing(open_database(path)) as connection:
        assert SqliteCheckpointStore(connection).latest() == checkpoint()


def test_the_latest_is_the_last_saved(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    for day, run_id in enumerate(("paper-1", "paper-2", "paper-3")):
        journal_run(connection, run_id)
        store.save(checkpoint(run_id, saved_at=SAVED_AT + timedelta(days=day)))

    latest = store.latest()
    assert latest is not None
    assert latest.run_id == "paper-3"
    first = store.read("paper-1")
    assert first is not None
    assert first.saved_at == SAVED_AT


def test_refuses_a_second_checkpoint_for_one_run(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-1")
    store.save(checkpoint("paper-1"))

    with pytest.raises(CheckpointStoreError, match="A run saves one checkpoint"):
        store.save(checkpoint("paper-1", saved_at=SAVED_AT + timedelta(days=1)))
    assert store.latest() == checkpoint("paper-1")


def test_refuses_a_run_whose_journal_is_not_stored(store: SqliteCheckpointStore) -> None:
    with pytest.raises(CheckpointStoreError, match="only once its journal is stored"):
        store.save(checkpoint("never-journalled"))
    assert store.latest() is None


def test_refuses_a_checkpoint_not_later_than_the_latest(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-1")
    journal_run(connection, "paper-0")
    store.save(checkpoint("paper-1"))

    with pytest.raises(CheckpointStoreError, match="is not later than the latest"):
        store.save(checkpoint("paper-0", saved_at=SAVED_AT))
    latest = store.latest()
    assert latest is not None
    assert latest.run_id == "paper-1"


@pytest.mark.parametrize(
    "statement",
    ["UPDATE checkpoint SET payload = '{}'", "DELETE FROM checkpoint"],
)
def test_rows_are_never_changed_or_removed(
    connection: sqlite3.Connection, store: SqliteCheckpointStore, statement: str
) -> None:
    journal_run(connection, "paper-1")
    store.save(checkpoint("paper-1"))

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(statement)
    connection.rollback()
    assert store.latest() == checkpoint("paper-1")


def insert_raw(connection: sqlite3.Connection, run_id: str, fmt: int, payload: str) -> None:
    connection.execute(
        "INSERT INTO checkpoint (run_id, saved_at, format, payload) VALUES (?, ?, ?, ?)",
        (run_id, SAVED_AT.isoformat(), fmt, payload),
    )
    connection.commit()


def test_refuses_a_stored_checkpoint_whose_parts_disagree(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-1")
    raw = json.loads(codec.dumps_checkpoint(checkpoint("paper-1")))
    holdings = raw["fields"]["sleeves"]["fields"]["holdings"]["$tuple"]
    holdings[1]["fields"]["quantity"] = {"$decimal": "5"}
    insert_raw(connection, "paper-1", codec.FORMAT, json.dumps(raw))

    with pytest.raises(CheckpointStoreError, match=r"cannot be read: .*the sleeves hold 11"):
        store.latest()


def test_refuses_a_format_it_cannot_read(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-1")
    insert_raw(connection, "paper-1", codec.FORMAT + 1, codec.dumps_checkpoint(checkpoint()))

    with pytest.raises(CheckpointStoreError, match="stored in format 2"):
        store.read("paper-1")


def test_refuses_a_row_holding_another_runs_state(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-1")
    insert_raw(connection, "paper-1", codec.FORMAT, codec.dumps_checkpoint(checkpoint("other")))

    with pytest.raises(CheckpointStoreError, match="holds run 'other'"):
        store.latest()


def test_needs_a_connection_from_open_database(tmp_path: Path) -> None:
    with (
        closing(sqlite3.connect(tmp_path / "plain.db", autocommit=True)) as plain,
        pytest.raises(CheckpointStoreError, match="open_database"),
    ):
        SqliteCheckpointStore(plain)


def test_the_codec_refuses_anything_but_a_checkpoint() -> None:
    with pytest.raises(codec.CodecError, match="expected a Checkpoint"):
        codec.dumps_checkpoint("not a checkpoint")  # type: ignore[arg-type]
    started = RunEvent("r", RunMode.PAPER, RunStage.STARTED, "0.1.0")
    with pytest.raises(codec.CodecError, match="not a checkpoint"):
        codec.loads_checkpoint(codec.dumps(started))


def test_reads_back_a_reconciliation_halt(
    connection: sqlite3.Connection, store: SqliteCheckpointStore
) -> None:
    journal_run(connection, "paper-halted")
    halted = unreconciled()

    store.save(halted)

    assert store.read("paper-halted") == halted
    assert halted.reconciliation.halt is not None
    assert halted.reconciliation.halt.inferred


def test_a_checkpoint_stored_before_reconciliation_reads_back_with_an_empty_memory() -> None:
    raw = json.loads(codec.dumps_checkpoint(checkpoint()))
    del raw["fields"]["reconciliation"]

    loaded = codec.loads_checkpoint(json.dumps(raw))

    assert loaded == checkpoint()
    assert loaded.reconciliation == ReconciliationState()
