-- The broker adapter's own memory of the orders it sent (ADR-0042).
--
-- A row is written and committed BEFORE the order goes to the broker, so a crash or a
-- lost connection never leaves an order Tyche sent but has no record of. `fate` says
-- what Tyche knows about it:
--   sending  written, sent or about to be, and not yet confirmed by the broker
--   placed   the broker gave it an order id, or listed it after a reconnection
--   lost     not listed by the broker after a reconnection; never resent
-- `state` is the latest OrderState Tyche published for it, as the codec writes it.
-- Rows change as the order moves, unlike the journal, which records every change.

CREATE TABLE broker_order (
    client_order_id  TEXT    PRIMARY KEY CHECK (length(trim(client_order_id)) > 0),
    sent_at          TEXT    NOT NULL,
    fate             TEXT    NOT NULL CHECK (fate IN ('sending', 'placed', 'lost')),
    order_id         INTEGER CHECK (order_id IS NULL OR order_id > 0),
    perm_id          INTEGER CHECK (perm_id IS NULL OR perm_id > 0),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    format           INTEGER NOT NULL,
    state            TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL
) STRICT;

-- Every execution already published as a fill, so the same day's executions, read
-- again by the next run, are never applied twice. Append-only.

CREATE TABLE broker_fill (
    exec_id         TEXT PRIMARY KEY CHECK (length(trim(exec_id)) > 0),
    client_order_id TEXT NOT NULL REFERENCES broker_order (client_order_id),
    published_at    TEXT NOT NULL
) STRICT;

CREATE TRIGGER broker_fill_no_update BEFORE UPDATE ON broker_fill
BEGIN
    SELECT RAISE(ABORT, 'broker fills are append-only: rows are never updated');
END;

CREATE TRIGGER broker_fill_no_delete BEFORE DELETE ON broker_fill
BEGIN
    SELECT RAISE(ABORT, 'broker fills are append-only: rows are never deleted');
END;
