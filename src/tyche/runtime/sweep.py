"""Wiring for ``tyche sweep``: a grid of parameters run, the pick, and its record (ADR-0030).

Composition-root code (ADR-0004). It reads a sweep file (``load_sweep``), checks every
combination by building it before anything runs, counts the trials already recorded
for the plugin (``recorded_trial_keys``), and runs each combination as a backtest over
the same days through the same path as ``tyche backtest`` (``run_and_measure``). The
pick is the trial with the highest Sharpe ratio; its Sharpe ratio is deflated for
every trial counted.

The same sweep runs on each training window of a walk-forward
(``tyche walk-forward --sweep``); this module holds what both share.

What a sweep keeps (ADR-0030): one ``trials.json`` with every combination's parameters
and results, and the pick's full backtest record. The other trials' equity and fills
are not kept: any of them can be run again from its parameters and the config hash.
A standalone sweep writes to ``reports/sweeps/<id>/``:

* ``sweep.json``: what ran (code, config hash and every setting, the sweep file and
  its hash, the range) and how it ended.
* ``trials.json``: every trial, the pick, the deflated Sharpe ratio and the warnings.
* ``pick/``: the pick's full backtest record, as ``tyche backtest`` writes it, without
  a report of its own.
* ``report.html``.
"""

import json
import math
import platform
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tyche.adapters.clocks import SystemClock
from tyche.config import ConfigError, SweepSpec, TycheConfig
from tyche.core.backtest import (
    CONFIDENCE,
    Combination,
    DeflatedSharpe,
    Grid,
    SweepError,
    Trial,
    combinations,
    deflated_sharpe,
    overfitting_warnings,
    pick,
    return_moments,
    session_sharpe,
    trial_key,
)
from tyche.core.backtest.metrics import SESSIONS_PER_YEAR, Drawdown, equity_points
from tyche.core.domain import Currency
from tyche.core.ports import Clock
from tyche.runtime.backtest import (
    BENCHMARK_METHOD,
    BacktestOutcome,
    CachedMarket,
    CodeVersion,
    MeasuredRun,
    cached_market,
    cents,
    checked_range,
    current_code_version,
    new_run_id,
    record_run,
    run_and_measure,
)
from tyche.runtime.strategies import ConfiguredStrategies, build_strategies
from tyche.runtime.trials import TRIALS_FILE, recorded_trial_keys

SWEEP_FORMAT = 1
"""Version of the layout of ``sweep.json`` and ``trials.json``. Raised when a field
changes meaning or goes away."""

SWEEP_FILE = "sweep.json"
PICK_FOLDER = "pick"

RULE = "the highest Sharpe ratio (risk-free rate 0); the first in the grid's order on a tie"
"""How the pick is chosen, as records state it."""

_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """A sweep checked against the configuration, before anything runs.

    Attributes:
        config: The workspace configuration the sweep runs in.
        sweep: The sweep file, read.
        plugin: The swept strategy's plugin.
        version: The plugin's version: a change of rules is a new trial.
        base_parameters: The strategy file's parameters, which the grid overrides.
        grid: The values tried.
        combinations: Every combination, in the grid's order.
        keys: Each combination's ``trial_key``, in the same order.
        earlier_trials: Distinct trials of the plugin recorded before this sweep.
        trials_counted: ``N``: earlier trials and this grid's, each distinct trial once.
        longest: The number of the combination whose strategy needs the most history:
            it runs first, so that history missing from the cache stops the sweep
            before any other trial has run.
    """

    config: TycheConfig
    sweep: SweepSpec
    plugin: str
    version: str
    base_parameters: Mapping[str, Any]
    grid: Grid
    combinations: tuple[Combination, ...]
    keys: tuple[str, ...]
    earlier_trials: int
    trials_counted: int
    longest: int = 1

    @property
    def strategy_id(self) -> str:
        return self.sweep.strategy_id

    def strategies(self, combination: Combination) -> ConfiguredStrategies:
        """The configured strategies, with ``combination`` applied to the swept one."""
        return build_strategies(
            self.config, {self.strategy_id: combination.values}, source=self.sweep.source
        )


