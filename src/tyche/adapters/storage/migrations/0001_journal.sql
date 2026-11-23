-- The journal: every event of every run, in order, with its cause (ADR-0009, ADR-0037).
-- Append-only: the triggers refuse any update or delete.

CREATE TABLE journal (
    run_id      TEXT    NOT NULL CHECK (length(trim(run_id)) > 0),
    seq         INTEGER NOT NULL CHECK (seq >= 1),
    occurred_at TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    caused_by   INTEGER CHECK (caused_by IS NULL OR (caused_by >= 1 AND caused_by < seq)),
    cycle_id    TEXT,
    format      INTEGER NOT NULL,
    payload     TEXT    NOT NULL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id, caused_by) REFERENCES journal (run_id, seq)
) STRICT;

CREATE INDEX journal_by_type ON journal (run_id, event_type);

CREATE TRIGGER journal_no_update BEFORE UPDATE ON journal
BEGIN
    SELECT RAISE(ABORT, 'the journal is append-only: rows are never updated');
END;

CREATE TRIGGER journal_no_delete BEFORE DELETE ON journal
BEGIN
    SELECT RAISE(ABORT, 'the journal is append-only: rows are never deleted');
END;
