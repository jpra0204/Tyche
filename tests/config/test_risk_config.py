"""Loading the three layers of risk limits (ADR-0032): every breach names file, key and limit."""

from decimal import Decimal
from pathlib import Path

import pytest

from tyche.config import ConfigError, Workspace, init_workspace, load_config
from tyche.core.domain import Currency, Money
from tyche.core.risk import RiskProfile, StrategyRiskLimits


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def add_risk_table(workspace: Workspace, table: str) -> None:
    path = workspace.strategies_dir / "buy_and_hold.toml"
    with path.open("a", encoding="utf-8") as file:
        file.write("\n[risk]\n" + table)


class TestTheShippedFiles:
    def test_the_default_profile_is_the_briefs(self, workspace: Workspace) -> None:
        config = load_config(workspace)

        assert config.risk_profile == RiskProfile(
            name="default",
            risk_per_trade=Decimal("0.01"),
            max_open_positions=5,
            max_position_size=Decimal("0.20"),
            daily_loss_limit=Decimal("0.03"),
            drawdown_kill=Decimal("0.15"),
        )
        assert config.risk_profiles == ("default",)

    def test_the_guardrails_cap_usd_because_the_us_profile_holds_usd(
        self, workspace: Workspace
    ) -> None:
        guardrails = load_config(workspace).guardrails

        assert guardrails.capital_cap(Currency.USD) == Money(Decimal(700), Currency.USD)
        assert guardrails.order_cap(Currency.USD) == Money(Decimal(350), Currency.USD)

    def test_a_strategy_without_a_risk_table_has_no_limits_of_its_own(
        self, workspace: Workspace
    ) -> None:
        (spec,) = load_config(workspace).strategies

        assert spec.risk == StrategyRiskLimits()


