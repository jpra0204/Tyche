"""Loading the workspace configuration: all valid, or a clear error naming file and key."""

from datetime import date
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest

from tests.support.costs import US_COSTS, US_TIERED_COSTS
from tests.support.profiles import US_PROFILE, US_TEMPLATE_PROFILE
from tests.support.workspace import BACKTEST
from tyche.config import (
    BacktestFile,
    ConfigError,
    TycheFile,
    Workspace,
    config_hash,
    init_workspace,
    load_config,
)
from tyche.core.domain import Currency, Money


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def write(workspace: Workspace, relative: str, text: str) -> None:
    path = workspace.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


TYCHE_TOML = 'schema_version = 1\nmarket_profile = "US"\n' + BACKTEST
STRATEGIES = '\n[strategies]\nbuy_and_hold = "1.0"\n'
BUY_AND_HOLD_TOML = (
    files("tyche.config") / "templates" / "strategies" / "buy_and_hold.toml"
).read_text()
UNIVERSE_TOML = """
[universe]
asset_classes = ["stock", "etf"]
currency = "USD"
min_price = "5.00"
min_average_dollar_volume = "10000000"
liquidity_sessions = 20
quality_sessions = 5
instruments = [
    { symbol = "SPY", exchange = "ARCX", asset_class = "etf" },
    { symbol = "QQQ", exchange = "XNAS", asset_class = "etf" },
]
"""
EXECUTION_TOML = """
[execution]
rebalance_band = "0.10"
price_buffer = "0.02"
"""
BENCHMARK_TOML = """
[benchmark]
symbol = "SPY"
exchange = "ARCX"
asset_class = "etf"
"""
US_TOML = (
    'name = "US"\ncash_currencies = ["USD"]\ncalendars = ["XNYS"]\n'
    + UNIVERSE_TOML
    + EXECUTION_TOML
    + BENCHMARK_TOML
)
US_COSTS_TOML = (files("tyche.config") / "templates" / "costs" / "US.toml").read_text()


