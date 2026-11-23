"""The state database's migrations: numbered SQL files, applied in order (ADR-0037).

Each file is named ``NNNN_short_name.sql``, numbered from ``0001`` with no gaps. The
database records the last one applied in ``PRAGMA user_version``. A file runs once, in
one transaction with its version bump, so it is applied whole or not at all.

Rules for a new file:

* Never edit or renumber a file that has been merged: a workspace may already have run
  it. Change the schema with a new file instead.
* No ``BEGIN``, ``COMMIT`` or ``PRAGMA`` statements: the runner owns the transaction
  and the version.
* Migrations only go forward. To undo a change, write a new migration.
"""
