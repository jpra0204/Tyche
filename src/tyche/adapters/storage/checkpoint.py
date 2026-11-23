"""SqliteCheckpointStore: each run's checkpoint in the state database (ADR-0038)."""

import sqlite3
from datetime import datetime

from tyche.adapters.storage import codec
from tyche.core.domain import Checkpoint
from tyche.core.ports import CheckpointStoreError

_INSERT = "INSERT INTO checkpoint (run_id, saved_at, format, payload) VALUES (?, ?, ?, ?)"
_LATEST = "SELECT run_id, format, payload FROM checkpoint ORDER BY number DESC LIMIT 1"
_BY_RUN = "SELECT run_id, format, payload FROM checkpoint WHERE run_id = ?"
_LATEST_SAVED_AT = "SELECT run_id, saved_at FROM checkpoint ORDER BY number DESC LIMIT 1"


class SqliteCheckpointStore:
    """A ``CheckpointStore`` on a connection from ``open_database``.

    Each ``save`` is its own committed transaction. The table is append-only, one row
    per run, and each row's run must have its journal stored (a foreign key to the
    run's first envelope), so the journal can always explain the state a checkpoint
    hands on.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        if connection.autocommit is not False:
            raise CheckpointStoreError("the checkpoint store needs a connection from open_database")
        self._connection = connection

    def save(self, checkpoint: Checkpoint) -> None:
        run_id = checkpoint.run_id
        try:
            payload = codec.dumps_checkpoint(checkpoint)
        except codec.CodecError as error:
            raise CheckpointStoreError(
                f"run {run_id!r}'s checkpoint cannot be stored: {error}"
            ) from error
        try:
            latest = self._connection.execute(_LATEST_SAVED_AT).fetchone()
            if latest is not None:
                previous_run, previous_at = latest
                if checkpoint.saved_at <= datetime.fromisoformat(str(previous_at)):
                    raise CheckpointStoreError(
                        f"run {run_id!r}'s checkpoint, taken at "
                        f"{checkpoint.saved_at.isoformat()}, is not later than the latest, "
                        f"run {previous_run!r}'s at {previous_at}"
                    )
            self._connection.execute(
                _INSERT, (run_id, checkpoint.saved_at.isoformat(), codec.FORMAT, payload)
            )
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            raise CheckpointStoreError(
                f"run {run_id!r}'s checkpoint was refused: {error}. A run saves one "
                "checkpoint, and only once its journal is stored"
            ) from error
        except BaseException:
            self._connection.rollback()
            raise

    def latest(self) -> Checkpoint | None:
        row = self._connection.execute(_LATEST).fetchone()
        return None if row is None else self._checkpoint(row)

    def read(self, run_id: str) -> Checkpoint | None:
        row = self._connection.execute(_BY_RUN, (run_id,)).fetchone()
        return None if row is None else self._checkpoint(row)

    @staticmethod
    def _checkpoint(row: tuple[object, ...]) -> Checkpoint:
        run_id, stored_format, payload = row
        where = f"run {run_id!r}'s checkpoint"
        if stored_format != codec.FORMAT:
            raise CheckpointStoreError(
                f"{where} was stored in format {stored_format}; this Tyche reads "
                f"format {codec.FORMAT}"
            )
        try:
            checkpoint = codec.loads_checkpoint(str(payload))
        except codec.CodecError as error:
            raise CheckpointStoreError(f"{where} cannot be read: {error}") from error
        if checkpoint.run_id != run_id:
            raise CheckpointStoreError(f"{where} holds run {checkpoint.run_id!r}'s state")
        return checkpoint