class TestValidConfig:
    def test_the_workspace_created_by_init_is_valid(self, workspace: Workspace) -> None:
        config = load_config(workspace)

        assert config.workspace == workspace
        assert config.market_profile == US_TEMPLATE_PROFILE
        assert config.config_hash.startswith("sha256:")
        assert len(config.config_hash) == len("sha256:") + 64

    def test_the_packaged_costs_are_the_checked_ibkr_rates(self, workspace: Workspace) -> None:
        assert load_config(workspace).costs == US_COSTS

    def test_the_packaged_tiered_rates_are_the_checked_ibkr_rates(
        self, workspace: Workspace
    ) -> None:
        assert load_config(workspace).tiered_costs == US_TIERED_COSTS

    def test_the_tiered_table_is_optional(self, workspace: Workspace) -> None:
        without = US_COSTS_TOML[: US_COSTS_TOML.index("[tiered]")]
        write(workspace, "config/costs/US.toml", without)

        config = load_config(workspace)

        assert config.tiered_costs is None
        assert config.costs == US_COSTS
        # An absent optional table is not hashed, so workspaces written before it
        # existed keep their config hash.
        assert "tiered" not in config.snapshot["config/costs/US.toml"]

    def test_the_tiered_rates_are_part_of_the_hash(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        write(
            workspace,
            "config/costs/US.toml",
            US_COSTS_TOML.replace(
                'exchange_fee_per_share = "0.0030"', 'exchange_fee_per_share = "0.0015"'
            ),
        )

        assert load_config(workspace).config_hash != before

    def test_impossible_tiered_rates_are_refused(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/costs/US.toml",
            US_COSTS_TOML.replace('clearing_maximum_rate = "0.005"', 'clearing_maximum_rate = "2"'),
        )

        with pytest.raises(
            ConfigError,
            match=r"config/costs/US.toml: tiered clearing_maximum_rate must be at most 1",
        ):
            load_config(workspace)

    def test_a_combined_profile_loads(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/tyche.toml",
            'schema_version = 1\nmarket_profile = "CA+US"\n' + BACKTEST + STRATEGIES,
        )
        write(
            workspace,
            "config/markets/CA+US.toml",
            'name = "CA+US"\ncash_currencies = ["CAD", "USD"]\ncalendars = ["XTSE", "XNYS"]\n'
            + UNIVERSE_TOML
            + EXECUTION_TOML
            + BENCHMARK_TOML,
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
            '# rewritten\n\nmarket_profile = "US"   # same\nschema_version = 1\n'
            + BACKTEST
            + STRATEGIES,
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
        def model() -> TycheFile:
            return TycheFile(
                schema_version=1,
                market_profile="US",
                strategies={},
                backtest=BacktestFile.model_validate(
                    {"holdout_starts": date(2024, 1, 1), "starting_cash": "1"}
                ),
            )

        same = config_hash({"config/tyche.toml": model()})

        assert same == config_hash({"config/tyche.toml": model()})
        assert same != config_hash({"config/other.toml": model()})


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
        write(
            workspace,
            "config/tyche.toml",
            'schema_version = 1\nmarket_profile = "CA"\n' + BACKTEST + STRATEGIES,
        )

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
        write(workspace, "config/tyche.toml", TYCHE_TOML + "risk_profle = 'default'\n" + STRATEGIES)

        with pytest.raises(ConfigError, match=r"risk_profle: Extra inputs are not permitted"):
            load_config(workspace)

    def test_missing_key(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", "schema_version = 1\n" + BACKTEST + STRATEGIES)

        with pytest.raises(ConfigError, match=r"market_profile: Field required"):
            load_config(workspace)

    @pytest.mark.parametrize("value", ['"1"', "true", "1.0"])
    def test_schema_version_is_never_converted(self, workspace: Workspace, value: str) -> None:
        write(
            workspace,
            "config/tyche.toml",
            f'schema_version = {value}\nmarket_profile = "US"\n' + STRATEGIES,
        )

        with pytest.raises(ConfigError, match=r"schema_version: Input should be a valid integer"):
            load_config(workspace)

    def test_unsupported_schema_version(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/tyche.toml",
            'schema_version = 2\nmarket_profile = "US"\n' + BACKTEST + STRATEGIES,
        )

        with pytest.raises(
            ConfigError, match="schema_version is 2, but this version of Tyche reads version 1"
        ):
            load_config(workspace)

    def test_every_problem_is_reported_at_once(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", 'schema_version = "x"\nextra = 1\n')

        with pytest.raises(ConfigError, match=r"5 invalid setting\(s\)") as caught:
            load_config(workspace)

        message = str(caught.value)
        assert "backtest:" in message
        assert "schema_version:" in message
        assert "market_profile:" in message
        assert "extra:" in message
        assert "strategies:" in message

    @pytest.mark.parametrize("name", ["../secrets", "us", "US/CA"])
    def test_a_profile_name_can_never_become_a_path(self, workspace: Workspace, name: str) -> None:
        write(
            workspace,
            "config/tyche.toml",
            f'schema_version = 1\nmarket_profile = "{name}"\n' + BACKTEST + STRATEGIES,
        )

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


class TestUniverseRules:
    def test_the_packaged_profile_has_the_documented_rules(self, workspace: Workspace) -> None:
        assert load_config(workspace).market_profile.universe == US_TEMPLATE_PROFILE.universe

    def test_instruments_are_built_from_their_exchange(self, workspace: Workspace) -> None:
        spy, qqq, *others = load_config(workspace).market_profile.universe.instruments

        assert (str(spy), spy.calendar, spy.currency) == ("SPY@ARCX", "XNYS", Currency.USD)
        assert str(qqq) == "QQQ@XNAS"
        assert [str(i) for i in others] == [
            "IWM@ARCX",
            "EFA@ARCX",
            "EEM@ARCX",
            "TLT@XNAS",
            "IEF@XNAS",
            "GLD@ARCX",
            "VNQ@ARCX",
        ]

    def test_an_unknown_exchange_is_refused_with_the_known_ones(self, workspace: Workspace) -> None:
        write(
            workspace, "config/markets/US.toml", US_TOML.replace('"XNAS", asset', '"XTSE", asset')
        )

        with pytest.raises(
            ConfigError,
            match=r"US.toml: universe.instruments: QQQ: unknown exchange 'XTSE'; known "
            "exchanges: ARCX",
        ):
            load_config(workspace)

    def test_an_invalid_symbol_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('"QQQ"', '"Q Q Q"'))

        with pytest.raises(ConfigError, match=r"US.toml: universe.instruments: .*symbol"):
            load_config(workspace)

    def test_the_instrument_list_cannot_be_empty(self, workspace: Workspace) -> None:
        start = US_TOML.index("instruments = [")
        end = US_TOML.index("]\n", start) + 2
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML[:start] + "instruments = []\n" + US_TOML[end:],
        )

        with pytest.raises(ConfigError, match="list at least one instrument"):
            load_config(workspace)

    def test_changing_the_instruments_changes_the_hash(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML)
        before = load_config(workspace).config_hash
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML.replace('"QQQ"', '"IWM"').replace('"XNAS", asset', '"ARCX", asset'),
        )

        assert load_config(workspace).config_hash != before

    def test_a_profile_without_a_universe_table_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace(UNIVERSE_TOML, ""))

        with pytest.raises(ConfigError, match=r"US.toml: .*\n  universe: Field required"):
            load_config(workspace)

    def test_changing_a_threshold_changes_the_hash(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML)
        before = load_config(workspace).config_hash
        write(workspace, "config/markets/US.toml", US_TOML.replace('"5.00"', '"10.00"'))

        assert load_config(workspace).config_hash != before

    def test_a_price_without_quotes_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('"5.00"', "5.00"))

        with pytest.raises(ConfigError, match=r"universe.min_price: .*write decimals as strings"):
            load_config(workspace)

    def test_an_unknown_asset_class_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('"etf"]', '"bond"]'))

        with pytest.raises(ConfigError, match=r"universe.asset_classes.1: Input should be"):
            load_config(workspace)

    def test_an_impossible_rule_names_the_file(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML.replace("liquidity_sessions = 20", "liquidity_sessions = 0"),
        )

        with pytest.raises(
            ConfigError,
            match=r"config/markets/US.toml: universe rules: liquidity_sessions must be at least 1",
        ):
            load_config(workspace)

    def test_instruments_must_be_quoted_in_the_thresholds_currency(
        self, workspace: Workspace
    ) -> None:
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML.replace('currency = "USD"', 'currency = "CAD"'),
        )

        with pytest.raises(
            ConfigError,
            match=r"config/markets/US.toml: universe rules: SPY@ARCX is quoted in USD, but the "
            "thresholds are in CAD",
        ):
            load_config(workspace)


