"""Wiring for ``tyche walk-forward``: folds of backtests, and their record (ADR-0029).

Composition-root code (ADR-0004). It plans the folds (``plan_folds``), runs every
training and test window as a backtest of its own through the same path as
``tyche backtest`` (``run_and_record``), and measures the test windows chained into
one out-of-sample result (``measure_walk_forward``). Everything goes to
``reports/walk_forward/<id>/`` in the workspace:

* ``walk_forward.json``: what ran (code, config hash and every setting, the scheme,
  each fold's windows and records) and how it ended.
* ``metrics.json``: the test windows chained, against the benchmark chained the same
  way, and how many test windows beat the benchmark.
* ``equity.csv``: the chained equity and benchmark at every test close.
* ``folds/<NN>-train/`` and ``folds/<NN>-test/``: each window's full backtest record,
  as ``tyche backtest`` writes it, without a report of its own.

The train step sits between a fold's two runs: it decides what the test window runs.

* Without a sweep it is ``keep_configured``: nothing is chosen, so a test window runs
  the configured strategies, exactly as any backtest would. The training run is still
  made and recorded, so that in-sample and out-of-sample results are always reported
  side by side.
* With a sweep (``tyche walk-forward --sweep <name>``, ADR-0030), every combination of
  the grid runs on the training window, and the test window runs the one with the
  highest Sharpe ratio there. The training window's folder then holds the pick's full
  record and ``trials.json``, with every combination's results and the pick's
  deflated Sharpe ratio. Each combination counts as one trial, however many folds
  run it.

A walk-forward stops at the first window that halts or cannot be measured, and is
recorded up to there.
"""

import csv
import json
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from tyche.adapters.clocks import SystemClock
from tyche.config import SweepSpec, TycheConfig
from tyche.core.backtest import (
    BacktestError,
    Fold,
    FoldResult,
    FoldScheme,
    MetricsError,
    WalkForwardMetrics,
    measure_walk_forward,
    plan_folds,
)
from tyche.core.backtest.metrics import equity_points
from tyche.core.ports import Clock
from tyche.runtime.backtest import (
    BENCHMARK_METHOD,
    BacktestOutcome,
    BacktestRequestError,
    CachedMarket,
    CodeVersion,
    cached_market,
    cents,
    checked_range,
    comparison_record,
    conventions_record,
    current_code_version,
    new_run_id,
    record_run,
    run_and_record,
    series_record,
)
from tyche.runtime.strategies import ConfiguredStrategies, build_strategies
from tyche.runtime.sweep import (
    SweepPlan,
    SweepResult,
    TrialProgress,
    plan_sweep,
    run_sweep,
    write_trials,
)
from tyche.runtime.trials import TRIALS_FILE

WALK_FORWARD_FORMAT = 1
"""Version of the layout of ``walk_forward.json`` and of the walk-forward's
``metrics.json``. Raised when a field changes meaning or goes away."""

WALK_FORWARD_FILE = "walk_forward.json"

TRAIN_STEP = "keep the configured parameters"
"""What the train step does without a sweep, as the record states it."""


def sweep_train_step(plan: SweepPlan) -> str:
    """What the train step does with a sweep, as the record states it."""
    return (
        f"pick the highest Sharpe ratio of sweep {plan.sweep.name!r} "
        f"({len(plan.combinations)} combinations of {plan.strategy_id}) on the training window"
    )


class WindowKind(StrEnum):
    """Which of a fold's two windows a run is."""

    TRAIN = "train"
    TEST = "test"


Progress = Callable[[Fold, WindowKind, BacktestOutcome, Mapping[str, Any] | None], None]
"""Told about every window as soon as it is recorded, for the command to print, with
the parameters a sweep picked on a training window (``None`` without a sweep)."""


@dataclass(frozen=True, slots=True)
class WalkForwardOutcome:
    """A finished walk-forward, or as far as it got, and where its record was written.

    Attributes:
        walk_forward_id: Identifies it, and names its folder.
        record_dir: ``reports/walk_forward/<id>/``.
        code: Which code ran.
        scheme: How the history was cut.
        folds: Every fold planned.
        finished: The folds run to the end of their test window, in order.
        metrics: The test windows chained and measured; ``None`` if it stopped early.
        failure: Why it stopped before the end, or ``None``.
        plan: The sweep run on every training window; ``None`` without one.
        picks: Each finished training window's sweep, by fold number.
    """

    walk_forward_id: str
    record_dir: Path
    code: CodeVersion
    scheme: FoldScheme
    folds: tuple[Fold, ...]
    finished: tuple[FoldResult, ...]
    metrics: WalkForwardMetrics | None
    failure: str | None
    plan: SweepPlan | None = None
    picks: Mapping[int, SweepResult] | None = None

    @property
    def completed(self) -> bool:
        return self.failure is None


