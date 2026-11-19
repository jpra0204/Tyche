"""The plugin registry: config names a plugin, the plugin checks its own parameters."""

import pytest
from pydantic import ValidationError

from tests.support.market import SPY
from tyche.core.domain import AssetClass, Instrument
from tyche.strategies import PLUGINS, BuyAndHold


def lookup(symbol: str, exchange: str, asset_class: AssetClass) -> Instrument:
    assert (symbol, exchange, asset_class) == ("SPY", "ARCX", AssetClass.ETF)
    return SPY


def test_every_plugin_is_registered_under_its_own_name() -> None:
    assert all(name == plugin.name for name, plugin in PLUGINS.items())
    assert "buy_and_hold" in PLUGINS


def test_buy_and_hold_is_built_from_its_parameters() -> None:
    raw = {"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf"}

    strategy = PLUGINS["buy_and_hold"].create("benchmark", raw, lookup)

    assert isinstance(strategy, BuyAndHold)
    assert (strategy.strategy_id, strategy.instrument) == ("benchmark", SPY)


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ({"symbol": "SPY", "exchange": "ARCX"}, "asset_class"),
        ({"symbol": "SPY", "exchange": "ARCX", "asset_class": "etf", "lots": 2}, "lots"),
        ({"symbol": 1, "exchange": "ARCX", "asset_class": "etf"}, "symbol"),
        ({"symbol": "SPY", "exchange": "ARCX", "asset_class": "bond"}, "asset_class"),
    ],
)
def test_parameters_are_strict(raw: dict[str, object], problem: str) -> None:
    with pytest.raises(ValidationError) as raised:
        PLUGINS["buy_and_hold"].create("benchmark", raw, lookup)

    assert [error["loc"][0] for error in raised.value.errors()] == [problem]
