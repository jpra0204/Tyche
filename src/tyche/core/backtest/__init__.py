"""Backtesting on top of the engine and the simulator.

Available now: ``run_backtest``, which runs one ``BacktestSpec`` through the whole
trading path on replayed history and returns a ``BacktestResult``; and
``BacktestSettings``, the starting cash and the reserved holdout that no backtest may
reach (``HoldoutError``, ADR-0024); and ``measure_backtest``, which measures a run
against the total return of the market profile's benchmark (ADR-0025); and, for the
report (ADR-0028), ``cost_drag``, the run measured before and after its costs, and
``yearly_returns``, its return in each calendar year; and, for walk-forward analysis
(ADR-0029), ``plan_folds``, which cuts history into training and test windows, and
``measure_walk_forward``, which chains the test windows into one out-of-sample result.

Planned (Phase 1): parameter sweeps.
"""

from tyche.core.backtest.cost_drag import CostDrag, FillCost, cost_drag, fill_cost
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
from tyche.core.backtest.walk_forward import (
    Fold,
    FoldResult,
    FoldScheme,
    WalkForwardError,
    WalkForwardMetrics,
    Window,
    chain,
    measure_walk_forward,
    plan_folds,
)
from tyche.core.backtest.years import YearReturn, yearly_returns

__all__ = [
    "BacktestError",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestSettings",
    "BacktestSpec",
    "ClosedTrade",
    "Comparison",
    "CostDrag",
    "Drawdown",
    "EquityPoint",
    "FillCost",
    "Fold",
    "FoldResult",
    "FoldScheme",
    "HoldoutError",
    "MetricsError",
    "SeriesMetrics",
    "TradeStats",
    "WalkForwardError",
    "WalkForwardMetrics",
    "Window",
    "YearReturn",
    "benchmark_points",
    "chain",
    "closed_trades",
    "cost_drag",
    "fill_cost",
    "measure",
    "measure_backtest",
    "measure_walk_forward",
    "plan_folds",
    "run_backtest",
    "series_metrics",
    "yearly_returns",
]
