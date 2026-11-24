"""``tyche kill`` and ``tyche resume`` underneath: the flag, the halt and the record (ADR-0039)."""

from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.support import checkpoints
from tests.support.reconciliation import unreconciled
from tests.support.recording import TickingClock
from tyche.adapters.kill_switch import FlagFileKillSwitch
from tyche.adapters.storage import SqliteCheckpointStore, SqliteJournalStore, open_database
from tyche.config.workspace import Workspace, init_workspace
from tyche.core.domain import Checkpoint, Kill
from tyche.core.events import Envelope, ResumeEvent, RunEvent, RunMode, RunStage
from tyche.runtime.kill_switch import (
    KillSwitchError,
    TradingStatus,
    engage_kill,
    resume,
    status,
)

NOW = datetime(2026, 11, 23, 21, 4, tzinfo=UTC)


class Fixed:
    def now(self) -> datetime:
        return NOW


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    (tmp_path / "home").mkdir()
    return init_workspace(tmp_path / "workspace", user_home=tmp_path / "home")


def save(workspace: Workspace, checkpoint: Checkpoint) -> None:
    """Store ``checkpoint`` as a paper run would: its journal first, then its state."""
    started = RunEvent(checkpoint.run_id, RunMode.PAPER, RunStage.STARTED, "0.1.0")
    with closing(open_database(workspace.state_database)) as connection:
        SqliteJournalStore(connection).append(
            checkpoint.run_id, Envelope(1, checkpoint.saved_at, "engine", started)
        )
        SqliteCheckpointStore(connection).save(checkpoint)


def halted() -> Checkpoint:
    return checkpoints.checkpoint()


def running() -> Checkpoint:
    return replace(checkpoints.checkpoint(), rules=checkpoints.rules())


class TestEngage:
    def test_writes_the_flag_with_when_and_why(self, workspace: Workspace) -> None:
        outcome = engage_kill(workspace, "looks wrong", flatten=False, clock=Fixed())

        assert outcome.changed
        assert outcome.status == TradingStatus(Kill("looks wrong", engaged_at=NOW))
        assert FlagFileKillSwitch(workspace.kill_file).read() == outcome.status.kill

    def test_adds_flatten_to_a_switch_already_engaged(self, workspace: Workspace) -> None:
        engage_kill(workspace, "first", flatten=False, clock=Fixed())
        outcome = engage_kill(workspace, "sell it all", flatten=True, clock=Fixed())

        assert outcome.changed
        assert outcome.status.kill == Kill("sell it all", flatten=True, engaged_at=NOW)

    def test_adding_flatten_without_a_reason_keeps_the_first(self, workspace: Workspace) -> None:
        engage_kill(workspace, "looks wrong", flatten=False, clock=Fixed())
        outcome = engage_kill(workspace, flatten=True, clock=Fixed())

        assert outcome.status.kill == Kill("looks wrong", flatten=True, engaged_at=NOW)

    def test_without_a_reason_says_how_it_was_engaged(self, workspace: Workspace) -> None:
        outcome = engage_kill(workspace, flatten=False, clock=Fixed())

        assert outcome.status.kill == Kill("engaged with tyche kill", engaged_at=NOW)

    @pytest.mark.parametrize("again_with_flatten", [False, True])
    def test_never_weakens_a_switch_already_engaged(
        self, workspace: Workspace, again_with_flatten: bool
    ) -> None:
        engage_kill(workspace, "first", flatten=True, clock=Fixed())
        outcome = engage_kill(workspace, "second", flatten=again_with_flatten, clock=Fixed())

        assert not outcome.changed
        assert outcome.status.kill == Kill("first", flatten=True, engaged_at=NOW)

    def test_lists_what_the_last_run_left_working(self, workspace: Workspace) -> None:
        save(workspace, running())

        outcome = engage_kill(workspace, "stop", flatten=False, clock=Fixed())

        assert outcome.status.checkpoint == running()
        assert outcome.status.working == running().execution.orders
        assert outcome.status.halt is None

    def test_a_broken_state_database_does_not_stop_the_flag(self, workspace: Workspace) -> None:
        workspace.state_dir.mkdir()
        workspace.state_database.write_text("not a database")

        outcome = engage_kill(workspace, "stop", flatten=False, clock=Fixed())

        assert outcome.status.kill is not None
        assert outcome.status.unreadable is not None
        assert workspace.kill_file.exists()