def plan_sweep(config: TycheConfig, sweep: SweepSpec) -> SweepPlan:
    """Check every combination of ``sweep`` by building it, and count the trials.

    Raises:
        ConfigError: A combination cannot be built: an unknown parameter, a wrong type
            or a value the plugin refuses, named with the sweep file.
        TrialCountError: A record cannot be read to count trials.
    """
    spec = next(s for s in config.strategies if s.strategy_id == sweep.strategy_id)
    try:
        grid = Grid(sweep.grid)
    except SweepError as error:
        raise ConfigError(f"{sweep.source}: {error}") from None
    found = combinations(grid)
    version = ""
    keys: list[str] = []
    lookbacks: list[int] = []
    for combination in found:
        built = build_strategies(
            config, {sweep.strategy_id: combination.values}, source=sweep.source
        )
        swept = next(s for s in built.strategies if s.strategy_id == sweep.strategy_id)
        version = swept.version
        lookbacks.append(swept.lookback)
        keys.append(trial_key(spec.plugin, version, built.parameters[sweep.strategy_id]))
    earlier = recorded_trial_keys(config.workspace.reports_dir, spec.plugin)
    return SweepPlan(
        config=config,
        sweep=sweep,
        plugin=spec.plugin,
        version=version,
        base_parameters=dict(spec.parameters),
        grid=grid,
        combinations=found,
        keys=tuple(keys),
        earlier_trials=len(earlier),
        trials_counted=len(earlier | set(keys)),
        longest=found[lookbacks.index(max(lookbacks))].number,
    )