class TestStrategies:
    def test_the_template_runs_buy_and_hold_on_the_whole_budget(self, workspace: Workspace) -> None:
        config = load_config(workspace)

        [spec] = config.strategies
        assert (spec.strategy_id, spec.plugin, spec.budget) == (
            "buy_and_hold",
            "buy_and_hold",
            Decimal(1),
        )
        assert spec.parameters == {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"}
        assert spec.source == "config/strategies/buy_and_hold.toml"
        assert config.budgets == {"buy_and_hold": Decimal("1.0")}

    def test_strategies_are_ordered_by_id(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/tyche.toml",
            TYCHE_TOML + '[strategies]\nzeta = "0.3"\nalpha = "0.4"\n',
        )
        write(workspace, "config/strategies/zeta.toml", BUY_AND_HOLD_TOML)
        write(workspace, "config/strategies/alpha.toml", BUY_AND_HOLD_TOML)

        assert [s.strategy_id for s in load_config(workspace).strategies] == ["alpha", "zeta"]

    def test_a_strategy_needs_its_file(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", TYCHE_TOML + '[strategies]\ntrend = "0.5"\n')

        with pytest.raises(
            ConfigError,
            match=r"strategy 'trend' a budget, but config/strategies/trend.toml does not exist",
        ):
            load_config(workspace)

    @pytest.mark.parametrize(
        ("table", "message"),
        [
            ('buy_and_hold = "0.7"\nother = "0.4"', "budgets add up to 1.1, more than 1"),
            ('buy_and_hold = "0"', "must be above 0"),
            ("buy_and_hold = 0.5", "write decimals as strings"),
            ('"Buy And Hold" = "0.5"', "invalid strategy id"),
            ("", "need at least one strategy"),
        ],
    )
    def test_invalid_budgets(self, workspace: Workspace, table: str, message: str) -> None:
        write(workspace, "config/tyche.toml", TYCHE_TOML + "[strategies]\n" + table + "\n")
        write(workspace, "config/strategies/other.toml", BUY_AND_HOLD_TOML)

        with pytest.raises(ConfigError, match=message):
            load_config(workspace)

    def test_a_strategy_file_needs_a_plugin_and_no_unknown_keys(self, workspace: Workspace) -> None:
        write(workspace, "config/strategies/buy_and_hold.toml", 'plugn = "buy_and_hold"\n')

        with pytest.raises(ConfigError, match=r"buy_and_hold.toml: 2 invalid") as caught:
            load_config(workspace)

        assert "plugin: Field required" in str(caught.value)
        assert "plugn: Extra inputs are not permitted" in str(caught.value)

    def test_the_hash_covers_budgets_and_parameters(self, workspace: Workspace) -> None:
        before = load_config(workspace).config_hash
        write(workspace, "config/tyche.toml", TYCHE_TOML + '[strategies]\nbuy_and_hold = "0.9"\n')
        budget_changed = load_config(workspace).config_hash
        write(workspace, "config/tyche.toml", TYCHE_TOML + STRATEGIES)
        write(
            workspace,
            "config/strategies/buy_and_hold.toml",
            BUY_AND_HOLD_TOML.replace("SPY", "QQQ"),
        )

        assert len({before, budget_changed, load_config(workspace).config_hash}) == 3


class TestExecutionRules:
    def test_the_packaged_profile_has_the_documented_band(self, workspace: Workspace) -> None:
        execution = load_config(workspace).market_profile.execution

        assert execution == US_PROFILE.execution
        assert execution.rebalance_band == Decimal("0.10")
        assert execution.price_buffer == Decimal("0.02")

    def test_a_profile_without_an_execution_table_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace(EXECUTION_TOML, ""))

        with pytest.raises(ConfigError, match=r"US.toml: .*\n  execution: Field required"):
            load_config(workspace)

    def test_a_band_without_quotes_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('"0.10"', "0.10"))

        with pytest.raises(
            ConfigError, match=r"execution.rebalance_band: .*write decimals as strings"
        ):
            load_config(workspace)

    def test_an_impossible_band_names_the_file(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace('"0.10"', '"1"'))

        with pytest.raises(
            ConfigError,
            match=r"config/markets/US.toml: rebalance_band must be at least 0 and below 1",
        ):
            load_config(workspace)

    def test_a_profile_without_a_price_buffer_is_refused(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML.replace('price_buffer = "0.02"\n', ""),
        )

        with pytest.raises(ConfigError, match=r"execution.price_buffer: Field required"):
            load_config(workspace)

    def test_changing_the_band_changes_the_hash(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML)
        before = load_config(workspace).config_hash
        write(workspace, "config/markets/US.toml", US_TOML.replace('"0.10"', '"0.05"'))

        assert load_config(workspace).config_hash != before