class TestGuardrailsFile:
    def test_tyche_refuses_to_start_without_it(self, workspace: Workspace) -> None:
        workspace.guardrails.unlink()

        with pytest.raises(ConfigError, match=r"config/guardrails.toml is missing"):
            load_config(workspace)

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("long_only = true", "long_only = false"),
            ("allow_leverage = false", "allow_leverage = true"),
        ],
    )
    def test_only_long_only_without_leverage_is_accepted(
        self, workspace: Workspace, old: str, new: str
    ) -> None:
        edit(workspace.guardrails, old, new)

        with pytest.raises(ConfigError, match=r"config/guardrails.toml: 1 invalid setting"):
            load_config(workspace)

    def test_every_cash_currency_of_the_market_profile_needs_caps(
        self, workspace: Workspace
    ) -> None:
        edit(
            workspace.guardrails,
            'currency = "USD" },\n]\nmax_order',
            'currency = "CAD" },\n]\nmax_order',
        )
        edit(
            workspace.guardrails,
            '{ amount = "350", currency = "USD" }',
            '{ amount = "350", currency = "CAD" }',
        )

        with pytest.raises(ConfigError, match=r"holds cash in USD, but max_total_capital"):
            load_config(workspace)

    def test_an_order_cap_above_the_capital_cap_is_refused(self, workspace: Workspace) -> None:
        edit(workspace.guardrails, '"350"', '"800"')

        with pytest.raises(ConfigError, match=r"config/guardrails.toml: max_order_value"):
            load_config(workspace)

    def test_a_money_cap_written_as_a_number_is_refused(self, workspace: Workspace) -> None:
        edit(workspace.guardrails, 'amount = "700"', "amount = 700")

        with pytest.raises(ConfigError, match=r"write decimals as strings"):
            load_config(workspace)

    def test_the_guardrails_are_part_of_the_hash(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        edit(workspace.guardrails, '"0.25"    # largest', '"0.30"    # largest')

        assert load_config(workspace).config_hash != before


class TestRiskProfiles:
    def test_a_profile_above_the_guardrails_names_every_breach(self, workspace: Workspace) -> None:
        path = workspace.risk_dir / "default.toml"
        edit(path, 'max_position_size = "0.20"', 'max_position_size = "0.30"')
        edit(path, 'drawdown_kill = "0.15"', 'drawdown_kill = "0.40"')

        with pytest.raises(ConfigError) as caught:
            load_config(workspace)

        assert str(caught.value) == (
            "config/risk/default.toml: a risk profile may not exceed the guardrails "
            "(config/guardrails.toml)\n"
            "  max_position_size = 0.30 is above max_position_size = 0.25\n"
            "  drawdown_kill = 0.40 is above max_drawdown_kill = 0.25"
        )

    def test_every_profile_is_checked_not_only_the_active_one(self, workspace: Workspace) -> None:
        (workspace.risk_dir / "riskybusiness.toml").write_text(
            (workspace.risk_dir / "default.toml")
            .read_text()
            .replace("max_open_positions = 5", "max_open_positions = 11")
        )

        with pytest.raises(ConfigError, match=r"config/risk/riskybusiness.toml: a risk profile"):
            load_config(workspace)

    def test_another_profile_can_be_chosen(self, workspace: Workspace) -> None:
        (workspace.risk_dir / "safecash.toml").write_text(
            (workspace.risk_dir / "default.toml")
            .read_text()
            .replace('risk_per_trade = "0.01"', 'risk_per_trade = "0.005"')
        )

        config = load_config(workspace, "safecash")

        assert config.risk_profile.name == "safecash"
        assert config.risk_profile.risk_per_trade == Decimal("0.005")
        assert config.risk_profiles == ("default", "safecash")

    def test_only_the_active_profile_is_hashed(self, workspace: Workspace) -> None:
        before = load_config(workspace)
        (workspace.risk_dir / "safecash.toml").write_text(
            (workspace.risk_dir / "default.toml").read_text()
        )

        after = load_config(workspace)

        assert after.config_hash == before.config_hash
        assert "config/risk/safecash.toml" not in after.snapshot
        assert load_config(workspace, "safecash").config_hash != before.config_hash

    def test_a_file_name_that_is_not_a_profile_name_is_refused(self, workspace: Workspace) -> None:
        (workspace.risk_dir / "Safe Cash.toml").write_text("")

        with pytest.raises(ConfigError, match=r"invalid risk profile name 'Safe Cash'"):
            load_config(workspace)

    def test_a_limit_that_could_never_trigger_is_refused(self, workspace: Workspace) -> None:
        edit(workspace.guardrails, '"0.25"    # a profile', '"1"    # a profile')
        edit(workspace.risk_dir / "default.toml", '"0.15"', '"1"')

        with pytest.raises(ConfigError, match=r"config/guardrails.toml: max_drawdown_kill"):
            load_config(workspace)

    def test_a_profile_value_that_is_not_a_limit_names_the_file(self, workspace: Workspace) -> None:
        edit(
            workspace.risk_dir / "default.toml",
            'daily_loss_limit = "0.03"',
            'daily_loss_limit = "0"',
        )

        with pytest.raises(ConfigError, match=r"config/risk/default.toml: daily_loss_limit"):
            load_config(workspace)

    def test_a_missing_key_is_named(self, workspace: Workspace) -> None:
        edit(workspace.risk_dir / "default.toml", 'drawdown_kill = "0.15"', "")

        with pytest.raises(ConfigError, match=r"(?s)config/risk/default.toml.*drawdown_kill"):
            load_config(workspace)

    def test_an_unknown_profile_lists_the_available_ones(self, workspace: Workspace) -> None:
        with pytest.raises(
            ConfigError, match=r"no risk profile named 'safecash'.*available: default"
        ):
            load_config(workspace, "safecash")

    def test_a_workspace_without_profiles_says_where_to_find_one(
        self, workspace: Workspace
    ) -> None:
        (workspace.risk_dir / "default.toml").unlink()

        with pytest.raises(ConfigError, match=r"there are none; `tyche init`"):
            load_config(workspace)

    @pytest.mark.parametrize("name", ["../tyche", "Default", "a/b"])
    def test_a_chosen_name_can_never_become_a_path(self, workspace: Workspace, name: str) -> None:
        with pytest.raises(ConfigError, match=r"invalid risk profile name"):
            load_config(workspace, name)


class TestStrategyOverrides:
    def test_a_stricter_override_is_loaded(self, workspace: Workspace) -> None:
        add_risk_table(workspace, 'max_position_size = "0.10"\nmax_open_positions = 2\n')

        (spec,) = load_config(workspace).strategies

        assert spec.risk == StrategyRiskLimits(
            max_open_positions=2, max_position_size=Decimal("0.10")
        )

    def test_a_looser_override_is_refused_with_the_profile_it_breaks(
        self, workspace: Workspace
    ) -> None:
        add_risk_table(workspace, 'risk_per_trade = "0.015"\n')

        with pytest.raises(ConfigError) as caught:
            load_config(workspace)

        assert str(caught.value) == (
            "config/strategies/buy_and_hold.toml: [risk] may only be stricter than the active "
            "risk profile 'default' (config/risk/default.toml)\n"
            "  risk.risk_per_trade = 0.015 is above risk_per_trade = 0.01"
        )

    def test_account_rules_cannot_be_overridden(self, workspace: Workspace) -> None:
        add_risk_table(workspace, 'daily_loss_limit = "0.01"\n')

        with pytest.raises(ConfigError, match=r"risk.daily_loss_limit: Extra inputs"):
            load_config(workspace)

    def test_an_invalid_override_names_the_file(self, workspace: Workspace) -> None:
        add_risk_table(workspace, "max_open_positions = 0\n")

        with pytest.raises(ConfigError, match=r"buy_and_hold.toml: risk: max_open_positions"):
            load_config(workspace)

    def test_the_override_is_part_of_the_hash(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        add_risk_table(workspace, "max_open_positions = 2\n")

        assert load_config(workspace).config_hash != before
