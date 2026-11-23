"""The state database: safe settings, and numbered migrations applied whole or not at all."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from tyche.adapters.storage import (
    Migration,
    StateDatabaseError,
    bundled_migrations,
    check_migrations,
    open_database,
    schema_version,
)

TABLE = Migration(1, "0001_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY) STRICT;")
COLUMN = Migration(2, "0002_names.sql", "ALTER TABLE things ADD COLUMN name TEXT;")
BROKEN = Migration(
    2,
    "0002_broken.sql",
    "CREATE TABLE half (id INTEGER) STRICT;\nINSERT INTO nowhere VALUES (1);",
)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "tyche.db"


def tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    return {row[0] for row in rows}


@pytest.fixture
def bundled(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(open_database(path)) as connection:
        yield connection


def test_creates_the_file_and_applies_every_bundled_migration(
    path: Path, bundled: sqlite3.Connection
) -> None:
    assert path.is_file()
    assert schema_version(bundled) == len(bundled_migrations()) >= 1
    assert "journal" in tables(bundled)


def test_opens_with_the_safe_settings(bundled: sqlite3.Connection) -> None:
    assert bundled.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert bundled.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert bundled.execute("PRAGMA synchronous").fetchone() == (2,)  # FULL
    assert bundled.autocommit is False


def test_applies_only_the_migrations_a_database_has_not_seen(path: Path) -> None:
    with closing(open_database(path, (TABLE,))) as connection:
        connection.execute("INSERT INTO things (id) VALUES (1)")
        connection.commit()

    with closing(open_database(path, (TABLE, COLUMN))) as connection:
        assert schema_version(connection) == 2
        assert connection.execute("SELECT id, name FROM things").fetchall() == [(1, None)]


def test_a_failed_migration_is_rolled_back_whole(path: Path) -> None:
    with closing(open_database(path, (TABLE,))):
        pass

    with pytest.raises(StateDatabaseError, match=r"0002_broken\.sql failed"):
        open_database(path, (TABLE, BROKEN))

    with closing(open_database(path, (TABLE,))) as connection:
        assert schema_version(connection) == 1
        assert "half" not in tables(connection)


def test_refuses_a_database_written_by_a_later_tyche(path: Path) -> None:
    with closing(open_database(path, (TABLE, COLUMN))):
        pass

    with pytest.raises(StateDatabaseError, match="newer than this Tyche knows"):
        open_database(path, (TABLE,))


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ([("1_things.sql", "")], "is not named"),
        ([("0001_Things.sql", "")], "is not named"),
        ([("0002_things.sql", "")], "numbered from 1"),
        ([("0001_a.sql", ""), ("0001_b.sql", "")], "numbered from 1"),
        ([("0001_a.sql", ""), ("0003_b.sql", "")], "numbered from 1"),
        ([("0001_a.sql", "BEGIN;\nCREATE TABLE a (x);\nCOMMIT;")], "own transaction"),
        ([("0001_a.sql", "PRAGMA user_version = 9;")], "own transaction"),
    ],
)
def test_refuses_migrations_that_break_the_rules(
    files: list[tuple[str, str]], message: str
) -> None:
    with pytest.raises(StateDatabaseError, match=message):
        check_migrations(files)


def test_accepts_trigger_bodies_and_comments() -> None:
    sql = (
        "-- BEGIN is only a word in a comment\n"
        "CREATE TABLE a (x INTEGER) STRICT;\n"
        "CREATE TRIGGER a_frozen BEFORE UPDATE ON a\nBEGIN\n"
        "    SELECT RAISE(ABORT, 'no');\nEND;\n"
    )

    (migration,) = check_migrations([("0001_a.sql", sql)])

    assert migration.version == 1


def test_bundled_migrations_follow_the_rules() -> None:
    migrations = bundled_migrations()

    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "0001_journal.sql"
