"""The console's API (ADR-0046): the lock, the Status data, and serving the page."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.runtime.test_kill_switch import halted, running, save
from tests.support.reconciliation import unreconciled
from tyche.adapters.kill_switch import engage
from tyche.api import TOKEN_HEADER, create_app
from tyche.api.schema import render
from tyche.config import Workspace, init_workspace
from tyche.core.domain import Kill

TOKEN = "test-token"
WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/secret-token"
SCHEMA_FILE = Path(__file__).resolve().parents[2] / "ui" / "src" / "api" / "openapi.json"


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def client(app: FastAPI, *, token: str | None = TOKEN) -> TestClient:
    headers = {TOKEN_HEADER: token} if token is not None else {}
    return TestClient(app, base_url="http://127.0.0.1:8765", headers=headers)


def console(workspace: Workspace, app_dir: Path | None = None) -> FastAPI:
    return create_app(workspace, TOKEN, environ={}, app_dir=app_dir)


class TestTheLock:
    def test_a_call_without_the_token_is_refused(self, workspace: Workspace) -> None:
        response = client(console(workspace), token=None).get("/api/status")

        assert response.status_code == 401

    def test_a_call_with_another_token_is_refused(self, workspace: Workspace) -> None:
        response = client(console(workspace), token="guessed").get("/api/status")

        assert response.status_code == 401

    def test_a_call_with_the_token_is_answered(self, workspace: Workspace) -> None:
        response = client(console(workspace)).get("/api/status")

        assert response.status_code == 200

    @pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765"])
    def test_local_host_names_are_accepted(self, workspace: Workspace, host: str) -> None:
        response = client(console(workspace)).get("/api/status", headers={"Host": host})

        assert response.status_code == 200

    def test_any_other_host_name_is_refused(self, workspace: Workspace) -> None:
        # A site pointing its own domain at this machine (DNS rebinding).
        response = client(console(workspace)).get(
            "/api/status", headers={"Host": "tyche.example.com"}
        )

        assert response.status_code == 400


class TestStatus:
    def test_a_new_workspace(self, workspace: Workspace) -> None:
        body = client(console(workspace)).get("/api/status").json()

        assert body["workspace"] == str(workspace.root)
        assert body["config"]["valid"] is True
        assert body["config"]["market_profile"] == "US"
        assert body["config"]["risk_profile"]["name"] == "default"
        assert body["config"]["strategies"] == [
            {"strategy_id": "buy_and_hold", "plugin": "buy_and_hold", "budget": "1.0"}
        ]
        assert body["config"]["money_caps"] == [
            {"currency": "USD", "capital": "700", "order": "350"}
        ]
        assert body["trading"] == {
            "stopped": False,
            "kill": None,
            "drawdown_halt": None,
            "reconciliation_halt": None,
            "state_unreadable": None,
        }
        assert body["account"] is None
        assert body["secrets"] == {"discord_webhook": False, "ib_gateway": False, "error": None}

    def test_an_invalid_config_says_why(self, workspace: Workspace) -> None:
        (workspace.root / "config" / "guardrails.toml").write_text("long_only = 3\n")

        body = client(console(workspace)).get("/api/status").json()

        assert body["config"]["valid"] is False
        assert "guardrails.toml" in body["config"]["error"]
        assert body["config"]["risk_profile"] is None

    def test_an_unknown_risk_profile_says_so(self, workspace: Workspace) -> None:
        body = (
            client(console(workspace)).get("/api/status", params={"risk_profile": "stage-9"}).json()
        )

        assert body["config"]["valid"] is False
        assert "stage-9" in body["config"]["error"]

    def test_the_kill_switch(self, workspace: Workspace) -> None:
        engage(workspace.kill_file, Kill("looks wrong", flatten=True))

        trading = client(console(workspace)).get("/api/status").json()["trading"]

        assert trading["stopped"] is True
        assert trading["kill"]["reason"] == "looks wrong"
        assert trading["kill"]["flatten"] is True

    def test_the_account_from_the_latest_checkpoint(self, workspace: Workspace) -> None:
        save(workspace, running())

        body = client(console(workspace)).get("/api/status").json()

        account = body["account"]
        assert account["run_id"] == "paper-2024-01-03"
        assert account["positions"] == [
            {"instrument": "SPY@ARCX", "quantity": "10", "cost": "4701"}
        ]
        assert {o["order_type"] for o in account["working_orders"]} == {"market", "stop"}
        stop = next(o for o in account["working_orders"] if o["order_type"] == "stop")
        assert stop["stop_price"] == "440"
        assert body["trading"]["stopped"] is False

    def test_a_drawdown_halt(self, workspace: Workspace) -> None:
        save(workspace, halted())

        trading = client(console(workspace)).get("/api/status").json()["trading"]

        assert trading["stopped"] is True
        assert trading["drawdown_halt"]["reasons"] == ["equity fell 15% below its peak"]

    def test_a_reconciliation_halt_lists_its_differences(self, workspace: Workspace) -> None:
        save(workspace, unreconciled())

        halt = (
            client(console(workspace)).get("/api/status").json()["trading"]["reconciliation_halt"]
        )

        assert halt is not None
        assert any("on a day no run read" in reason for reason in halt["reasons"])

    def test_secrets_are_reported_set_never_shown(self, workspace: Workspace) -> None:
        workspace.env_file.write_text(f"DISCORD_WEBHOOK_URL={WEBHOOK}\n")

        response = client(console(workspace)).get("/api/status")

        assert response.json()["secrets"]["discord_webhook"] is True
        assert "secret-token" not in response.text


class TestThePage:
    @pytest.fixture
    def built(self, tmp_path: Path) -> Path:
        app_dir = tmp_path / "dist"
        (app_dir / "assets").mkdir(parents=True)
        (app_dir / "index.html").write_text("<html>console</html>")
        (app_dir / "assets" / "app.js").write_text("console.log('tyche')")
        (tmp_path / "secret.txt").write_text("outside the app")
        return app_dir

    def test_serves_the_page_without_the_token(self, workspace: Workspace, built: Path) -> None:
        response = client(console(workspace, built), token=None).get("/")

        assert response.status_code == 200
        assert response.text == "<html>console</html>"

    def test_serves_built_files(self, workspace: Workspace, built: Path) -> None:
        response = client(console(workspace, built), token=None).get("/assets/app.js")

        assert response.text == "console.log('tyche')"

    def test_any_other_path_is_the_page_for_its_router(
        self, workspace: Workspace, built: Path
    ) -> None:
        response = client(console(workspace, built), token=None).get("/paper")

        assert response.text == "<html>console</html>"

    def test_never_serves_a_file_outside_the_app(self, workspace: Workspace, built: Path) -> None:
        response = client(console(workspace, built), token=None).get("/..%2fsecret.txt")

        assert "outside the app" not in response.text

    def test_an_unknown_api_path_is_not_the_page(self, workspace: Workspace, built: Path) -> None:
        response = client(console(workspace, built)).get("/api/nothing")

        assert response.status_code == 404


def test_the_committed_schema_matches_the_api() -> None:
    # After changing tyche.api.models: `make ui-types`, then commit both files.
    assert SCHEMA_FILE.read_text(encoding="utf-8") == render()
