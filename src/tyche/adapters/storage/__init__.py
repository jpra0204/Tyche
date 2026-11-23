"""Storage adapters: the state database in the workspace's ``state/`` folder.

Available now: ``open_database``, which opens the SQLite file with safe settings and
applies the numbered migrations (ADR-0037); ``SqliteJournalStore``, the append-only
journal of every event with its cause (ADR-0009); ``SqliteCheckpointStore``, the state
each run hands to the next (ADR-0038); and the ``codec`` both use.

Later: proposals and the strategy lifecycle.
"""

from tyche.adapters.storage.checkpoint import SqliteCheckpointStore
from tyche.adapters.storage.journal import SqliteJournalStore
from tyche.adapters.storage.sqlite import (
    Migration,
    StateDatabaseError,
    bundled_migrations,
    check_migrations,
    open_database,
    schema_version,
)

__all__ = [
    "Migration",
    "SqliteCheckpointStore",
    "SqliteJournalStore",
    "StateDatabaseError",
    "bundled_migrations",
    "check_migrations",
    "open_database",
    "schema_version",
]
