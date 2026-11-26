"""The Config page (ADR-0046, console U5): the configuration, read-only."""

from pathlib import Path

import pytest

from tests.api.test_app import TOKEN, WEBHOOK, client
from tests.config.test_risk_config import add_risk_table, edit
from tyche.api import create_app
from tyche.config import Workspace, init_workspace, load_config


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def config_page(workspace: Workspace) -> dict:  # type: ignore[type-arg]
    response = client(create_app(workspace, TOKEN, environ={})).get("/api/config")
    assert response.status_code == 200
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def add_profile(workspace: Workspace, name: str, risk_per_trade: str) -> None:
    risk = workspace.root / "config" / "risk"
    text = (risk / "default.toml").read_text()
    assert 'risk_per_trade = "0.01"' in text
    text = text.replace('risk_per_trade = "0.01"', f'risk_per_trade = "{risk_per_trade}"')
    (risk / f"{name}.toml").write_text(text)


class TestANewWorkspace:
    def test_passes_its_check_with_the_same_hash(self, workspace: Workspace) -> None:
        body = config_page(workspace)

        assert body["valid"] is True
        assert body["error"] is None
        assert body["config_hash"] == load_config(workspace).config_hash
        assert body["workspace"] == str(workspace.root)

    def test_the_guardrails(self, workspace: Workspace) -> None:
        guardrails = config_page(workspace)["guardrails"]

        assert guardrails["max_open_positions"] >= 1
        assert guardrails["money_caps"] == [{"currency": "USD", "capital": "700", "order": "350"}]

    def test_the_strategy_and_its_parameters(self, workspace: Workspace) -> None:
        [strategy] = config_page(workspace)["strategies"]

        assert strategy["strategy_id"] == "buy_and_hold"
        assert strategy["budget"] == "1.0"
        assert strategy["source"] == "config/strategies/buy_and_hold.toml"
        assert strategy["parameters"]["symbol"] == "SPY"
        assert strategy["risk_per_trade"] is None

    def test_the_market_profile(self, workspace: Workspace) -> None:
        market = config_page(workspace)["market"]

        assert market["name"] == "US"
        assert market["cash_currencies"] == ["USD"]
        assert market["benchmark"] == "SPY@ARCX"
        assert "SPY@ARCX" in market["candidates"]
        assert market["holdout_starts"] == "2024-01-01"

    def test_every_loaded_file_as_hashed(self, workspace: Workspace) -> None:
        files = config_page(workspace)["files"]

        paths = [f["path"] for f in files]
        assert "config/tyche.toml" in paths
        assert "config/guardrails.toml" in paths
        assert paths == sorted(paths)

    def test_a_sweep_whose_strategy_has_no_budget_says_why(self, workspace: Workspace) -> None:
        [sweep] = config_page(workspace)["sweeps"]

        assert sweep["name"] == "trend_rotation"
        assert "no budget" in sweep["error"]


class TestProfiles:
    def test_each_profile_as_the_active_one(self, workspace: Workspace) -> None:
        add_profile(workspace, "careful", "0.005")
        add_risk_table(workspace, 'risk_per_trade = "0.008"\n')

        body = config_page(workspace)

        by_name = {p["name"]: p for p in body["profiles"]}
        assert by_name["default"]["valid"] is True
        assert by_name["default"]["profile"]["risk_per_trade"] == "0.01"
        assert by_name["careful"]["valid"] is False
        assert "may only be stricter" in by_name["careful"]["error"]
        assert body["valid"] is True  # under default, the strategy's own limit fits

    def test_an_invalid_config_says_why_and_shows_nothing_else(self, workspace: Workspace) -> None:
        (workspace.root / "config" / "guardrails.toml").write_text("long_only = 3\n")

        body = config_page(workspace)

        assert body["valid"] is False
        assert "guardrails.toml" in body["error"]
        assert body["strategies"] == []
        assert body["files"] == []


class TestSweeps:
    def test_a_sweep_and_how_many_combinations_it_tries(self, workspace: Workspace) -> None:
        edit(
            workspace.tyche_config,
            'buy_and_hold = "1.0"',
            'buy_and_hold = "0.5"\ntrend_rotation = "0.5"',
        )

        [sweep] = config_page(workspace)["sweeps"]

        assert sweep["error"] is None
        assert sweep["strategy_id"] == "trend_rotation"
        sizes = [len(values) for values in sweep["grid"].values()]
        expected = 1
        for size in sizes:
            expected *= size
        assert sweep["combinations"] == expected > 1


class TestSecrets:
    def test_env_is_never_shown(self, workspace: Workspace) -> None:
        workspace.env_file.write_text(f"DISCORD_WEBHOOK_URL={WEBHOOK}\n")

        response = client(create_app(workspace, TOKEN, environ={})).get("/api/config")

        assert "secret-token" not in response.text
        assert all(".env" not in f["path"] for f in response.json()["files"])

    def test_says_when_other_users_can_read_env(self, workspace: Workspace) -> None:
        workspace.env_file.chmod(0o644)

        assert config_page(workspace)["env_readable_by_others"] is True

    def test_a_private_env_is_not_flagged(self, workspace: Workspace) -> None:
        workspace.env_file.chmod(0o600)

        assert config_page(workspace)["env_readable_by_others"] is False
