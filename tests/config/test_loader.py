"""Loading the workspace configuration: all valid, or a clear error naming file and key."""

from importlib.resources import files
from pathlib import Path

import pytest

from tests.support.costs import US_COSTS
from tyche.config import (
    ConfigError,
    TycheFile,
    Workspace,
    config_hash,
    init_workspace,
    load_config,
)
from tyche.core.domain import Currency, MarketProfile


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def write(workspace: Workspace, relative: str, text: str) -> None:
    path = workspace.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


TYCHE_TOML = 'schema_version = 1\nmarket_profile = "US"\n'
US_TOML = 'name = "US"\ncash_currencies = ["USD"]\ncalendars = ["XNYS"]\n'
US_COSTS_TOML = (files("tyche.config") / "templates" / "costs" / "US.toml").read_text()


class TestValidConfig:
    def test_the_workspace_created_by_init_is_valid(self, workspace: Workspace) -> None:
        config = load_config(workspace)

        assert config.workspace == workspace
        assert config.market_profile == MarketProfile("US", (Currency.USD,), ("XNYS",))
        assert config.config_hash.startswith("sha256:")
        assert len(config.config_hash) == len("sha256:") + 64

    def test_the_packaged_costs_are_the_checked_ibkr_rates(self, workspace: Workspace) -> None:
        assert load_config(workspace).costs == US_COSTS

    def test_a_combined_profile_loads(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", 'schema_version = 1\nmarket_profile = "CA+US"\n')
        write(
            workspace,
            "config/markets/CA+US.toml",
            'name = "CA+US"\ncash_currencies = ["CAD", "USD"]\ncalendars = ["XTSE", "XNYS"]\n',
        )
        write(workspace, "config/costs/CA+US.toml", US_COSTS_TOML)

        profile = load_config(workspace).market_profile

        assert profile.cash_currencies == (Currency.CAD, Currency.USD)


class TestConfigHash:
    def test_is_stable(self, workspace: Workspace) -> None:
        assert load_config(workspace).config_hash == load_config(workspace).config_hash

    def test_ignores_comments_blank_lines_and_key_order(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        write(
            workspace,
            "config/tyche.toml",
            '# rewritten\n\nmarket_profile = "US"   # same\nschema_version = 1\n',
        )

        assert load_config(workspace).config_hash == before

    def test_changes_when_any_value_changes(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        write(workspace, "config/markets/US.toml", US_TOML.replace('["XNYS"]', '["XNYS", "XNAS"]'))

        assert load_config(workspace).config_hash != before

    def test_changes_when_a_cost_changes(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        write(workspace, "config/costs/US.toml", US_COSTS_TOML.replace('"5"', '"10"'))

        assert load_config(workspace).config_hash != before

    def test_is_independent_of_where_the_workspace_is(
        self, tmp_path: Path, workspace: Workspace
    ) -> None:
        other_home = tmp_path / "other"
        other_home.mkdir()
        other = init_workspace(other_home / "elsewhere", user_home=other_home)

        assert load_config(other).config_hash == load_config(workspace).config_hash

    def test_does_not_depend_on_secrets(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        write(workspace, ".env", "DISCORD_WEBHOOK_URL=https://example.invalid/hook\n")

        assert load_config(workspace).config_hash == before

    def test_includes_a_scheme_so_a_new_hashing_method_changes_every_hash(self) -> None:
        model = TycheFile(schema_version=1, market_profile="US")
        same = config_hash({"config/tyche.toml": model})

        assert same == config_hash(
            {"config/tyche.toml": TycheFile(schema_version=1, market_profile="US")}
        )
        assert same != config_hash({"config/other.toml": model})


class TestMissingFiles:
    def test_missing_tyche_toml(self, workspace: Workspace) -> None:
        workspace.tyche_config.unlink()

        with pytest.raises(
            ConfigError, match=r"config/tyche.toml is missing; is .* a Tyche workspace\?"
        ):
            load_config(workspace)

    def test_not_a_workspace_at_all(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"config/tyche\.toml is missing"):
            load_config(Workspace(tmp_path))

    def test_selected_profile_has_no_file(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", 'schema_version = 1\nmarket_profile = "CA"\n')

        with pytest.raises(
            ConfigError,
            match=r"selects market profile 'CA', but config/markets/CA.toml does not exist",
        ):
            load_config(workspace)


class TestInvalidTyche:
    def test_not_toml(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", "market_profile = US\n")

        with pytest.raises(ConfigError, match=r"config/tyche\.toml: not valid TOML"):
            load_config(workspace)

    def test_unknown_key(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", TYCHE_TOML + "risk_profle = 'default'\n")

        with pytest.raises(ConfigError, match=r"risk_profle: Extra inputs are not permitted"):
            load_config(workspace)

    def test_missing_key(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", "schema_version = 1\n")

        with pytest.raises(ConfigError, match=r"market_profile: Field required"):
            load_config(workspace)

    @pytest.mark.parametrize("value", ['"1"', "true", "1.0"])
    def test_schema_version_is_never_converted(self, workspace: Workspace, value: str) -> None:
        write(workspace, "config/tyche.toml", f'schema_version = {value}\nmarket_profile = "US"\n')

        with pytest.raises(ConfigError, match=r"schema_version: Input should be a valid integer"):
            load_config(workspace)

    def test_unsupported_schema_version(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", 'schema_version = 2\nmarket_profile = "US"\n')

        with pytest.raises(
            ConfigError, match="schema_version is 2, but this version of Tyche reads version 1"
        ):
            load_config(workspace)

    def test_every_problem_is_reported_at_once(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", 'schema_version = "x"\nextra = 1\n')

        with pytest.raises(ConfigError, match=r"3 invalid setting\(s\)") as caught:
            load_config(workspace)

        message = str(caught.value)
        assert "schema_version:" in message
        assert "market_profile:" in message
        assert "extra:" in message

    @pytest.mark.parametrize("name", ["../secrets", "us", "US/CA"])
    def test_a_profile_name_can_never_become_a_path(self, workspace: Workspace, name: str) -> None:
        write(workspace, "config/tyche.toml", f'schema_version = 1\nmarket_profile = "{name}"\n')

        with pytest.raises(ConfigError, match="market_profile: invalid market profile name"):
            load_config(workspace)


class TestInvalidMarketProfile:
    def test_name_must_match_the_file(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('name = "US"', 'name = "CA"'))

        with pytest.raises(
            ConfigError, match=r"config/markets/US.toml: name is 'CA', but the file is for 'US'"
        ):
            load_config(workspace)

    def test_unknown_currency(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('["USD"]', '["UDS"]'))

        with pytest.raises(ConfigError, match=r"cash_currencies.0: Input should be 'CAD' or 'USD'"):
            load_config(workspace)

    def test_a_single_string_is_not_a_list(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('["XNYS"]', '"XNYS"'))

        with pytest.raises(ConfigError, match=r"calendars: Input should be a valid tuple"):
            load_config(workspace)

    def test_domain_rules_are_reported_with_the_file(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('["XNYS"]', '["XNYS", "XNYS"]'))

        with pytest.raises(
            ConfigError, match=r"config/markets/US.toml: market profile US: calendars are repeated"
        ):
            load_config(workspace)

    def test_empty_calendars(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('["XNYS"]', "[]"))

        with pytest.raises(ConfigError, match="needs at least one calendar"):
            load_config(workspace)


class TestCosts:
    def test_missing_costs_file(self, workspace: Workspace) -> None:
        (workspace.costs_dir / "US.toml").unlink()

        with pytest.raises(
            ConfigError, match=r"config/costs/US.toml is missing: every market profile needs"
        ):
            load_config(workspace)

    @pytest.mark.parametrize(
        ("original", "replacement"),
        [('per_share = "0.005"', "per_share = 0.005"), ('slippage_bps = "5"', "slippage_bps = 5")],
    )
    def test_a_number_without_quotes_is_refused(
        self, workspace: Workspace, original: str, replacement: str
    ) -> None:
        write(workspace, "config/costs/US.toml", US_COSTS_TOML.replace(original, replacement))

        with pytest.raises(ConfigError, match=r"write decimals as strings"):
            load_config(workspace)

    def test_a_string_that_is_not_a_number_is_refused(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/costs/US.toml",
            US_COSTS_TOML.replace('minimum = "1.00"', 'minimum = "one"'),
        )

        with pytest.raises(ConfigError, match=r"commission.minimum: .*not a decimal number"):
            load_config(workspace)

    def test_infinity_is_refused(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/costs/US.toml",
            US_COSTS_TOML.replace('slippage_bps = "5"', 'slippage_bps = "Infinity"'),
        )

        with pytest.raises(ConfigError, match=r"slippage_bps: .*must be a finite number"):
            load_config(workspace)

    def test_checked_on_must_be_a_date(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/costs/US.toml",
            US_COSTS_TOML.replace("checked_on = 2026-11-17", "checked_on = 2026-11-17T10:00:00"),
        )

        with pytest.raises(ConfigError, match=r"checked_on: Input should be a valid date"):
            load_config(workspace)

    def test_an_impossible_rate_names_the_file(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/costs/US.toml",
            US_COSTS_TOML.replace('maximum_rate = "0.01"', 'maximum_rate = "2"'),
        )

        with pytest.raises(
            ConfigError, match=r"config/costs/US.toml: commission maximum_rate must be at most 1"
        ):
            load_config(workspace)

    def test_costs_must_be_in_a_currency_the_profile_holds(self, workspace: Workspace) -> None:
        write(workspace, "config/costs/US.toml", US_COSTS_TOML.replace('"USD"', '"CAD"'))

        with pytest.raises(
            ConfigError,
            match=(
                r"config/costs/US.toml: costs are in CAD, "
                r"but market profile US holds cash in USD"
            ),
        ):
            load_config(workspace)

    def test_an_unknown_key_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/costs/US.toml", US_COSTS_TOML + 'plan = "tiered"\n')

        with pytest.raises(ConfigError, match=r"plan: Extra inputs are not permitted"):
            load_config(workspace)