def keep_configured(
    config: TycheConfig, fold: Fold, trained: BacktestOutcome
) -> ConfiguredStrategies:
    """The train step: what a fold's test window runs, decided on its training window.

    Without a sweep, it keeps the configured strategies and parameters, and ignores
    the training run. With one, the walk-forward picks from the sweep instead.
    """
    del fold, trained  # nothing is chosen yet
    return build_strategies(config)


@dataclass(frozen=True, slots=True)
class _Study:
    """What every window of one walk-forward shares."""

    config: TycheConfig
    market: CachedMarket
    walk_forward_id: str
    folder: Path
    scheme: FoldScheme
    folds: tuple[Fold, ...]
    first: date
    last: date
    clock: Clock
    code: CodeVersion
    started: datetime
    plan: SweepPlan | None
    train_step: str


def run_configured_walk_forward(
    config: TycheConfig,
    first: date,
    last: date | None = None,
    scheme: FoldScheme | None = None,
    *,
    clock: Clock | None = None,
    code: CodeVersion | None = None,
    progress: Progress | None = None,
    sweep: SweepSpec | None = None,
    trial_progress: TrialProgress | None = None,
) -> WalkForwardOutcome:
    """Walk forward from ``first`` to ``last``, and record every window and the result.

    ``last`` defaults to the day before the holdout; ``scheme`` to anchored folds with
    a five-year first training window and one-year test windows. With ``sweep``, each
    training window runs every combination of its grid and the test window runs the
    pick; ``trial_progress`` is told about each trial.

    Raises:
        BacktestRequestError: The range cannot be run as asked, or history is missing
            from the cache. Windows already run stay recorded, and so does the
            walk-forward, as stopped.
        HoldoutError: ``last`` reaches the holdout.
        WalkForwardError: The range leaves no test window.
        BacktestError: A window cannot be set up.
        ConfigError: A strategy cannot be built from its file, or a sweep's combination
            cannot be built.
        TrialCountError: A sweep's trials cannot be counted.
    """
    clock = clock or SystemClock()
    last = checked_range(config, first, last)
    scheme = scheme or FoldScheme()
    folds = plan_folds(first, last, scheme)
    build_strategies(config)  # a bad strategy file fails before anything is written
    plan = plan_sweep(config, sweep) if sweep is not None else None
    root = config.workspace.reports_dir / "walk_forward"
    walk_forward_id = new_run_id(root, clock.now(), config.config_hash)
    study = _Study(
        config=config,
        market=cached_market(config, last, clock),
        walk_forward_id=walk_forward_id,
        folder=root / walk_forward_id,
        scheme=scheme,
        folds=folds,
        first=first,
        last=last,
        clock=clock,
        code=code or current_code_version(),
        started=clock.now(),
        plan=plan,
        train_step=sweep_train_step(plan) if plan is not None else TRAIN_STEP,
    )
    currency = config.market_profile.cash_currencies[0]

    finished: list[FoldResult] = []
    picks: dict[int, SweepResult] = {}
    failure: str | None = None
    try:
        for fold in folds:
            if plan is None:
                trained = _window(study, fold, WindowKind.TRAIN, build_strategies(config), progress)
                chosen = keep_configured(config, fold, trained)
            else:
                swept = _sweep_window(study, plan, fold, trial_progress)
                train_folder = study.folder / fold_folder(fold, WindowKind.TRAIN)
                if swept.best is None or swept.best_run is None:
                    train_folder.mkdir(parents=True)
                    write_trials(train_folder, swept, pick_record=None)
                    failure = (
                        f"fold {fold.number}'s train window: no combination of the sweep "
                        "has a Sharpe ratio, so nothing can be picked"
                    )
                    break
                picks[fold.number] = swept
                trained = record_run(
                    config,
                    swept.best_run,
                    folder=train_folder,
                    code=study.code,
                    part_of=_part_of(study, fold, WindowKind.TRAIN, swept.best.combination.number),
                )
                write_trials(train_folder, swept, pick_record=".")
                if progress is not None:
                    progress(fold, WindowKind.TRAIN, trained, swept.best.combination.values)
                chosen = plan.strategies(swept.best.combination)
            failure = _failure(fold, WindowKind.TRAIN, trained)
            if failure is not None:
                break
            tested = _window(study, fold, WindowKind.TEST, chosen, progress)
            failure = _failure(fold, WindowKind.TEST, tested)
            if failure is not None:
                break
            if trained.metrics is None or tested.metrics is None:  # pragma: no cover
                raise AssertionError("a window without a failure was not measured")
            finished.append(
                FoldResult(
                    fold, trained.metrics, tested.metrics, equity_points(tested.result, currency)
                )
            )
    except (BacktestRequestError, BacktestError) as error:
        if study.folder.exists():
            _write_record(study, finished, None, f"stopped: {error}", picks)
        raise

    metrics: WalkForwardMetrics | None = None
    if failure is None:
        try:
            metrics = measure_walk_forward(finished)
        except MetricsError as error:
            failure = f"the test windows could not be measured: {error}"
    _write_record(study, finished, metrics, failure, picks)
    return WalkForwardOutcome(
        walk_forward_id,
        study.folder,
        study.code,
        scheme,
        folds,
        tuple(finished),
        metrics,
        failure,
        plan,
        picks,
    )


