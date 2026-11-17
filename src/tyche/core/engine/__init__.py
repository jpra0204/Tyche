"""The run loop that feeds inputs to the event bus.

Available now: ``Engine`` and ``RunResult``. One engine serves backtest, paper and live;
it receives a clock and a feed and does not know which mode it is in (ADR-0005).

Planned (Phase 1 onward): the wiring that subscribes the pipeline stages in a fixed,
documented order.
"""

from tyche.core.engine.engine import Engine, FeedOrderError, RunResult

__all__ = ["Engine", "FeedOrderError", "RunResult"]