class TestResume:
    def test_releases_the_kill_switch_and_records_it(self, workspace: Workspace) -> None:
        save(workspace, running())
        engage_kill(workspace, "stop", flatten=False, clock=Fixed())
        seen = status(workspace)

        outcome = resume(workspace, "all clear", code_version="0.2.0", expected=seen, clock=Fixed())

        assert outcome.released == seen.kill
        assert outcome.lifted is None
        assert not workspace.kill_file.exists()
        with closing(open_database(workspace.state_database)) as connection:
            [envelope] = SqliteJournalStore(connection).read("resume-20261123T210400Z")
            latest = SqliteCheckpointStore(connection).latest()
        assert envelope.event == ResumeEvent("all clear", kill=seen.kill)
        assert latest == running()  # nothing halted, so no new checkpoint

    def test_lifts_the_halt_with_a_new_peak_from_the_next_close(self, workspace: Workspace) -> None:
        save(workspace, halted())
        seen = status(workspace)
        assert seen.halt is not None
        assert seen.kill is None

        outcome = resume(workspace, "recovered", code_version="0.2.0", expected=seen, clock=Fixed())

        assert outcome.lifted == seen.halt
        assert outcome.run_id == "resume-20261123T210400Z"
        with closing(open_database(workspace.state_database)) as connection:
            [envelope] = SqliteJournalStore(connection).read(outcome.run_id)
            latest = SqliteCheckpointStore(connection).latest()
        assert envelope.event == ResumeEvent("recovered", halt=seen.halt, after_run=halted().run_id)
        assert latest == replace(
            halted(),
            run_id=outcome.run_id,
            saved_at=NOW,
            code_version="0.2.0",
            rules=replace(halted().rules, peak=(), halt=None),
        )
        assert status(workspace).halt is None

    def test_lifts_a_reconciliation_halt_applying_the_fill_it_explained(
        self, workspace: Workspace
    ) -> None:
        save(workspace, unreconciled())
        seen = status(workspace)
        assert seen.unreconciled is not None
        assert seen.applies
        assert seen.halt is None

        outcome = resume(
            workspace, "stop hit overnight", code_version="0.2.0", expected=seen, clock=Fixed()
        )

        assert (outcome.unreconciled, outcome.applied) == (seen.unreconciled, True)
        with closing(open_database(workspace.state_database)) as connection:
            [envelope] = SqliteJournalStore(connection).read(outcome.run_id or "")
            latest = SqliteCheckpointStore(connection).latest()
        assert envelope.event == ResumeEvent(
            "stop hit overnight",
            after_run=unreconciled().run_id,
            reconciliation=seen.unreconciled,
            applied=True,
        )
        assert latest is not None
        assert latest.run_id == outcome.run_id
        assert latest.reconciliation.halt is None
        assert [(h.strategy_id, h.quantity) for h in latest.sleeves.holdings] == [
            ("beta", Decimal(4))
        ]
        assert latest.rules == unreconciled().rules  # the drawdown memory is untouched
        assert not status(workspace).stopped

    def test_lifts_both_halts_at_once(self, workspace: Workspace) -> None:
        both = replace(unreconciled(), rules=checkpoints.rules(halted=True))
        save(workspace, both)
        seen = status(workspace)

        outcome = resume(workspace, "all clear", code_version="0.2.0", expected=seen, clock=Fixed())

        assert outcome.lifted is not None
        assert outcome.unreconciled is not None
        assert not status(workspace).stopped

    def test_without_a_state_database_only_removes_the_flag(self, workspace: Workspace) -> None:
        engage_kill(workspace, "stop", flatten=True, clock=Fixed())

        outcome = resume(
            workspace, "ok", code_version="0.2.0", expected=status(workspace), clock=Fixed()
        )

        assert outcome.run_id is None
        assert not workspace.kill_file.exists()
        assert not workspace.state_database.exists()

    def test_refuses_when_there_is_nothing_to_lift(self, workspace: Workspace) -> None:
        with pytest.raises(KillSwitchError, match="nothing to resume"):
            resume(workspace, "ok", code_version="0.2.0", expected=status(workspace))

    def test_refuses_when_things_changed_since_confirming(self, workspace: Workspace) -> None:
        engage_kill(workspace, "stop", flatten=False, clock=Fixed())
        seen = status(workspace)
        engage_kill(workspace, "sell", flatten=True, clock=Fixed())

        with pytest.raises(KillSwitchError, match="changed since you confirmed"):
            resume(workspace, "ok", code_version="0.2.0", expected=seen, clock=Fixed())
        assert workspace.kill_file.exists()

    def test_keeps_the_flag_and_writes_nothing_when_the_clock_is_behind(
        self, workspace: Workspace
    ) -> None:
        later = replace(halted(), saved_at=datetime(2030, 1, 1, tzinfo=UTC))
        save(workspace, later)  # taken after "now": the store refuses an earlier one
        engage_kill(workspace, "stop", flatten=False, clock=Fixed())
        seen = status(workspace)

        with pytest.raises(KillSwitchError, match="check this machine's clock"):
            resume(workspace, "ok", code_version="0.2.0", expected=seen, clock=Fixed())
        assert workspace.kill_file.exists()
        assert status(workspace).halt is not None
        with closing(open_database(workspace.state_database)) as connection:
            assert SqliteJournalStore(connection).run_ids() == (later.run_id,)

    def test_two_resumes_in_one_second_are_refused(self, workspace: Workspace) -> None:
        save(workspace, halted())
        resume(workspace, "ok", code_version="0.2.0", expected=status(workspace), clock=Fixed())
        engage_kill(workspace, "again", flatten=False, clock=Fixed())

        with pytest.raises(KillSwitchError, match="refused the resume"):
            resume(workspace, "ok", code_version="0.2.0", expected=status(workspace), clock=Fixed())
        assert workspace.kill_file.exists()

    def test_refuses_when_the_state_database_cannot_be_read(self, workspace: Workspace) -> None:
        engage_kill(workspace, "stop", flatten=False, clock=TickingClock())
        workspace.state_dir.mkdir()
        workspace.state_database.write_text("not a database")
        seen = status(workspace)

        with pytest.raises(KillSwitchError, match="cannot be ruled out"):
            resume(workspace, "ok", code_version="0.2.0", expected=seen)
        assert workspace.kill_file.exists()
