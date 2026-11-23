"""The kill switch and the manual restart: what ``tyche kill`` and ``tyche resume`` do.

``tyche kill`` writes the ``KILL`` flag file (ADR-0039). The risk gate reads it at every
decision of a paper or live run: from the next decision on, nothing new is bought, and
with flatten every holding is sold. It never reaches the broker itself: orders the last
run left working are listed, for Pablo to cancel in IBKR's own app if he wants them gone.

``tyche resume`` is the manual restart. It lifts both things that stop trading: the
kill switch (the flag file) and the drawdown halt (in the latest checkpoint, ADR-0038).
A halt is lifted by a short run of its own in the state database: one ``ResumeEvent`` in
the journal, then a checkpoint with the latest one's state, the halt lifted and the peak
forgotten, so the drawdown kill counts from the first close after the restart.

Neither command may run while a paper run is running; nothing enforces that yet (the
scheduler, Phase 2 PR 15, will).
"""

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime

from tyche.adapters.clocks import SystemClock
from tyche.adapters.kill_switch import FlagFileKillSwitch, engage, release
from tyche.adapters.storage import (
    SqliteCheckpointStore,
    SqliteJournalStore,
    StateDatabaseError,
    open_database,
)
from tyche.config.workspace import Workspace
from tyche.core.domain import AccountTrigger, Checkpoint, Kill, WorkingOrder
from tyche.core.events import Envelope, ResumeEvent
from tyche.core.ports import CheckpointStoreError, Clock, JournalStoreError

SOURCE = "cli"
"""The ``source`` of the envelope a resume journals: Pablo, at the command line."""

DEFAULT_REASON = "engaged with tyche kill"
"""The reason recorded when ``tyche kill`` is given none."""


class KillSwitchError(Exception):
    """The kill switch or the halt could not be changed as asked."""


@dataclass(frozen=True, slots=True)
class TradingStatus:
    """What stops trading now, and what the last run left at the broker.

    Attributes:
        kill: The kill switch, or ``None`` if it is not engaged.
        checkpoint: The latest checkpoint, or ``None`` if no paper or live run has
            saved one, or the state database could not be read.
        unreadable: Why the state database could not be read, or ``None``.
    """

    kill: Kill | None
    checkpoint: Checkpoint | None = None
    unreadable: str | None = None

    @property
    def halt(self) -> AccountTrigger | None:
        """The drawdown halt the latest checkpoint carries, or ``None``."""
        return self.checkpoint.rules.halt if self.checkpoint is not None else None

    @property
    def working(self) -> tuple[WorkingOrder, ...]:
        """The orders the last run left working at the broker, stops included."""
        return self.checkpoint.execution.orders if self.checkpoint is not None else ()


@dataclass(frozen=True, slots=True)
class KillOutcome:
    """What ``engage_kill`` did.

    Attributes:
        status: Trading's status after it, with the switch as it now stands.
        changed: False when the switch was already engaged as asked, or with flatten,
            and was left as it was.
    """

    status: TradingStatus
    changed: bool


@dataclass(frozen=True, slots=True)
class ResumeOutcome:
    """What ``resume`` lifted.

    Attributes:
        released: The kill switch released, or ``None``.
        lifted: The drawdown halt lifted, or ``None``.
        run_id: The resume's own run in the state database, or ``None`` when there is
            no state database to record it in.
    """

    released: Kill | None
    lifted: AccountTrigger | None
    run_id: str | None


def status(workspace: Workspace) -> TradingStatus:
    """Read the kill switch and the latest checkpoint. Changes nothing but the schema.

    Opening the state database brings its schema up to date, as every command that
    opens it does. It is opened only if it exists. If it cannot be read, the kill switch
    is still reported, with the reason.
    """
    kill = FlagFileKillSwitch(workspace.kill_file).read()
    if not workspace.state_database.exists():
        return TradingStatus(kill)
    try:
        connection = open_database(workspace.state_database)
    except (StateDatabaseError, sqlite3.Error, OSError) as error:
        return TradingStatus(kill, unreadable=str(error))
    try:
        checkpoint = SqliteCheckpointStore(connection).latest()
    except (CheckpointStoreError, sqlite3.Error) as error:
        return TradingStatus(kill, unreadable=str(error))
    finally:
        connection.close()
    return TradingStatus(kill, checkpoint)


