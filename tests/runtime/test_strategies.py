"""Building the configured strategies: every mistake is a ConfigError naming the file."""

from pathlib import Path

import pytest

from tests.support.market import SPY
from tyche.config import ConfigError, Workspace, init_workspace, load_config
from tyche.runtime.strategies import build_strategies
from tyche.strategies import PLUGINS, BuyAndHold, BuyAndHoldParameters, InstrumentLookup, Plugin


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return init_workspace(home / "ws", user_home=home)


def write_strategy(workspace: Workspace, text: str) -> None:
    (workspace.strategies_dir / "buy_and_hold.toml").write_text(text)


def test_the_template_builds_buy_and_hold_on_spy(workspace: Workspace) -> None:
    configured = build_strategies(load_config(workspace))

    [strategy] = configured.strategies
    assert isinstance(strategy, BuyAndHold)
    assert strategy.instrument == SPY
    assert configured.budgets == {"buy_and_hold": 1}


def test_an_unknown_plugin(workspace: Workspace) -> None:
    write_strategy(workspace, 'plugin = "moonshot"\n')

    with pytest.raises(ConfigError, match=r"buy_and_hold.toml: plugin: unknown plugin 'moonshot'"):
        build_strategies(load_config(workspace))


def test_an_instrument_outside_the_market_profile(workspace: Workspace) -> None:
    write_strategy(
        workspace,
        'plugin = "buy_and_hold"\n[parameters]\nsymbol = "XIU"\nexchange = "XTSE"\n'
        'asset_class = "etf"\n',
    )

    with pytest.raises(
        ConfigError, match=r"buy_and_hold.toml: parameters: unknown exchange 'XTSE'"
    ):
        build_strategies(load_config(workspace))


def test_invalid_parameters_name_each_key(workspace: Workspace) -> None:
    write_strategy(workspace, 'plugin = "buy_and_hold"\n[parameters]\nsymbol = 5\n')

    with pytest.raises(ConfigError) as raised:
        build_strategies(load_config(workspace))

    message = str(raised.value)
    assert message.startswith("config/strategies/buy_and_hold.toml: 3 invalid parameter(s)")
    assert "parameters.symbol: Input should be a valid string" in message
    assert "parameters.exchange: Field required" in message


def test_a_plugin_that_renames_its_strategy_is_a_bug(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def renaming(
        strategy_id: str, parameters: BuyAndHoldParameters, lookup: InstrumentLookup
    ) -> BuyAndHold:
        return BuyAndHold(SPY, strategy_id="someone_else")

    monkeypatch.setitem(
        PLUGINS, "buy_and_hold", Plugin("buy_and_hold", BuyAndHoldParameters, renaming)
    )

    with pytest.raises(ConfigError, match="built a strategy named 'someone_else'"):
        build_strategies(load_config(workspace))
