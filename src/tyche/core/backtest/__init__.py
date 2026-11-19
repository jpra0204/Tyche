"""Backtesting on top of the engine and the simulator.

Available now: ``run_backtest``, which runs one ``BacktestSpec`` through the whole
trading path on replayed history and returns a ``BacktestResult``; and
``BacktestSettings``, the starting cash and the reserved holdout that no backtest may
reach (``HoldoutError``, ADR-0024).

Planned (Phase 1): metrics versus the benchmark, train/test splits, walk-forward
analysis and parameter sweeps.
"""

from tyche.core.backtest.runner import (
    BacktestError,
    BacktestResult,
    BacktestSpec,
    run_backtest,
)
from tyche.core.backtest.settings import BacktestSettings, HoldoutError

__all__ = [
    "BacktestError",
    "BacktestResult",
    "BacktestSettings",
    "BacktestSpec",
    "HoldoutError",
    "run_backtest",
]
