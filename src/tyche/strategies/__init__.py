"""Built-in strategy plugins.

Available now: ``BuyAndHold``, the benchmark. Planned (PR 18): two simple example
strategies, an ETF trend rotation and a mean reversion with a stop. They exist to
exercise the framework, not to make money.

A strategy is one file plus config. It may import only the domain, the events and the
signals contract (``tyche.core.pipeline.signals``); the import contracts forbid risk,
execution, the engine, the simulator and every port.
"""

from tyche.strategies.buy_and_hold import BuyAndHold

__all__ = ["BuyAndHold"]