TrialProgress = Callable[[SweepPlan, Trial], None]
"""Told about every trial as soon as it is measured, for the command to print."""


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Every combination of a sweep run over one range, and the pick.

    Attributes:
        plan: What was run.
        first: The first day every trial ran.
        last: The last day.
        trials: Every trial, in the grid's order.
        best: The pick; ``None`` if no trial has a Sharpe ratio.
        best_run: The pick's run, kept in full for its record.
        deflated: The pick's deflated Sharpe ratio; ``None`` if it cannot be computed.
        deflation_error: Why not, or ``None``.
        warnings: What should make a reader wary of the pick.
    """

    plan: SweepPlan
    first: date
    last: date
    trials: tuple[Trial, ...]
    best: Trial | None
    best_run: MeasuredRun | None
    deflated: DeflatedSharpe | None
    deflation_error: str | None
    warnings: tuple[str, ...]


def run_sweep(
    plan: SweepPlan,
    market: CachedMarket,
    *,
    run_id: str,
    first: date,
    last: date,
    clock: Clock,
    code: CodeVersion,
    progress: TrialProgress | None = None,
) -> SweepResult:
    """Run every combination of ``plan`` from ``first`` to ``last`` and pick the best.

    The combination needing the most history runs first (``plan.longest``), then the
    others in the grid's order; trials are returned in the grid's order whatever the
    order they ran in. Only the best run so far is kept in memory; the others leave
    their figures in the trial they become.

    Raises:
        BacktestRequestError: History is missing from the cache.
        HoldoutError: ``last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run.
    """
    currency = plan.config.market_profile.cash_currencies[0]
    trials: list[Trial] = []
    best_run: MeasuredRun | None = None
    leader: tuple[Decimal, int] | None = None
    first_run = next(c for c in plan.combinations if c.number == plan.longest)
    order = [first_run, *(c for c in plan.combinations if c is not first_run)]
    for combination in order:
        run = run_and_measure(
            plan.config,
            market,
            plan.strategies(combination),
            run_id=f"{run_id}-t{combination.number:03d}",
            first=first,
            last=last,
            clock=clock,
            code=code,
        )
        trial = _trial(combination, run, currency)
        trials.append(trial)
        sharpe = trial.sharpe
        # The same rule as ``pick``: the highest Sharpe ratio, then the lowest number.
        if sharpe is not None and (leader is None or (sharpe, -combination.number) > leader):
            best_run, leader = run, (sharpe, -combination.number)
        if progress is not None:
            progress(plan, trial)

    trials.sort(key=lambda t: t.combination.number)
    best = pick(trials)
    deflated: DeflatedSharpe | None = None
    deflation_error: str | None = None
    if best is not None and best_run is not None:
        moments = return_moments(equity_points(best_run.result, currency))
        sharpes = [t.session_sharpe for t in trials if t.session_sharpe is not None]
        if moments is None:
            deflation_error = "the pick's daily returns have no variation"
        else:
            try:
                deflated = deflated_sharpe(moments, sharpes, plan.trials_counted)
            except SweepError as error:
                deflation_error = str(error)
    warnings = overfitting_warnings(plan.grid, trials, best, deflated, deflation_error)
    return SweepResult(
        plan, first, last, tuple(trials), best, best_run, deflated, deflation_error, warnings
    )


def _trial(combination: Combination, run: MeasuredRun, currency: Currency) -> Trial:
    if not run.result.run.completed:
        return Trial(combination, None, None, f"halted: {run.result.run.failure}")
    if run.metrics is None:
        return Trial(combination, None, None, f"not measured: {run.metrics_error}")
    halt = run.result.halt
    return Trial(
        combination,
        run.metrics,
        session_sharpe(equity_points(run.result, currency)),
        halted_at=halt.at if halt is not None else None,
    )


# --- the standalone sweep -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SweepOutcome:
    """A finished sweep and where its record was written.

    Attributes:
        sweep_id: Identifies it, and names its folder.
        record_dir: ``reports/sweeps/<id>/``.
        code: Which code ran.
        result: Every trial and the pick.
        pick: The pick's recorded backtest; ``None`` if nothing was picked.
    """

    sweep_id: str
    record_dir: Path
    code: CodeVersion
    result: SweepResult
    pick: BacktestOutcome | None


def run_configured_sweep(
    config: TycheConfig,
    sweep: SweepSpec,
    first: date,
    last: date | None = None,
    *,
    clock: Clock | None = None,
    code: CodeVersion | None = None,
    progress: TrialProgress | None = None,
    planned: Callable[[SweepPlan], None] | None = None,
) -> SweepOutcome:
    """Sweep from ``first`` to ``last``, and record every trial and the pick.

    ``last`` defaults to the day before the holdout. ``planned`` is told about the
    plan before the first trial runs.

    Raises:
        BacktestRequestError: The range cannot be run as asked, or history is missing.
        HoldoutError: ``last`` reaches the holdout.
        BacktestError: The range or the setup cannot be run.
        ConfigError: A combination cannot be built.
        TrialCountError: A record cannot be read to count trials.
    """
    clock = clock or SystemClock()
    code = code or current_code_version()
    last = checked_range(config, first, last)
    plan = plan_sweep(config, sweep)
    if planned is not None:
        planned(plan)
    root = config.workspace.reports_dir / "sweeps"
    started = clock.now()
    sweep_id = new_run_id(root, started, config.config_hash)
    folder = root / sweep_id
    result = run_sweep(
        plan,
        cached_market(config, last, clock),
        run_id=sweep_id,
        first=first,
        last=last,
        clock=clock,
        code=code,
        progress=progress,
    )
    folder.mkdir(parents=True)
    recorded: BacktestOutcome | None = None
    if result.best is not None and result.best_run is not None:
        recorded = record_run(
            config,
            result.best_run,
            folder=folder / PICK_FOLDER,
            code=code,
            part_of={"sweep": sweep_id, "trial": result.best.combination.number},
        )
    write_trials(folder, result, pick_record=PICK_FOLDER if recorded else None)
    _write_json(
        folder / SWEEP_FILE,
        sweep_record(sweep_id, result, code, started=started, finished=clock.now()),
    )
    return SweepOutcome(sweep_id, folder, code, result, recorded)


# --- the record -----------------------------------------------------------------------


def write_trials(folder: Path, result: SweepResult, *, pick_record: str | None) -> None:
    """Write ``trials.json`` into ``folder``, which must exist."""
    _write_json(folder / TRIALS_FILE, trials_record(result, pick_record))


def trials_record(result: SweepResult, pick_record: str | None) -> dict[str, Any]:
    """``trials.json``: every trial, the pick, its deflated Sharpe ratio, the warnings.

    Each trial's ``key`` is what ``recorded_trial_keys`` counts. Figures follow
    ``metrics.json``'s conventions: fractions and ratios as strings to six places.
    """
    plan, best = result.plan, result.best
    measured = next((t.metrics for t in result.trials if t.metrics is not None), None)
    return {
        "sweep_format": SWEEP_FORMAT,
        "sweep": plan.sweep.name,
        "sweep_file": plan.sweep.source,
        "sweep_hash": plan.sweep.sweep_hash,
        "strategy": plan.strategy_id,
        "plugin": plan.plugin,
        "version": plan.version,
        "base_parameters": dict(plan.base_parameters),
        "grid": {name: list(values) for name, values in plan.grid.values.items()},
        "range": {"first": result.first.isoformat(), "last": result.last.isoformat()},
        "rule": RULE,
        "benchmark": (
            {
                "instrument": str(measured.benchmark_instrument),
                "method": BENCHMARK_METHOD,
                "cagr": _fraction(measured.benchmark.cagr),
                "sharpe": _fraction(measured.benchmark.sharpe),
                "max_drawdown": _fraction(_depth(measured.benchmark.max_drawdown)),
            }
            if measured is not None
            else None
        ),
        "trials": [
            _trial_record(trial, key) for trial, key in zip(result.trials, plan.keys, strict=True)
        ],
        "pick": (
            {
                "number": best.combination.number,
                "parameters": dict(best.combination.values),
                "record": pick_record,
            }
            if best is not None
            else None
        ),
        "trials_counted": {
            "total": plan.trials_counted,
            "this_grid": len(set(plan.keys)),
            "recorded_before": plan.earlier_trials,
        },
        "deflated_sharpe": _deflated_record(result.deflated),
        "deflation_error": result.deflation_error,
        "warnings": list(result.warnings),
    }


def _trial_record(trial: Trial, key: str) -> dict[str, Any]:
    metrics = trial.metrics
    record: dict[str, Any] = {
        "number": trial.combination.number,
        "parameters": dict(trial.combination.values),
        "key": key,
        "measured": metrics is not None,
        "failure": trial.failure,
        "halted_at": trial.halted_at.isoformat() if trial.halted_at is not None else None,
    }
    if metrics is None:
        return record
    strategy, trades = metrics.strategy, metrics.trades
    return {
        **record,
        "sharpe": _fraction(strategy.sharpe),
        "session_sharpe": _float(trial.session_sharpe),
        "cagr": _fraction(strategy.cagr),
        "total_return": _fraction(strategy.total_return),
        "volatility": _fraction(strategy.volatility),
        "max_drawdown": _fraction(_depth(strategy.max_drawdown)),
        "exposure": _fraction(strategy.exposure),
        "turnover": _fraction(metrics.turnover),
        "costs": cents(metrics.costs.amount),
        "closed_trades": len(trades.closed),
        "win_rate": _fraction(trades.win_rate),
        "versus_benchmark": {
            "cagr": _fraction(metrics.versus_benchmark.cagr),
            "sharpe": _fraction(metrics.versus_benchmark.sharpe),
        },
    }


def _deflated_record(deflated: DeflatedSharpe | None) -> dict[str, Any] | None:
    if deflated is None:
        return None
    annual = math.sqrt(SESSIONS_PER_YEAR)
    moments = deflated.moments
    return {
        "probability": _float(deflated.probability),
        "confidence": str(CONFIDENCE),
        "significant": deflated.significant,
        "trials": deflated.trials,
        "variance_of_sharpes": _float(deflated.variance, places=10),
        "threshold": _float(deflated.threshold),
        "threshold_annualised": _float(deflated.threshold * annual),
        "sharpe": _float(moments.sharpe),
        "sharpe_annualised": _float(moments.sharpe * annual),
        "returns": moments.count,
        "skewness": _float(moments.skewness),
        "kurtosis": _float(moments.kurtosis),
        "per": "session; annualised by sqrt(252) where marked",
        "source": (
            "Bailey and Lopez de Prado (2014), The Deflated Sharpe Ratio, "
            "Journal of Portfolio Management, equations 1 and 2"
        ),
    }


def sweep_record(
    sweep_id: str,
    result: SweepResult,
    code: CodeVersion,
    *,
    started: datetime,
    finished: datetime,
) -> dict[str, Any]:
    """``sweep.json``: what ran, and how it ended."""
    plan = result.plan
    config = plan.config
    measured = sum(1 for t in result.trials if t.metrics is not None)
    return {
        "sweep_format": SWEEP_FORMAT,
        "sweep_id": sweep_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "code": {
            "tyche_version": code.tyche,
            "git_commit": code.commit,
            "git_dirty": code.dirty,
            "python": platform.python_version(),
        },
        "config_hash": config.config_hash,
        "market_profile": config.market_profile.name,
        "range": {"first": result.first.isoformat(), "last": result.last.isoformat()},
        "holdout_starts": config.backtest.holdout_starts.isoformat(),
        "starting_cash": {
            "amount": str(config.backtest.starting_cash.amount),
            "currency": config.backtest.starting_cash.currency.value,
        },
        "strategies": [
            {"id": s.strategy_id, "plugin": s.plugin, "budget": str(s.budget)}
            for s in config.strategies
        ],
        "sweep": {
            "name": plan.sweep.name,
            "file": plan.sweep.source,
            "hash": plan.sweep.sweep_hash,
            "content": dict(plan.sweep.snapshot),
        },
        "rule": RULE,
        "outcome": {
            "trials": len(result.trials),
            "measured": measured,
            "picked": result.best.combination.number if result.best is not None else None,
            "trials_file": TRIALS_FILE,
            "pick_record": PICK_FOLDER if result.best is not None else None,
        },
        "config": config.snapshot,
    }


def _fraction(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_PLACES))


def _float(value: float | None, places: int = 6) -> str | None:
    return None if value is None else f"{value:.{places}f}"


def _depth(drawdown: Drawdown | None) -> Decimal:
    return drawdown.depth if drawdown is not None else Decimal(0)


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
