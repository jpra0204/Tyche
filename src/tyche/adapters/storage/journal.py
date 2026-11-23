"""SqliteJournalStore: the journal in the state database (ADR-0009, ADR-0037)."""

import sqlite3
from datetime import datetime

from tyche.adapters.storage import codec
from tyche.core.events import Envelope, Event
from tyche.core.ports import JournalStoreError

_INSERT = """
INSERT INTO journal
    (run_id, seq, occurred_at, source, event_type, caused_by, cycle_id, format, payload)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_SELECT = """
SELECT seq, occurred_at, source, event_type, caused_by, cycle_id, format, payload
FROM journal WHERE run_id = ? ORDER BY seq
"""
_RUNS = """
SELECT run_id FROM journal WHERE seq = 1 ORDER BY occurred_at, run_id
"""


class SqliteJournalStore:
    """A ``JournalStore`` on a connection from ``open_database``.

    Every ``append`` is its own committed transaction, so an envelope is on disk before
    the next handler runs. A paper cycle publishes a few hundred events a day, so the
    cost of one commit each is small; backtests do not use this store.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        if connection.autocommit is not False:
            raise JournalStoreError("the journal store needs a connection from open_database")
        self._connection = connection

    def append(self, run_id: str, envelope: Envelope[Event]) -> None:
        try:
            payload = codec.dumps(envelope.event)
        except codec.CodecError as error:
            raise JournalStoreError(
                f"run {run_id!r} cannot store envelope {envelope.seq}: {error}"
            ) from error
        row = (
            run_id,
            envelope.seq,
            envelope.occurred_at.isoformat(),
            envelope.source,
            type(envelope.event).__name__,
            envelope.caused_by,
            envelope.cycle_id,
            codec.FORMAT,
            payload,
        )
        try:
            self._connection.execute(_INSERT, row)
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            raise JournalStoreError(
                f"run {run_id!r} refused envelope {envelope.seq} "
                f"({type(envelope.event).__name__}): {error}. A run id is used once, and "
                "an envelope's cause must already be stored"
            ) from error
        except BaseException:
            self._connection.rollback()
            raise

    def read(self, run_id: str) -> tuple[Envelope[Event], ...]:
        rows = self._connection.execute(_SELECT, (run_id,)).fetchall()
        return tuple(self._envelope(run_id, row) for row in rows)

    def run_ids(self) -> tuple[str, ...]:
        return tuple(row[0] for row in self._connection.execute(_RUNS).fetchall())

    @staticmethod
    def _envelope(run_id: str, row: tuple[object, ...]) -> Envelope[Event]:
        seq, occurred_at, source, event_type, caused_by, cycle_id, stored_format, payload = row
        where = f"run {run_id!r}, envelope {seq}"
        if stored_format != codec.FORMAT:
            raise JournalStoreError(
                f"{where} was stored in format {stored_format}; this Tyche reads "
                f"format {codec.FORMAT}"
            )
        try:
            event = codec.loads(str(payload))
        except codec.CodecError as error:
            raise JournalStoreError(f"{where} cannot be read: {error}") from error
        if type(event).__name__ != event_type:
            raise JournalStoreError(
                f"{where} is labelled {event_type} but holds a {type(event).__name__}"
            )
        return Envelope(
            seq=int(str(seq)),
            occurred_at=datetime.fromisoformat(str(occurred_at)),
            source=str(source),
            event=event,
            caused_by=None if caused_by is None else int(str(caused_by)),
            cycle_id=None if cycle_id is None else str(cycle_id),
        )
