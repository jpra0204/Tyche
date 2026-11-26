"""The Paper page (ADR-0046, console U3): the paper cycle, the kill switch and resume
started from the page, the last cycle's reconciliations, and the alerts.

`tyche paper run` itself is never started here: it connects to IB Gateway. Its tests
use the stand-in program. `tyche kill` and `tyche resume` run for real, on a scratch
workspace with no `.env` and an empty environment, so nothing can be posted.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.api.test_app import TOKEN, client
from tests.api.test_runs import PROGRAM, console, finished
from tests.runtime.test_notify import FakeNotifier
from tests.support.reconciliation import mismatch
from tyche.adapters.logs import close_logging, configure_logging
from tyche.adapters.storage import SqliteJournalStore, open_database
from tyche.api import create_app
from tyche.api.models import KillRequest, PaperRunRequest, ResumeRequest
from tyche.api.runs import arguments
from tyche.config import Workspace, init_workspace
from tyche.core.domain import Reconciliation
from tyche.core.events import Envelope, ReconciliationEvent
from tyche.core.ports import Alert, AlertKind
from tyche.runtime.notify import deliver

AT = datetime(2026, 11, 25, 21, 30, tzinfo=UTC)
PAPER: dict[str, Any] = {"command": "paper_run", "confirmed": True}
KILL: dict[str, Any] = {"command": "kill", "reason": "looks wrong", "confirmed": True}
RESUME: dict[str, Any] = {"command": "resume", "reason": "checked it", "confirmed": True}


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


@pytest.fixture
def logs(workspace: Workspace) -> Iterator[Path]:
    configure_logging(workspace.logs_dir)
    yield workspace.logs_dir
    close_logging()


def store(workspace: Workspace, run_id: str, *found: Reconciliation) -> None:
    connection = open_database(workspace.state_database)
    try:
        journal = SqliteJournalStore(connection)
        for seq, reconciliation in enumerate(found, start=1):
            event = ReconciliationEvent(reconciliation=reconciliation)
            journal.append(run_id, Envelope(seq, reconciliation.at, "test", event))
    finally:
        connection.close()


class TestArguments:
    def test_the_paper_cycle(self) -> None:
        request = PaperRunRequest(command="paper_run", risk_profile="stage-1", confirmed=True)

        assert arguments(request) == ["paper", "run", "--risk-profile", "stage-1"]

    def test_kill_says_yes_because_the_page_asked(self) -> None:
        request = KillRequest(command="kill", reason="looks wrong", flatten=True, confirmed=True)

        assert arguments(request) == ["kill", "--reason=looks wrong", "--flatten", "--yes"]

    def test_a_reason_that_looks_like_an_option_stays_a_reason(self) -> None:
        request = ResumeRequest(command="resume", reason="--flatten", confirmed=True)

        assert arguments(request) == ["resume", "--reason=--flatten", "--yes"]


class TestConfirmation:
    @pytest.mark.parametrize(
        "request_body",
        [
            pytest.param({"command": "paper_run"}, id="paper run, not confirmed"),
            pytest.param({**PAPER, "confirmed": False}, id="paper run, confirmed false"),
            pytest.param({**KILL, "confirmed": False}, id="kill, confirmed false"),
            pytest.param({"command": "resume", "reason": "x"}, id="resume, not confirmed"),
            pytest.param({**KILL, "reason": "   "}, id="a blank reason"),
            pytest.param({**KILL, "reason": "one\ntwo"}, id="a reason on two lines"),
            pytest.param({**KILL, "reason": "x" * 301}, id="a reason too long"),
            pytest.param({**PAPER, "risk_profile": "--help"}, id="a profile that is an option"),
            pytest.param({**PAPER, "live": True}, id="a field the command does not have"),
        ],
    )
    def test_is_required_and_nothing_starts_without_it(
        self, workspace: Workspace, request_body: dict[str, Any]
    ) -> None:
        test_client = client(console(workspace))

        response = test_client.post("/api/runs", json=request_body)

        assert response.status_code == 422
        assert test_client.get("/api/runs/current").json() is None


class TestRunning:
    def test_the_paper_cycle_runs_the_cli_command(self, workspace: Workspace) -> None:
        # The stand-in: `tyche paper run` itself would connect to IB Gateway.
        test_client = client(console(workspace, program=PROGRAM))

        started = test_client.post("/api/runs", json={**PAPER, "risk_profile": "stage-1"})

        assert started.status_code == 201
        assert started.json()["command"] == "paper_run"
        run = finished(test_client)
        assert run["lines"][0]["text"] == (
            f"args: paper run --risk-profile stage-1 --home {workspace.root}"
        )

    def test_kill_then_resume_for_real(self, workspace: Workspace) -> None:
        test_client = client(create_app(workspace, TOKEN, environ={}))

        test_client.post("/api/runs", json={**KILL, "flatten": True})

        killed = finished(test_client, timeout=120)
        assert killed["state"] == "succeeded", killed["lines"]
        trading = test_client.get("/api/status").json()["trading"]
        assert trading["kill"]["reason"] == "looks wrong"
        assert trading["kill"]["flatten"] is True

        test_client.post("/api/runs", json=RESUME)

        resumed = finished(test_client, timeout=120)
        assert resumed["state"] == "succeeded", resumed["lines"]
        assert any("Lifted the kill switch" in line["text"] for line in resumed["lines"])
        assert test_client.get("/api/status").json()["trading"]["stopped"] is False


class TestReconciliations:
    def test_none_before_the_first_cycle(self, workspace: Workspace) -> None:
        body = client(create_app(workspace, TOKEN, environ={})).get("/api/paper").json()

        assert body == {
            "last_cycle": None,
            "reconciliations": [],
            "alerts": [],
            "state_unreadable": None,
        }

    def test_the_last_cycle_s_check_and_decision(self, workspace: Workspace) -> None:
        store(workspace, "paper-20261124T213000Z-check", Reconciliation(at=AT.replace(day=24)))
        store(workspace, "paper-20261125T213000Z-check", Reconciliation(at=AT))
        store(workspace, "paper-20261125T213000Z", mismatch(AT.replace(minute=45)))

        body = client(create_app(workspace, TOKEN, environ={})).get("/api/paper").json()

        assert body["last_cycle"] == "paper-20261125T213000Z-check"
        [check, decision] = body["reconciliations"]
        assert check["stage"] == "check"
        assert check["status"] == "match"
        assert decision["stage"] == "decision"
        assert decision["run_id"] == "paper-20261125T213000Z"
        assert decision["status"] == "mismatch"
        assert decision["differences"] == [
            {"kind": "position", "subject": "SPY.ARCX", "detail": "Tyche holds 10, the broker 4"}
        ]

    def test_a_cycle_with_no_decision_has_only_its_check(self, workspace: Workspace) -> None:
        store(workspace, "paper-20261125T213000Z-check", Reconciliation(at=AT))
        store(workspace, "resume-20261125T220000Z", Reconciliation(at=AT.replace(hour=22)))

        body = client(create_app(workspace, TOKEN, environ={})).get("/api/paper").json()

        assert [r["stage"] for r in body["reconciliations"]] == ["check"]

    def test_an_unreadable_state_database_says_why(self, workspace: Workspace) -> None:
        workspace.state_database.parent.mkdir(parents=True, exist_ok=True)
        workspace.state_database.write_bytes(b"not a database")

        body = client(create_app(workspace, TOKEN, environ={})).get("/api/paper").json()

        assert body["state_unreadable"]
        assert body["reconciliations"] == []


class TestAlerts:
    def test_as_the_logs_recorded_them_newest_first(self, workspace: Workspace, logs: Path) -> None:
        older = Alert(AlertKind.KILL_SWITCH, "Kill switch engaged", AT, ("reason: x",))
        newer = Alert(AlertKind.RECONCILIATION, "Reconciliation mismatch", AT, ("SPY",))
        failing = Alert(AlertKind.RECONCILIATION, "Not delivered", AT)
        deliver(None, [older])
        deliver(FakeNotifier("Not delivered"), [newer, failing])
        close_logging()

        alerts = client(create_app(workspace, TOKEN, environ={})).get("/api/paper").json()["alerts"]

        assert [(a["title"], a["delivery"]) for a in alerts] == [
            ("Not delivered", "not_sent"),
            ("Reconciliation mismatch", "sent"),
            ("Kill switch engaged", "no_channel"),
        ]
        assert alerts[0]["error"] == "could not send Not delivered"
        assert alerts[2]["kind"] == "kill_switch"
        assert alerts[2]["lines"] == ["reason: x"]

    def test_other_log_lines_and_broken_ones_are_skipped(
        self, workspace: Workspace, logs: Path
    ) -> None:
        deliver(None, [Alert(AlertKind.KILL_SWITCH, "Kill switch engaged", AT)])
        close_logging()
        [path] = logs.glob("*.jsonl")
        with path.open("a", encoding="utf-8") as file:
            file.write("{not json\n")
            file.write('{"message": "backtest done", "at": "2026-11-25T00:00:00Z"}\n')

        alerts = client(create_app(workspace, TOKEN, environ={})).get("/api/paper").json()["alerts"]

        assert [a["title"] for a in alerts] == ["Kill switch engaged"]


def journal_rows(workspace: Workspace) -> int:
    with closing(sqlite3.connect(workspace.state_database)) as connection:
        (count,) = connection.execute("SELECT count(*) FROM journal").fetchone()
        return int(count)


def test_reading_writes_nothing_but_the_schema(workspace: Workspace) -> None:
    store(workspace, "paper-20261125T213000Z-check", Reconciliation(at=AT))
    before = journal_rows(workspace)

    client(create_app(workspace, TOKEN, environ={})).get("/api/paper")

    assert journal_rows(workspace) == before
