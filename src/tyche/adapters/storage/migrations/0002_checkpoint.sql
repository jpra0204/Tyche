-- Checkpoints: the state each run hands to the next (ADR-0038).
-- One per run, in the order saved; a restart carries on from the highest number.
-- Append-only, like the journal: the triggers refuse any update or delete.
--
-- A checkpoint belongs to a run whose journal is stored: (run_id, first_seq) must be
-- that run's first envelope, so a run that left no journal cannot leave a checkpoint.

CREATE TABLE checkpoint (
    number    INTEGER PRIMARY KEY,
    run_id    TEXT    NOT NULL UNIQUE CHECK (length(trim(run_id)) > 0),
    first_seq INTEGER NOT NULL DEFAULT 1 CHECK (first_seq = 1),
    saved_at  TEXT    NOT NULL,
    format    INTEGER NOT NULL,
    payload   TEXT    NOT NULL,
    FOREIGN KEY (run_id, first_seq) REFERENCES journal (run_id, seq)
) STRICT;

CREATE TRIGGER checkpoint_no_update BEFORE UPDATE ON checkpoint
BEGIN
    SELECT RAISE(ABORT, 'checkpoints are append-only: rows are never updated');
END;

CREATE TRIGGER checkpoint_no_delete BEFORE DELETE ON checkpoint
BEGIN
    SELECT RAISE(ABORT, 'checkpoints are append-only: rows are never deleted');
END;
