"""Backtesting on top of the engine and the simulator.

Available now: ``run_backtest``, which runs one ``BacktestSpec`` through the whole
trading path on replayed history and returns a ``BacktestResult``; and
``BacktestSettings``, the starting cash and the reserved holdout that no backtest may
reach (``HoldoutError``, ADR-0024); and ``measure_backtest``, which measures a run
against the total return of the market profile's benchmark (ADR-0025); and, for the
report (ADR-0028), ``cost_drag``, the run measured before and after its costs, and
``yearly_returns``, its return in each calendar year; and, for walk-forward analysis
(ADR-0029), ``plan_folds``, which cuts history into training and test windows, and
``measure_walk_forward``, which chains the test windows into one out-of-sample result;
and, for parameter sweeps (ADR-0030), ``combinations`` of a ``Grid``, ``pick``, which
chooses the trial with the highest Sharpe ratio, ``deflated_sharpe``, which discounts
it for the trials behind it, ``trial_key``, which fingerprints a trial so it is counted
once, and ``overfitting_warnings``.
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
from tyche.core.backtest.sweep import (
    CONFIDENCE,
    Combination,
    DeflatedSharpe,
    Grid,
    ReturnMoments,
    SweepError,
    Trial,
    combinations,
    deflated_sharpe,
    expected_max_sharpe,
    overfitting_warnings,
    pick,
    probabilistic_sharpe,
    return_moments,
    session_sharpe,
    trial_key,
)
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
    "CONFIDENCE",
    "BacktestError",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestSettings",
    "BacktestSpec",
    "ClosedTrade",
    "Combination",
    "Comparison",
    "CostDrag",
    "DeflatedSharpe",
    "Drawdown",
    "EquityPoint",
    "FillCost",
    "Fold",
    "FoldResult",
    "FoldScheme",
    "Grid",
    "HoldoutError",
    "MetricsError",
    "ReturnMoments",
    "SeriesMetrics",
    "SweepError",
    "TradeStats",
    "Trial",
    "WalkForwardError",
    "WalkForwardMetrics",
    "Window",
    "YearReturn",
    "benchmark_points",
    "chain",
    "closed_trades",
    "combinations",
    "cost_drag",
    "deflated_sharpe",
    "expected_max_sharpe",
    "fill_cost",
    "measure",
    "measure_backtest",
    "measure_walk_forward",
    "overfitting_warnings",
    "pick",
    "plan_folds",
    "probabilistic_sharpe",
    "return_moments",
    "run_backtest",
    "series_metrics",
    "session_sharpe",
    "trial_key",
    "yearly_returns",
]
