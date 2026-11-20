"""Built-in strategy plugins, and the registry config names them from.

Available now: ``BuyAndHold``, the benchmark; two example strategies (ADR-0027),
``TrendRotation`` (a monthly ETF rotation) and ``MeanReversion`` (a dip buy with a
stop), which exist to exercise the framework, not to make money; the shared
``indicators``; and ``PLUGINS``, the registry that ``config/strategies/<id>.toml``
files name a plugin from (ADR-0022).

A strategy is one file, one line in ``PLUGINS`` and its config. It may import only the
domain, the events and the signals contract (``tyche.core.pipeline.signals``); the
import contracts forbid risk, execution, the engine, the simulator and every port.
"""

from typing import Any

from tyche.strategies import buy_and_hold, mean_reversion, trend_rotation
from tyche.strategies.buy_and_hold import BuyAndHold, BuyAndHoldParameters
from tyche.strategies.mean_reversion import MeanReversion, MeanReversionParameters
from tyche.strategies.registry import (
    ExactDecimal,
    InstrumentLookup,
    InstrumentParameters,
    Parameters,
    Plugin,
)
from tyche.strategies.trend_rotation import TrendRotation, TrendRotationParameters

PLUGINS: dict[str, Plugin[Any]] = {
    plugin.name: plugin
    for plugin in (buy_and_hold.PLUGIN, mean_reversion.PLUGIN, trend_rotation.PLUGIN)
}
"""Every built-in plugin, by the name a strategy file uses."""

__all__ = [
    "PLUGINS",
    "BuyAndHold",
    "BuyAndHoldParameters",
    "ExactDecimal",
    "InstrumentLookup",
    "InstrumentParameters",
    "MeanReversion",
    "MeanReversionParameters",
    "Parameters",
    "Plugin",
    "TrendRotation",
    "TrendRotationParameters",
]