def fold_folder(fold: Fold, kind: WindowKind) -> str:
    """Where a window's record goes, inside the walk-forward's folder."""
    return f"folds/{fold.number:02d}-{kind.value}"


def _window(
    study: _Study,
    fold: Fold,
    kind: WindowKind,
    strategies: ConfiguredStrategies,
    progress: Progress | None,
) -> BacktestOutcome:
    window = fold.train if kind is WindowKind.TRAIN else fold.test
    outcome = run_and_record(
        study.config,
        study.market,
        strategies,
        run_id=f"{study.walk_forward_id}-{fold.number:02d}-{kind.value}",
        first=window.first,
        last=window.last,
        folder=study.folder / fold_folder(fold, kind),
        clock=study.clock,
        code=study.code,
        part_of=_part_of(study, fold, kind),
    )
    if progress is not None:
        progress(fold, kind, outcome, None)
    return outcome


def _sweep_window(
    study: _Study, plan: SweepPlan, fold: Fold, trial_progress: TrialProgress | None
) -> SweepResult:
    return run_sweep(
        plan,
        study.market,
        run_id=f"{study.walk_forward_id}-{fold.number:02d}-{WindowKind.TRAIN.value}",
        first=fold.train.first,
        last=fold.train.last,
        clock=study.clock,
        code=study.code,
        progress=trial_progress,
    )


def _part_of(
    study: _Study, fold: Fold, kind: WindowKind, trial: int | None = None
) -> dict[str, Any]:
    return {
        "walk_forward": study.walk_forward_id,
        "fold": fold.number,
        "window": kind.value,
        "train_step": study.train_step,
        **({"trial": trial} if trial is not None else {}),
    }


def _failure(fold: Fold, kind: WindowKind, outcome: BacktestOutcome) -> str | None:
    where = f"fold {fold.number}'s {kind.value} window"
    if not outcome.result.run.completed:
        return f"{where} halted: {outcome.result.run.failure}"
    if outcome.metrics is None:
        return f"{where} could not be measured: {outcome.metrics_error}"
    return None


# --- the record -----------------------------------------------------------------------


