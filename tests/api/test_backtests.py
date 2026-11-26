"""The Backtests and Data pages' reads (ADR-0046, console U2)."""

from pathlib import Path

import pytest

from tests.api.test_app import TOKEN, client
from tests.runtime.test_backtest import backtest
from tests.runtime.test_backtest import config as config  # the fixture: SPY and QQQ cached
from tyche.api import create_app
from tyche.config import TycheConfig, Workspace, init_workspace
from tyche.runtime.report import write_report


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


class TestBacktests:
    def test_none_yet(self, workspace: Workspace) -> None:
        body = client(create_app(workspace, TOKEN, environ={})).get("/api/backtests").json()

        assert body == []

    def test_a_recorded_backtest_with_its_numbers(self, config: TycheConfig) -> None:
        outcome = backtest(config)
        write_report(outcome.record_dir)

        listed = client(create_app(config.workspace, TOKEN, environ={})).get("/api/backtests")

        [summary] = listed.json()
        assert summary["run_id"] == outcome.record_dir.name
        assert summary["first"] == "2023-11-01"
        assert summary["last"] == "2023-12-29"
        assert summary["risk_profile"] == "default"
        assert summary["currency"] == "USD"
        assert summary["completed"] is True
        assert summary["halted"] is False
        assert summary["benchmark"] == "SPY@ARCX"
        assert summary["total_return"] is not None
        assert summary["has_report"] is True
        assert summary["error"] is None

    def test_newest_first_and_a_broken_record_is_listed_with_why(
        self, workspace: Workspace
    ) -> None:
        folder = workspace.reports_dir / "backtests"
        (folder / "20240101T000000Z-aaaaaaaa").mkdir(parents=True)
        (folder / "20240101T000000Z-aaaaaaaa" / "run.json").write_text("{not json")
        (folder / "20240102T000000Z-bbbbbbbb").mkdir()

        body = client(create_app(workspace, TOKEN, environ={})).get("/api/backtests").json()

        assert [s["run_id"] for s in body] == [
            "20240102T000000Z-bbbbbbbb",
            "20240101T000000Z-aaaaaaaa",
        ]
        assert all("run.json unreadable" in s["error"] for s in body)

    def test_the_report(self, config: TycheConfig) -> None:
        outcome = backtest(config)
        write_report(outcome.record_dir)
        test_client = client(create_app(config.workspace, TOKEN, environ={}))

        response = test_client.get(f"/api/backtests/{outcome.record_dir.name}/report")

        assert response.status_code == 200
        assert response.text == (outcome.record_dir / "report.html").read_text()
        assert response.headers["content-security-policy"] == "sandbox"

    def test_a_record_without_a_report_says_so(self, config: TycheConfig) -> None:
        outcome = backtest(config)
        (outcome.record_dir / "report.html").unlink(missing_ok=True)
        test_client = client(create_app(config.workspace, TOKEN, environ={}))

        response = test_client.get(f"/api/backtests/{outcome.record_dir.name}/report")

        assert response.status_code == 404
        assert "no report yet" in response.json()["detail"]

    @pytest.mark.parametrize(
        ("run_id", "status"),
        [
            ("20240101T000000Z-cccccccc", 404),  # no such record
            ("not-a-run-id", 422),  # not a run id at all
            ("..", 404),  # the URL collapses it: no route matches
        ],
    )
    def test_an_unknown_record_is_not_found(
        self, workspace: Workspace, run_id: str, status: int
    ) -> None:
        test_client = client(create_app(workspace, TOKEN, environ={}))

        response = test_client.get(f"/api/backtests/{run_id}/report")

        assert response.status_code == status

    def test_needs_the_token(self, workspace: Workspace) -> None:
        test_client = client(create_app(workspace, TOKEN, environ={}), token=None)

        assert test_client.get("/api/backtests").status_code == 401


class TestData:
    def test_the_exchanges_and_what_all_fetches(self, workspace: Workspace) -> None:
        body = client(create_app(workspace, TOKEN, environ={})).get("/api/data").json()

        assert {"mic": "ARCX", "name": "NYSE Arca"} in body["exchanges"]
        assert body["default_first"] == "2000-01-01"
        assert "SPY@ARCX" in body["followed"]
        assert body["error"] is None

    def test_an_invalid_config_says_why(self, workspace: Workspace) -> None:
        (workspace.root / "config" / "guardrails.toml").write_text("long_only = 3\n")

        body = client(create_app(workspace, TOKEN, environ={})).get("/api/data").json()

        assert body["followed"] == []
        assert "guardrails.toml" in body["error"]
