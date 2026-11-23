# ADR-0037: The state database, numbered SQL migrations, and a journal stored as tagged JSON

- **Status:** Accepted (Pablo, 2026-11-23)
- **Date:** 2026-11-23

## Context

[ADR-0009](0009-storage-sqlite-parquet.md) put operational state in SQLite and made the journal append-only, and left one question for the first table: how the schema changes over time. Phase 2, PR 6 creates that first table, the journal, and PR 7 adds the state that carries a paper run across restarts. Until now the journal lived in memory and died with the run.

Pablo answered the open question on 2026-11-23, before any code: **numbered SQL files, versioned by SQLite's `user_version`, with no new dependency.**

Writing the journal to disk raised three more questions, answered below as my recommendation:

1. How is an event, with its Decimals, UTC times, enums and accounts keyed by instrument, stored so that it reads back as the same object, years and versions later, in rows that are never rewritten?
2. When is each event committed, and what happens if the store refuses one?
3. Which runs write to it?

Facts checked on 2026-11-23 against the Python 3.14 `sqlite3` documentation and SQLite's pragma page, and on Tyche's Python (3.14.6, SQLite 3.53.3):

- `user_version` is an integer in the database file's header that SQLite itself never uses. Set inside a transaction and rolled back, it returns to its old value, so a migration and its version bump commit or fail together.
- Python recommends `autocommit=False`, which keeps a transaction always open until `commit()`. Its default date and time adapters are deprecated since 3.12.
- Foreign keys are off unless a connection turns them on, and the pragma does nothing inside a transaction.
- Write-ahead logging (WAL) persists in the file. With `synchronous=NORMAL` a committed transaction can be lost on a power cut; `FULL` makes WAL commits durable.

## Decision

**One file.** The state database is `state/tyche.db` in the workspace (`Workspace.state_database`), gitignored like the rest of `state/`. `tyche.adapters.storage.open_database` opens or creates it with `foreign_keys = ON` (checked), `journal_mode = WAL` (checked), `synchronous = FULL`, applies the migrations, and returns the connection with `autocommit=False`.

**Migrations** are SQL files in `tyche/adapters/storage/migrations/`, named `NNNN_short_name.sql` and numbered from `0001` with no gap. The database's `user_version` is the number of the last one applied. At every open, each newer file runs in one transaction with its version bump (`BEGIN IMMEDIATE … PRAGMA user_version = N; COMMIT`), so it applies whole or not at all; a failure is rolled back and raised. The rules, checked when the files are loaded: a file has no `BEGIN`, `COMMIT` or `PRAGMA` of its own outside a trigger body; a merged file is never edited or renumbered; migrations only go forward. A database at a higher version than this Tyche knows is refused rather than guessed at.

**The journal table** (`0001_journal.sql`) holds one row per envelope: `run_id`, `seq`, `occurred_at` (ISO 8601 text), `source`, `event_type`, `caused_by`, `cycle_id`, `format` and `payload`. The key is (`run_id`, `seq`), because every run's bus numbers from 1. `caused_by` must be an earlier `seq` of the same run, and a foreign key makes the cause already stored. Triggers refuse every `UPDATE` and `DELETE`. The table is `STRICT`, so a column holds only its declared type.

**Events are stored as tagged JSON** (`tyche.adapters.storage.codec`). JSON's own values stand for themselves; a dataclass is `{"$type": name, "fields": {…}}`, an enum `{"$enum": name, "name": member}`, and a Decimal, a datetime, a date, a tuple, a frozenset and a mapping each have their own tag, so that every value reads back equal and of the same type. Only the dataclasses and enums that `tyche.core.domain` and `tyche.core.events` export can be written or read, by name: anything else is refused when it is written, and a stored name never makes the reader import anything. Reading rebuilds each object through its constructor, so its own checks run again. Every row records the codec's `format` (1 today). **Compatibility rule:** adding a field with a default to an event or a value object is compatible. Any other change to a stored type (a rename, a removed field, a new meaning) needs a new format number and a reader that still reads the old one, because the old rows stay as they were written.

**One commit per envelope, and the journal first.** `StoredJournal` (in `tyche.core.pipeline.journal`) subscribes to every event and appends each envelope to a `JournalStore` (a new port) under the run id it was given. It is wired as the first subscriber, so each event is on disk before anything acts on it, and a run that fails leaves a journal ending with the event it failed on. A store that refuses an envelope (a run id used twice, a missing cause, an event it cannot store) raises, and the bus halts: a run whose journal has a gap cannot explain what it did. A `RunEvent` for a different run is refused the same way. A paper cycle publishes a few hundred events a day, so the cost of a commit each is small.

**Who writes to it.** The paper cycle (PR 14) and, later, live. Backtests, walk-forwards, sweeps and comparisons keep the in-memory journal: their record is their run folder ([ADR-0024](0024-backtest-runner-holdout-and-run-record.md)), and thousands of research runs would otherwise fill a file meant for the account's own history. Which journal a run gets is chosen where the run is wired, not in the core, so the pipeline is the same in every mode ([ADR-0005](0005-backtest-paper-live-parity.md)). `JournalView` answers the same questions (by type, by cycle, the chain of causes) over the in-memory journal and over a run read back from the store.

## Alternatives considered

- **Alembic (with SQLAlchemy).** The standard tool: autogenerated migrations, downgrades, branches. Two dependencies and a framework, for one writer and a handful of tables; downgrades are rarely safe for data that holds money anyway. Pablo chose against it.
- **Migrations as Python functions.** Can transform data in code, but a schema change is less visible than a SQL file. A Python step can still be added later for the one migration that needs it.
- **`pickle` for events.** One line, and the worst choice: loading a pickle runs code named in the data, and a renamed class makes every old row unreadable.
- **Pydantic for events.** Already a dependency, for config ([ADR-0010](0010-config-toml-pydantic.md)). It would need a discriminator on every union of dataclasses and cannot write mappings keyed by an `Instrument` to JSON, so the events would bend to the library. About 230 lines of explicit codec is easier to read and to trust.
- **Storing only a readable summary of each event.** Cheaper, but the journal could no longer answer "why did this happen?" with the objects themselves, and PR 7 could not rebuild anything from it.
- **Committing once per decision cycle.** Fewer disk syncs, but a crash mid-cycle would lose the events that explain it, and the bus has no "cycle finished" signal to hang it on.
- **Backtests writing to the database too.** Every research run would leave rows in the account's own history, and a sweep would add thousands of runs. A backtest's record is already complete.

## Consequences

- A paper run's every event is on disk with its cause before the next handler runs, and any order can be traced back to the data that started its cycle, days later.
- Changing the schema means adding a numbered SQL file, never editing one. The [state database](../developer-guide/state-database.md) page says how.
- Changing a stored event in any way but adding a defaulted field needs a codec format change. The round-trip tests fail first: every exported event type must read back identical, from real runs and from samples of the rare ones.
- A run id can be stored once. The paper cycle must give each run its own.
- `STRICT` tables need SQLite 3.37 or later. The Python Tyche runs on today has 3.53.3; the Docker image (PR 18) must be checked, because on Linux the SQLite version depends on how Python was built.
- Backups: copy `state/` while Tyche is stopped, or use SQLite's backup command, because a WAL database is more than one file while it is open.