def _write_record(
    study: _Study,
    finished: Sequence[FoldResult],
    metrics: WalkForwardMetrics | None,
    failure: str | None,
    picks: Mapping[int, SweepResult],
) -> None:
    study.folder.mkdir(parents=True, exist_ok=True)
    record = walk_forward_record(study, finished, metrics, failure, picks)
    _write_json(study.folder / WALK_FORWARD_FILE, record)
    if metrics is None:
        return
    currency = study.config.market_profile.cash_currencies[0]
    _write_json(study.folder / "metrics.json", walk_forward_metrics_record(study, metrics))
    fold_of = {
        point.at: result.fold.number for result in metrics.folds for point in result.test_equity
    }
    with (study.folder / "equity.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["close_utc", "fold", "equity", "invested", "benchmark_equity", "currency"])
        for point, bench in zip(metrics.equity, metrics.benchmark_equity, strict=True):
            writer.writerow(
                [
                    point.at.isoformat(),
                    fold_of[point.at],
                    cents(point.equity),
                    cents(point.invested),
                    cents(bench.equity),
                    currency.value,
                ]
            )


def walk_forward_record(
    study: _Study,
    finished: Sequence[FoldResult],
    metrics: WalkForwardMetrics | None,
    failure: str | None,
    picks: Mapping[int, SweepResult] | None = None,
) -> dict[str, Any]:
    """``walk_forward.json``: what ran, fold by fold, and how it ended."""
    picks = picks or {}
    plan = study.plan
    config, code = study.config, study.code
    done = {result.fold.number for result in finished}
    plugins = {s.strategy_id: s.plugin for s in config.strategies}
    budgets = config.budgets
    return {
        "walk_forward_format": WALK_FORWARD_FORMAT,
        "walk_forward_id": study.walk_forward_id,
        "started_at": study.started.isoformat(),
        "finished_at": study.clock.now().isoformat(),
        "code": {
            "tyche_version": code.tyche,
            "git_commit": code.commit,
            "git_dirty": code.dirty,
            "python": platform.python_version(),
        },
        "config_hash": config.config_hash,
        "market_profile": config.market_profile.name,
        "range": {"first": study.first.isoformat(), "last": study.last.isoformat()},
        "scheme": {
            "anchored": study.scheme.anchored,
            "train_years": study.scheme.train_years,
            "test_years": study.scheme.test_years,
            "described": str(study.scheme),
        },
        "train_step": study.train_step,
        "sweep": (
            {
                "name": plan.sweep.name,
                "file": plan.sweep.source,
                "hash": plan.sweep.sweep_hash,
                "content": dict(plan.sweep.snapshot),
                "strategy": plan.strategy_id,
                "plugin": plan.plugin,
                "combinations": len(plan.combinations),
                "trials_counted": {
                    "total": plan.trials_counted,
                    "this_grid": len(set(plan.keys)),
                    "recorded_before": plan.earlier_trials,
                },
            }
            if plan is not None
            else None
        ),
        "holdout_starts": config.backtest.holdout_starts.isoformat(),
        "starting_cash": {
            "amount": str(config.backtest.starting_cash.amount),
            "currency": config.backtest.starting_cash.currency.value,
        },
        "strategies": [
            {"id": strategy_id, "plugin": plugins.get(strategy_id), "budget": str(budget)}
            for strategy_id, budget in sorted(budgets.items())
        ],
        "benchmark": {
            "instrument": str(config.market_profile.benchmark),
            "method": BENCHMARK_METHOD,
        },
        "folds": [
            {
                "number": fold.number,
                "train": _window_record(study, fold, WindowKind.TRAIN),
                "test": _window_record(study, fold, WindowKind.TEST),
                "finished": fold.number in done,
                "picked": _picked(picks.get(fold.number)),
            }
            for fold in study.folds
        ],
        "outcome": {
            "completed": failure is None,
            "failure": failure,
            "folds_planned": len(study.folds),
            "folds_finished": len(finished),
            "metrics": "metrics.json" if metrics is not None else None,
        },
        "config": config.snapshot,
    }


def _window_record(study: _Study, fold: Fold, kind: WindowKind) -> dict[str, Any]:
    window = fold.train if kind is WindowKind.TRAIN else fold.test
    record = {
        "first": window.first.isoformat(),
        "last": window.last.isoformat(),
        "run_id": f"{study.walk_forward_id}-{fold.number:02d}-{kind.value}",
        "record": fold_folder(fold, kind),
    }
    if study.plan is not None and kind is WindowKind.TRAIN:
        record["trials"] = f"{fold_folder(fold, kind)}/{TRIALS_FILE}"
    return record


def _picked(swept: SweepResult | None) -> dict[str, Any] | None:
    """What a training window's sweep picked, for ``walk_forward.json``."""
    if swept is None or swept.best is None:
        return None
    deflated = swept.deflated
    return {
        "trial": swept.best.combination.number,
        "parameters": dict(swept.best.combination.values),
        "deflated_sharpe": f"{deflated.probability:.6f}" if deflated is not None else None,
        "warnings": len(swept.warnings),
    }


def walk_forward_metrics_record(study: _Study, metrics: WalkForwardMetrics) -> dict[str, Any]:
    """The walk-forward's ``metrics.json``: the test windows chained, against the
    benchmark chained the same way. Same conventions as a backtest's ``metrics.json``.
    Each fold's own figures are in its windows' records."""
    return {
        "walk_forward_format": WALK_FORWARD_FORMAT,
        "walk_forward_id": study.walk_forward_id,
        "currency": study.config.market_profile.cash_currencies[0].value,
        "conventions": conventions_record(),
        "chaining": (
            "each test window's equity scaled to start where the previous one ended; "
            "every window starts in cash and is measured from its first close"
        ),
        "out_of_sample": series_record(metrics.out_of_sample),
        "benchmark": {
            "instrument": str(study.config.market_profile.benchmark),
            "method": BENCHMARK_METHOD,
            **series_record(metrics.benchmark),
        },
        "versus_benchmark": comparison_record(metrics.versus_benchmark),
        "test_windows": len(metrics.folds),
        "test_windows_ahead": metrics.tests_ahead,
    }


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