def engage_kill(
    workspace: Workspace,
    reason: str | None = None,
    *,
    flatten: bool,
    clock: Clock | None = None,
) -> KillOutcome:
    """Engage the kill switch, or add flatten to one already engaged.

    The flag is written before anything else is read, so a broken state database can
    never delay it. A switch already engaged is never weakened: asking again without
    flatten leaves a flattening switch as it is; only ``resume`` releases it. Adding
    flatten without a new ``reason`` keeps the reason already given.
    """
    switch = FlagFileKillSwitch(workspace.kill_file)
    before = switch.read()
    changed = before is None or (flatten and not before.flatten)
    if changed:
        now = (clock or SystemClock()).now()
        given = reason or (before.reason if before is not None else DEFAULT_REASON)
        engage(workspace.kill_file, Kill(given, flatten=flatten, engaged_at=now))
    return KillOutcome(status(workspace), changed)


def resume(
    workspace: Workspace,
    reason: str,
    *,
    code_version: str,
    expected: TradingStatus,
    clock: Clock | None = None,
) -> ResumeOutcome:
    """Lift the kill switch and the drawdown halt: the manual restart (ADR-0039).

    ``expected`` is the status Pablo confirmed. If the kill switch or the latest
    checkpoint has changed since, nothing is lifted: he must see what he is lifting.

    The halt is lifted first, in the state database; the flag file is removed last. If
    anything fails on the way, the flag stays and trading stays stopped.

    Raises:
        KillSwitchError: Nothing to lift, the status changed since it was confirmed, or
            the state database refused the resume.
    """
    current = status(workspace)
    if current != expected:
        raise KillSwitchError(
            "the kill switch or the latest checkpoint changed since you confirmed; run "
            "tyche resume again to see what it would lift"
        )
    if current.unreadable is not None:
        raise KillSwitchError(
            f"the state database cannot be read, so a drawdown halt cannot be ruled out: "
            f"{current.unreadable}"
        )
    if current.kill is None and current.halt is None:
        raise KillSwitchError("nothing to resume: the kill switch is off and trading is not halted")

    run_id = None
    now = (clock or SystemClock()).now()
    if workspace.state_database.exists():
        run_id = f"resume-{now:%Y%m%dT%H%M%SZ}"
        _record(workspace, run_id, reason, current, now, code_version)
    release(workspace.kill_file)
    return ResumeOutcome(current.kill, current.halt, run_id)


def _record(
    workspace: Workspace,
    run_id: str,
    reason: str,
    current: TradingStatus,
    now: datetime,
    code_version: str,
) -> None:
    """Journal the resume as a run of its own; with a halt, save the lifted checkpoint.

    The journal and the checkpoint commit one after the other, so everything the store
    would refuse is checked first: a journaled resume always took effect.
    """
    latest = current.checkpoint
    if latest is not None and current.halt is not None and now <= latest.saved_at:
        raise KillSwitchError(
            f"the latest checkpoint was taken at {latest.saved_at.isoformat()}, not before "
            f"now ({now.isoformat()}); check this machine's clock"
        )
    event = ResumeEvent(
        reason,
        kill=current.kill,
        halt=current.halt,
        after_run=latest.run_id if latest is not None and current.halt is not None else None,
    )
    try:
        connection = open_database(workspace.state_database)
    except (StateDatabaseError, sqlite3.Error, OSError) as error:
        raise KillSwitchError(f"the state database cannot be opened: {error}") from error
    try:
        SqliteJournalStore(connection).append(run_id, Envelope(1, now, SOURCE, event))
        if latest is not None and current.halt is not None:
            lifted = replace(
                latest,
                run_id=run_id,
                saved_at=now,
                code_version=code_version,
                rules=latest.rules.resumed(),
            )
            SqliteCheckpointStore(connection).save(lifted)
    except (JournalStoreError, CheckpointStoreError, sqlite3.Error) as error:
        raise KillSwitchError(f"the state database refused the resume: {error}") from error
    finally:
        connection.close()