class TestBacktestSettings:
    def test_the_template_reserves_history_from_2024_and_starts_with_10000_usd(
        self, workspace: Workspace
    ) -> None:
        settings = load_config(workspace).backtest

        assert settings.holdout_starts == date(2024, 1, 1)
        assert settings.starting_cash == Money.of("10000", Currency.USD)

    def test_the_holdout_start_must_be_a_toml_date(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/tyche.toml",
            TYCHE_TOML.replace("holdout_starts = 2024-01-01", 'holdout_starts = "2024-01-01"')
            + STRATEGIES,
        )

        with pytest.raises(
            ConfigError, match=r"backtest.holdout_starts: Input should be a valid date"
        ):
            load_config(workspace)

    def test_the_starting_cash_must_be_positive(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/tyche.toml",
            TYCHE_TOML.replace('starting_cash = "10000"', 'starting_cash = "0"') + STRATEGIES,
        )

        with pytest.raises(
            ConfigError, match=r"config/tyche\.toml: backtest: starting cash must be positive"
        ):
            load_config(workspace)

    def test_moving_the_holdout_changes_the_hash(self, workspace: Workspace) -> None:
        write(workspace, "config/tyche.toml", TYCHE_TOML + STRATEGIES)
        before = load_config(workspace).config_hash
        write(
            workspace,
            "config/tyche.toml",
            TYCHE_TOML.replace("2024-01-01", "2025-01-01") + STRATEGIES,
        )

        assert load_config(workspace).config_hash != before

    def test_the_snapshot_is_what_was_hashed(self, workspace: Workspace) -> None:
        config = load_config(workspace)

        assert sorted(config.snapshot) == [
            "config/costs/US.toml",
            "config/markets/US.toml",
            "config/strategies/buy_and_hold.toml",
            "config/tyche.toml",
        ]
        assert config.snapshot["config/tyche.toml"]["backtest"] == {
            "holdout_starts": "2024-01-01",
            "starting_cash": "10000",
        }


class TestBenchmark:
    def test_the_packaged_profile_measures_against_spy(self, workspace: Workspace) -> None:
        benchmark = load_config(workspace).market_profile.benchmark

        assert benchmark == US_PROFILE.benchmark
        assert str(benchmark) == "SPY@ARCX"

    def test_a_profile_without_a_benchmark_is_refused(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML.replace(BENCHMARK_TOML, ""))

        with pytest.raises(ConfigError, match=r"US.toml: .*\n  benchmark: Field required"):
            load_config(workspace)

    def test_an_unknown_exchange_names_the_benchmark(self, workspace: Workspace) -> None:
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML.replace('exchange = "ARCX"', 'exchange = "NOPE"'),
        )

        with pytest.raises(ConfigError, match=r"benchmark: SPY: unknown exchange 'NOPE'"):
            load_config(workspace)

    def test_changing_the_benchmark_changes_the_hash(self, workspace: Workspace) -> None:
        write(workspace, "config/markets/US.toml", US_TOML)
        before = load_config(workspace).config_hash
        write(
            workspace,
            "config/markets/US.toml",
            US_TOML.replace(BENCHMARK_TOML, BENCHMARK_TOML.replace("SPY", "QQQ")),
        )

        assert load_config(workspace).config_hash != before
