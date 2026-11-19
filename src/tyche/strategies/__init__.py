"""Built-in strategy plugins, and the registry config names them from.

Available now: ``BuyAndHold``, the benchmark, and ``PLUGINS``, the registry that
``config/strategies/<id>.toml`` files name a plugin from (ADR-0022). Planned (PR 18):
two simple example strategies, an ETF trend rotation and a mean reversion with a
stop. They exist to exercise the framework, not to make money.

A strategy is one file, one line in ``PLUGINS`` and its config. It may import only the
domain, the events and the signals contract (``tyche.core.pipeline.signals``); the
import contracts forbid risk, execution, the engine, the simulator and every port.
"""

from typing import Any

from tyche.strategies import buy_and_hold
from tyche.strategies.buy_and_hold import BuyAndHold, BuyAndHoldParameters
from tyche.strategies.registry import InstrumentLookup, Parameters, Plugin

PLUGINS: dict[str, Plugin[Any]] = {plugin.name: plugin for plugin in (buy_and_hold.PLUGIN,)}
"""Every built-in plugin, by the name a strategy file uses."""

__all__ = [
    "PLUGINS",
    "BuyAndHold",
    "BuyAndHoldParameters",
    "InstrumentLookup",
    "Parameters",
    "Plugin",
]
