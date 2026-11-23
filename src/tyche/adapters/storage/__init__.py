"""Storage adapters: the state database in the workspace's ``state/`` folder.

Available now: ``open_database``, which opens the SQLite file with safe settings and
applies the numbered migrations (ADR-0037); ``SqliteJournalStore``, the append-only
journal of every event with its cause (ADR-0009); and the event ``codec`` it uses.

Planned (Phase 2): orders, fills, the sleeve book, the account view, peak equity and the
halt state across restarts (PR 7). Later: proposals and the strategy lifecycle.
"""

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
    "SqliteJournalStore",
    "StateDatabaseError",
    "bundled_migrations",
    "check_migrations",
    "open_database",
    "schema_version",
]
