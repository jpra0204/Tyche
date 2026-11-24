"""The broker order store: written before sending, fates that only move forward."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.support.ledger import order
from tyche.adapters.storage import (
    BrokerOrderStoreError,
    Fate,
    SqliteBrokerOrderStore,
    open_database,
)
from tyche.core.domain import OrderState

AT = datetime(2024, 1, 2, 21, 30, tzinfo=UTC)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(open_database(tmp_path / "state" / "tyche.db")) as opened:
        yield opened


@pytest.fixture
def store(connection: sqlite3.Connection) -> SqliteBrokerOrderStore:
    return SqliteBrokerOrderStore(connection)


def submitted(order_id: str = "o-1") -> OrderState:
    return OrderState(order(client_order_id=order_id)).submit()


def test_needs_a_connection_from_open_database(tmp_path: Path) -> None:
    with (
        closing(sqlite3.connect(tmp_path / "x.db", autocommit=True)) as raw,
        pytest.raises(BrokerOrderStoreError, match="open_database"),
    ):
        SqliteBrokerOrderStore(raw)


def test_an_order_is_written_as_sending_and_read_back_whole(
    store: SqliteBrokerOrderStore,
) -> None:
    state = submitted()
    store.record_sending(state, AT)
    record = store.get("o-1")
    assert record is not None
    assert record.state == state
    assert (record.fate, record.sent_at, record.order_id, record.perm_id) == (
        Fate.SENDING,
        AT,
        None,
        None,
    )
    assert record.client_order_id == "o-1"
    assert not record.cancel_requested
    assert store.get("o-2") is None


def test_an_order_is_written_once(store: SqliteBrokerOrderStore) -> None:
    store.record_sending(submitted(), AT)
    with pytest.raises(BrokerOrderStoreError, match="already recorded"):
        store.record_sending(submitted(), AT)


def test_it_survives_a_new_connection(tmp_path: Path) -> None:
    path = tmp_path / "state" / "tyche.db"
    with closing(open_database(path)) as first:
        SqliteBrokerOrderStore(first).record_sending(submitted(), AT)
    with closing(open_database(path)) as second:
        assert SqliteBrokerOrderStore(second).get("o-1") is not None


def test_placed_then_ids_then_states(store: SqliteBrokerOrderStore) -> None:
    state = submitted()
    store.record_sending(state, AT)
    store.record_placed("o-1", 101, AT)
    store.record_perm_id("o-1", 900001, AT)
    accepted = state.accept()
    store.record_state(accepted, AT)
    store.request_cancel("o-1", AT)
    record = store.get("o-1")
    assert record is not None
    assert (record.fate, record.order_id, record.perm_id) == (Fate.PLACED, 101, 900001)
    assert record.state == accepted
    assert record.cancel_requested
    assert store.unfinished() == (record,)


def test_a_lost_order_is_final(store: SqliteBrokerOrderStore) -> None:
    state = submitted()
    store.record_sending(state, AT)
    store.record_lost("o-1", state.reject("lost"), AT)
    record = store.get("o-1")
    assert record is not None
    assert record.fate is Fate.LOST
    assert store.unfinished() == ()
    changes: list[Callable[[], None]] = [
        lambda: store.record_placed("o-1", 101, AT),
        lambda: store.record_state(state.reject("x"), AT),
        lambda: store.request_cancel("o-1", AT),
        lambda: store.record_lost("o-1", state.reject("again"), AT),
    ]
    for change in changes:
        with pytest.raises(BrokerOrderStoreError, match="is lost"):
            change()


def test_a_perm_id_needs_a_placed_order(store: SqliteBrokerOrderStore) -> None:
    store.record_sending(submitted(), AT)
    with pytest.raises(BrokerOrderStoreError, match="is sending"):
        store.record_perm_id("o-1", 900001, AT)


def test_an_order_never_recorded_cannot_change(store: SqliteBrokerOrderStore) -> None:
    with pytest.raises(BrokerOrderStoreError, match="never recorded"):
        store.record_placed("o-9", 1, AT)


def test_orders_are_listed_oldest_first(store: SqliteBrokerOrderStore) -> None:
    store.record_sending(submitted("b"), AT)
    store.record_sending(submitted("a"), AT + timedelta(seconds=1))
    assert [r.client_order_id for r in store.all()] == ["b", "a"]


def test_fills_are_recorded_once_and_only_for_known_orders(
    store: SqliteBrokerOrderStore,
) -> None:
    store.record_sending(submitted(), AT)
    assert not store.fill_seen("e-1")
    store.record_fill("e-1", "o-1", AT)
    assert store.fill_seen("e-1")
    assert store.fills() == ("e-1",)
    with pytest.raises(BrokerOrderStoreError, match="e-1"):
        store.record_fill("e-1", "o-1", AT)
    with pytest.raises(BrokerOrderStoreError, match="e-2"):
        store.record_fill("e-2", "o-unknown", AT)


def test_fills_are_append_only(
    store: SqliteBrokerOrderStore, connection: sqlite3.Connection
) -> None:
    store.record_sending(submitted(), AT)
    store.record_fill("e-1", "o-1", AT)
    for statement in ("UPDATE broker_fill SET exec_id = 'x'", "DELETE FROM broker_fill"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(statement)
        connection.rollback()


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("format", 99, "format 99"),
        ("state", '{"$type": "Money", "fields": {}}', "cannot be read"),
        ("state", '"text"', "holds a str"),
    ],
)
def test_a_row_this_tyche_cannot_read_is_refused(
    store: SqliteBrokerOrderStore,
    connection: sqlite3.Connection,
    column: str,
    value: object,
    message: str,
) -> None:
    store.record_sending(submitted(), AT)
    connection.execute(f"UPDATE broker_order SET {column} = ?", (value,))
    connection.commit()
    with pytest.raises(BrokerOrderStoreError, match=message):
        store.get("o-1")


def test_a_failed_write_is_rolled_back(
    store: SqliteBrokerOrderStore, connection: sqlite3.Connection
) -> None:
    store.record_sending(submitted(), AT)
    connection.execute(
        "CREATE TRIGGER no_more BEFORE UPDATE ON broker_order "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="refused"):
        store.record_placed("o-1", 101, AT)
    record = store.get("o-1")
    assert record is not None
    assert record.fate is Fate.SENDING
    connection.execute("DROP TRIGGER no_more")
    connection.commit()
    store.record_placed("o-1", 101, AT)  # nothing half-done was left behind
