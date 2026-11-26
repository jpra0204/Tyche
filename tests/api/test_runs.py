"""Running ``tyche`` from the page (ADR-0046, console U2).

Most tests start a stand-in program that prints what it was given, so they check the
runner alone: the arguments, both streams, the exit code, one run at a time. The last
ones start the real ``tyche backtest`` on a workspace with a cache, end to end.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.api.test_app import TOKEN, client
from tests.runtime.test_backtest import CACHED_FROM, LAST
from tests.runtime.test_backtest import config as config  # the fixture: SPY and QQQ cached
from tyche.api import create_app
from tyche.api.models import BacktestRequest, FetchRequest, ReportRequest
from tyche.api.runs import arguments
from tyche.config import TycheConfig, Workspace, init_workspace

# Prints its arguments, one line to the error stream, and exits with the code after
# `--exit` if given. With GATE set, waits until that file exists (at most 20 s).
STAND_IN = """
import os, pathlib, sys, time
gate = os.environ.get("GATE")
if gate:
    deadline = time.monotonic() + 20
    while not pathlib.Path(gate).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
args = sys.argv[1:]
print("args:", " ".join(args))
print("a warning", file=sys.stderr)
print("done")
sys.exit(int(args[args.index("--exit") + 1]) if "--exit" in args else 0)
"""
PROGRAM = (sys.executable, "-c", STAND_IN)

BACKTEST: dict[str, Any] = {"command": "backtest", "first": "2005-01-03"}


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def console(
    workspace: Workspace, environ: dict[str, str] | None = None, program: Any = PROGRAM
) -> FastAPI:
    return create_app(workspace, TOKEN, environ=environ or {}, program=program)


def finished(test_client: TestClient, timeout: float = 60) -> dict[str, Any]:
    """The current run once it has ended."""
    runner_wait = test_client.app.state.runner.wait  # type: ignore[attr-defined]
    runner_wait(timeout)
    body: dict[str, Any] = test_client.get("/api/runs/current").json()
    assert body["state"] != "running"
    return body


class TestArguments:
    def test_fetch_everything_the_profile_follows(self) -> None:
        request = FetchRequest(command="data_fetch", every_candidate=True)

        assert arguments(request) == ["data", "fetch", "--all"]

    def test_fetch_symbols_with_every_option(self) -> None:
        request = FetchRequest(
            command="data_fetch",
            symbols=["SPY", "BRK.B"],
            exchange="ARCX",
            asset_class="stock",
            first=date(2005, 1, 3),
            last=date(2023, 12, 29),
        )

        assert arguments(request) == [
            "data",
            "fetch",
            "SPY",
            "BRK.B",
            "--exchange",
            "ARCX",
            "--asset-class",
            "stock",
            "--from",
            "2005-01-03",
            "--to",
            "2023-12-29",
        ]

    def test_backtest(self) -> None:
        request = BacktestRequest(
            command="backtest", first=date(2005, 1, 3), last=None, risk_profile="stage-1"
        )

        assert arguments(request) == [
            "backtest",
            "--from",
            "2005-01-03",
            "--risk-profile",
            "stage-1",
        ]

    def test_report(self) -> None:
        request = ReportRequest(command="report", run_id="20240105T120000Z-0123abcd")

        assert arguments(request) == ["report", "20240105T120000Z-0123abcd"]


class TestStartingARun:
    def test_needs_the_token(self, workspace: Workspace) -> None:
        response = client(console(workspace), token=None).post("/api/runs", json=BACKTEST)

        assert response.status_code == 401

    def test_there_is_no_run_before_the_first(self, workspace: Workspace) -> None:
        response = client(console(workspace)).get("/api/runs/current")

        assert response.status_code == 200
        assert response.json() is None

    def test_runs_the_command_in_the_console_s_workspace(self, workspace: Workspace) -> None:
        test_client = client(console(workspace))

        started = test_client.post("/api/runs", json=BACKTEST)

        assert started.status_code == 201
        assert started.json()["argv"] == [
            "tyche",
            "backtest",
            "--from",
            "2005-01-03",
            "--risk-profile",
            "default",
        ]
        run = finished(test_client)
        assert run["state"] == "succeeded"
        assert run["exit_code"] == 0
        assert run["number"] == 1
        assert run["finished_at"] is not None
        out = [line["text"] for line in run["lines"] if line["stream"] == "out"]
        assert out == [
            f"args: backtest --from 2005-01-03 --risk-profile default --home {workspace.root}",
            "done",
        ]
        assert {"stream": "err", "text": "a warning"} in run["lines"]

    def test_a_command_that_fails_is_failed(self, workspace: Workspace) -> None:
        # No request can carry "--exit": it goes in the stand-in's own command line.
        program = (*PROGRAM, "--exit", "1")
        test_client = client(console(workspace, program=program))

        test_client.post("/api/runs", json=BACKTEST)

        run = finished(test_client)
        assert run["state"] == "failed"
        assert run["exit_code"] == 1

    def test_one_run_at_a_time(self, workspace: Workspace, tmp_path: Path) -> None:
        gate = tmp_path / "gate"
        test_client = client(console(workspace, environ={"GATE": str(gate)}))
        assert test_client.post("/api/runs", json=BACKTEST).status_code == 201

        second = test_client.post("/api/runs", json=BACKTEST)

        assert second.status_code == 409
        assert "still running" in second.json()["detail"]
        assert test_client.get("/api/runs/current").json()["state"] == "running"
        gate.touch()
        assert finished(test_client)["state"] == "succeeded"
        assert test_client.post("/api/runs", json=BACKTEST).status_code == 201
        assert finished(test_client)["number"] == 2

    def test_the_command_gets_the_console_s_environment(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        program = (
            sys.executable,
            "-c",
            "import os; print(os.environ.get('MARK'), os.environ.get('PYTHONUNBUFFERED'))",
        )
        test_client = client(console(workspace, environ={"MARK": "here"}, program=program))

        test_client.post("/api/runs", json=BACKTEST)

        assert finished(test_client)["lines"] == [{"stream": "out", "text": "here 1"}]


class TestOnlyWhatACommandOffers:
    @pytest.mark.parametrize(
        "request_body",
        [
            pytest.param({"command": "paper_run"}, id="a command the page does not run"),
            pytest.param({"command": "kill", "reason": "x"}, id="kill"),
            pytest.param({"command": "backtest"}, id="a backtest with no first day"),
            pytest.param({**BACKTEST, "risk_profile": "--help"}, id="a profile that is an option"),
            pytest.param(
                {"command": "data_fetch", "symbols": ["--all"], "exchange": "ARCX"},
                id="a symbol that is an option",
            ),
            pytest.param(
                {"command": "data_fetch", "symbols": ["SPY"], "exchange": "arcx; ls"},
                id="an exchange that is not a code",
            ),
            pytest.param({"command": "report", "run_id": "../../x"}, id="a path as a run id"),
            pytest.param({**BACKTEST, "home": "/elsewhere"}, id="another workspace"),
        ],
    )
    def test_anything_else_is_refused_before_a_process_starts(
        self, workspace: Workspace, request_body: dict[str, Any]
    ) -> None:
        test_client = client(console(workspace))

        response = test_client.post("/api/runs", json=request_body)

        assert response.status_code == 422
        assert test_client.get("/api/runs/current").json() is None


class TestTheRealCommand:
    """The real `tyche`, as a subprocess, on a workspace whose cache holds SPY and QQQ."""

    def test_a_backtest_is_recorded_and_listed_with_its_report(self, config: TycheConfig) -> None:
        workspace = config.workspace
        test_client = client(create_app(workspace, TOKEN, environ={}))

        test_client.post(
            "/api/runs",
            json={"command": "backtest", "first": "2023-11-01", "last": LAST.isoformat()},
        )

        run = finished(test_client, timeout=120)
        assert run["state"] == "succeeded", run["lines"]
        listed = test_client.get("/api/backtests").json()
        assert len(listed) == 1
        assert listed[0]["first"] == "2023-11-01"
        assert listed[0]["has_report"] is True
        report = test_client.get(f"/api/backtests/{listed[0]['run_id']}/report")
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/html")
        assert any(listed[0]["run_id"] in line["text"] for line in run["lines"])

    def test_the_command_s_own_checks_still_apply(self, config: TycheConfig) -> None:
        # Before the cache's first session: the CLI refuses, the page shows why.
        test_client = client(create_app(config.workspace, TOKEN, environ={}))

        test_client.post(
            "/api/runs",
            json={"command": "backtest", "first": "2001-01-02", "last": CACHED_FROM.isoformat()},
        )

        run = finished(test_client, timeout=120)
        assert run["state"] == "failed"
        assert run["exit_code"] == 1
        errors = [line["text"] for line in run["lines"] if line["stream"] == "err"]
        assert any(text.startswith("Error:") for text in errors)
        assert test_client.get("/api/backtests").json() == []
