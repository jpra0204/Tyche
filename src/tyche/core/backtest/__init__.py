"""Backtesting on top of the engine and the simulator.

Available now: ``run_backtest``, which runs one ``BacktestSpec`` through the whole
trading path on replayed history and returns a ``BacktestResult``; and
``BacktestSettings``, the starting cash and the reserved holdout that no backtest may
reach (``HoldoutError``, ADR-0024); and ``measure_backtest``, which measures a run
against the total return of the market profile's benchmark (ADR-0025).

Planned (Phase 1): train/test splits, walk-forward analysis and parameter sweeps.
"""

from tyche.core.backtest.metrics import (
    BacktestMetrics,
    ClosedTrade,
    Comparison,
    Drawdown,
    EquityPoint,
    MetricsError,
    SeriesMetrics,
    TradeStats,
    benchmark_points,
    closed_trades,
    measure,
    measure_backtest,
    series_metrics,
)
from tyche.core.backtest.runner import (
    BacktestError,
    BacktestResult,
    BacktestSpec,
    run_backtest,
)
from tyche.core.backtest.settings import BacktestSettings, HoldoutError

__all__ = [
    "BacktestError",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestSettings",
    "BacktestSpec",
    "ClosedTrade",
    "Comparison",
    "Drawdown",
    "EquityPoint",
    "HoldoutError",
    "MetricsError",
    "SeriesMetrics",
    "TradeStats",
    "benchmark_points",
    "closed_trades",
    "measure",
    "measure_backtest",
    "run_backtest",
    "series_metrics",
]
