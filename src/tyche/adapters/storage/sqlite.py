"""The state database: one SQLite file, opened with safe settings and migrated (ADR-0037)."""

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

_MIGRATION_NAME = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")
_FORBIDDEN = re.compile(r"^\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE|PRAGMA)\b", re.I | re.M)
_TRIGGER_BODY = re.compile(r"\bBEGIN\b.*?\bEND\b\s*;", re.I | re.S)


class StateDatabaseError(Exception):
    """The state database cannot be opened or migrated safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One numbered SQL file."""

    version: int
    name: str
    sql: str


def bundled_migrations() -> tuple[Migration, ...]:
    """The migrations shipped with Tyche, checked and in order."""
    folder = files("tyche.adapters.storage") / "migrations"
    found = [
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in folder.iterdir()
        if entry.name.endswith(".sql")
    ]
    return check_migrations(found)


def check_migrations(found: Iterable[tuple[str, str]]) -> tuple[Migration, ...]:
    """``(file name, SQL)`` pairs as migrations, numbered 1, 2, 3 with no gap.

    Refuses a badly named file, a gap or repeat in the numbers, and any statement that
    would take the transaction or the version away from the runner.
    """
    migrations = []
    for name, sql in found:
        match = _MIGRATION_NAME.fullmatch(name)
        if match is None:
            raise StateDatabaseError(f"migration {name!r} is not named NNNN_short_name.sql")
        outside_triggers = _TRIGGER_BODY.sub("", _without_comments(sql))
        if _FORBIDDEN.search(outside_triggers):
            raise StateDatabaseError(
                f"migration {name} controls its own transaction or pragmas; the runner does that"
            )
        migrations.append(Migration(int(match.group(1)), name, sql))
    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise StateDatabaseError(
            f"migrations must be numbered from 1 with no gap or repeat, found {versions}"
        )
    return tuple(migrations)


def open_database(
    path: Path, migrations: tuple[Migration, ...] | None = None
) -> sqlite3.Connection:
    """Open (or create) the database at ``path``, bring its schema up to date, return it.

    Settings, for a file that holds money and must survive a crash:

    * ``foreign_keys = ON``: SQLite leaves them off unless asked, per connection.
    * ``journal_mode = WAL``: readers (reports, a dashboard) do not block the writer.
    * ``synchronous = FULL``: in WAL mode, a committed transaction survives a power
      cut. ``NORMAL`` would be faster and could lose the last commits.

    The connection is returned in Python's recommended mode, ``autocommit=False``: a
    transaction is always open, and nothing is saved until ``commit()``. Close it when
    done; closing rolls back anything not committed.
    """
    migrations = bundled_migrations() if migrations is None else migrations
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, autocommit=True)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise StateDatabaseError("this SQLite cannot enforce foreign keys")
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if mode is None or str(mode[0]).lower() != "wal":
            raise StateDatabaseError(f"{path} cannot use write-ahead logging (got {mode})")
        connection.execute("PRAGMA synchronous = FULL")
        migrate(connection, migrations, path=path)
        connection.autocommit = False
    except BaseException:
        connection.close()
        raise
    return connection


def schema_version(connection: sqlite3.Connection) -> int:
    """The number of the last migration applied to the database."""
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(
    connection: sqlite3.Connection, migrations: tuple[Migration, ...], *, path: Path
) -> None:
    """Apply every migration newer than the database, each in its own transaction.

    The connection must be in ``autocommit=True`` mode, so that the runner's own
    ``BEGIN`` and ``COMMIT`` are the only transaction. A migration that fails is rolled
    back whole, version included, and the error raised.
    """
    if connection.autocommit is not True:
        raise StateDatabaseError("migrate needs a connection with autocommit=True")
    current = schema_version(connection)
    if current > len(migrations):
        raise StateDatabaseError(
            f"{path} is at schema version {current}, newer than this Tyche knows "
            f"({len(migrations)}); it was written by a later version of Tyche"
        )
    for migration in migrations[current:]:
        script = (
            f"BEGIN IMMEDIATE;\n{migration.sql}\n"
            f"PRAGMA user_version = {migration.version};\nCOMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise StateDatabaseError(
                f"migration {migration.name} failed on {path} and was rolled back: {error}"
            ) from error


def _without_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)
