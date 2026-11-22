"""The ``tyche`` command-line interface, built with Typer (ADR-0016).

Commands are thin: they parse options, call one function elsewhere in Tyche, and turn
its result or error into text and an exit code. No logic lives here.
"""

import os
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from tyche import __version__
from tyche.config import (
    HOME_ENV_VAR,
    ConfigError,
    Workspace,
    WorkspaceError,
    init_workspace,
    load_config,
    load_sweep,
    resolve_home,
)
from tyche.core.backtest import (
    BacktestError,
    BacktestMetrics,
    Fold,
    FoldScheme,
    HoldoutError,
    SeriesMetrics,
    Trial,
    WalkForwardError,
    WalkForwardMetrics,
)
from tyche.core.domain import AssetClass, Money
from tyche.core.ports import DataError
from tyche.runtime.backtest import BacktestOutcome, BacktestRequestError, run_configured_backtest
from tyche.runtime.data import (
    DEFAULT_FIRST,
    FetchOutcome,
    FetchRequestError,
    fetch_daily_histories,
    instrument_for,
)
from tyche.runtime.report import ReportError, write_report
from tyche.runtime.strategies import build_strategies
from tyche.runtime.sweep import SweepOutcome, SweepPlan, SweepResult, run_configured_sweep
from tyche.runtime.sweep_report import is_sweep, write_sweep_report
from tyche.runtime.trials import TrialCountError
from tyche.runtime.walk_forward import (
    WALK_FORWARD_FILE,
    WalkForwardOutcome,
    WindowKind,
    run_configured_walk_forward,
)
from tyche.runtime.walk_forward_report import is_walk_forward, write_walk_forward_report

app = typer.Typer(
    name="tyche",
    help="Tyche: an event-driven, agent-assisted trading framework.",
    no_args_is_help=True,
    add_completion=False,
    # Never print local variables in a traceback: they could hold secrets.
    pretty_exceptions_show_locals=False,
)

config_app = typer.Typer(
    help="Check the workspace configuration.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")

data_app = typer.Typer(
    help="Fetch market data into the workspace.",
    no_args_is_help=True,
)
app.add_typer(data_app, name="data")

MAX_ISSUES_SHOWN = 10

HomeOption = Annotated[
    Path | None,
    typer.Option(
        "--home",
        help=f"Workspace folder. Defaults to ${HOME_ENV_VAR}, then ~/tyche-workspace.",
        show_default=False,
    ),
]


def _fail(message: str) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"tyche {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Tyche: an event-driven, agent-assisted trading framework."""


@app.command()
def init(home: HomeOption = None) -> None:
    """Create a new private workspace with example configuration."""
    try:
        workspace = init_workspace(resolve_home(home, os.environ), user_home=Path.home())
    except WorkspaceError as error:
        _fail(str(error))

    typer.echo(f"Created a Tyche workspace in {workspace.root}")
    typer.echo("")
    steps = [f"Keep it versioned and private: cd {workspace.root} && git init"]
    if workspace.root != resolve_home(None, {}):
        steps.append(f"Point Tyche at it: export {HOME_ENV_VAR}={workspace.root}")
    steps.append("Check the configuration: tyche config check")
    typer.echo("Next steps:")
    for number, step in enumerate(steps, start=1):
        typer.echo(f"  {number}. {step}")


@config_app.command("check")
def config_check(home: HomeOption = None) -> None:
    """Validate the workspace configuration and show its fingerprint."""
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        config = load_config(workspace)
        configured = build_strategies(config)
    except (WorkspaceError, ConfigError) as error:
        _fail(str(error))

    typer.echo(f"Configuration is valid: {workspace.root}")
    typer.echo(f"  Market profile: {config.market_profile}")
    typer.echo(f"  Costs checked:  {config.costs.checked_on.isoformat()}")
    execution = config.market_profile.execution
    typer.echo(
        f"  Execution:      rebalance band {execution.rebalance_band}, "
        f"price buffer {execution.price_buffer}"
    )
    typer.echo("  Strategies:")
    for spec in config.strategies:
        typer.echo(f"    {spec.strategy_id} ({spec.plugin}), budget {spec.budget}")
    cash = 1 - sum(configured.budgets.values())
    if cash:
        typer.echo(f"    cash: {cash}")
    typer.echo(f"  Config hash:    {config.config_hash}")


@data_app.command("fetch")
def data_fetch(
    symbols: Annotated[
        list[str],
        typer.Argument(
            help="Symbols as the exchange lists them, e.g. SPY or BRK.B.", show_default=False
        ),
    ],
    exchange: Annotated[
        str,
        typer.Option(
            "--exchange",
            help="Listing exchange, as a market identifier code: ARCX, XNAS, XNYS, BATS or XASE.",
            show_default=False,
        ),
    ],
    asset_class: Annotated[
        AssetClass, typer.Option("--asset-class", help="Stock or ETF.")
    ] = AssetClass.ETF,
    first: Annotated[
        datetime | None,
        typer.Option(
            "--from",
            formats=["%Y-%m-%d"],
            help=f"First session date. Defaults to {DEFAULT_FIRST}.",
            show_default=False,
        ),
    ] = None,
    last: Annotated[
        datetime | None,
        typer.Option(
            "--to",
            formats=["%Y-%m-%d"],
            help="Last session date. Defaults to today.",
            show_default=False,
        ),
    ] = None,
    home: HomeOption = None,
) -> None:
    """Fetch daily bars, dividends and splits from Yahoo Finance into the workspace cache.

    Only sessions not already cached are downloaded. Every answer is checked against
    the trading calendar, and any problem found is listed. Yahoo's data is for personal
    use only.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        config = load_config(workspace)
        instruments = [
            instrument_for(symbol, exchange, asset_class, config.market_profile)
            for symbol in symbols
        ]
        outcomes = fetch_daily_histories(
            config,
            instruments,
            first.date() if first else DEFAULT_FIRST,
            last.date() if last else None,
        )
    except (WorkspaceError, ConfigError, FetchRequestError) as error:
        _fail(str(error))

    failed = 0
    for outcome in outcomes:
        if outcome.error is not None:
            failed += 1
            typer.echo(f"Error: {outcome.instrument}: {outcome.error}", err=True)
        else:
            typer.echo(_describe_fetch(outcome))
    if failed:
        raise typer.Exit(code=1)


def _describe_fetch(outcome: FetchOutcome) -> str:
    history = outcome.history
    assert history is not None
    if not history.bars:
        lines = [f"{outcome.instrument}: no bars in this range"]
    else:
        span = f"{history.bars[0].timestamp.date()} to {history.bars[-1].timestamp.date()}"
        lines = [
            f"{outcome.instrument}: {_count(len(history.bars), 'bar')}, {span}; "
            f"{_count(len(history.distributions), 'distribution')}; "
            f"{_count(len(history.splits), 'split')}"
        ]
    if history.fetched is not None:
        oldest, newest = history.fetched
        lines.append(f"  fetched {oldest:%Y-%m-%d %H:%M} to {newest:%Y-%m-%d %H:%M} UTC")
    if history.issues:
        lines.append(f"  {len(history.issues)} data issue(s):")
        for issue in history.issues[:MAX_ISSUES_SHOWN]:
            day = issue.session_day.isoformat() if issue.session_day else "(no session)"
            lines.append(f"    {day} {issue.kind}: {issue.detail}")
        if len(history.issues) > MAX_ISSUES_SHOWN:
            lines.append(f"    ... and {len(history.issues) - MAX_ISSUES_SHOWN} more")
    return "\n".join(lines)


@app.command()
def backtest(
    first: Annotated[
        datetime,
        typer.Option(
            "--from",
            formats=["%Y-%m-%d"],
            help="First session date to trade. History before it is used to warm up.",
            show_default=False,
        ),
    ],
    last: Annotated[
        datetime | None,
        typer.Option(
            "--to",
            formats=["%Y-%m-%d"],
            help="Last session date to trade. Defaults to the day before the holdout.",
            show_default=False,
        ),
    ] = None,
    home: HomeOption = None,
) -> None:
    """Backtest the configured strategies on cached history, and record the run.

    Replays the instruments listed in the market profile, from the cache only: fetch
    them first with `tyche data fetch`. A range that reaches the holdout is refused.
    The record goes to reports/backtests/ in the workspace.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        config = load_config(workspace)
        outcome = run_configured_backtest(
            config, first.date(), last.date() if last is not None else None
        )
    except (
        WorkspaceError,
        ConfigError,
        BacktestRequestError,
        HoldoutError,
        BacktestError,
        DataError,
    ) as error:
        _fail(str(error))

    for line in _describe_backtest(outcome, config.backtest.starting_cash):
        typer.echo(line)
    if outcome.metrics is not None:
        try:
            typer.echo(f"  Report:        {write_report(outcome.record_dir)}")
        except ReportError as error:
            typer.echo(f"  Report:        not written: {error}")
    run = outcome.result.run
    if not run.completed:
        typer.echo(f"Error: the run halted: {run.failure}", err=True)
        raise typer.Exit(code=1)


@app.command("walk-forward")
def walk_forward(
    first: Annotated[
        datetime,
        typer.Option(
            "--from",
            formats=["%Y-%m-%d"],
            help="First day of the first training window. History before it is used to warm up.",
            show_default=False,
        ),
    ],
    last: Annotated[
        datetime | None,
        typer.Option(
            "--to",
            formats=["%Y-%m-%d"],
            help="Last day of the last test window. Defaults to the day before the holdout.",
            show_default=False,
        ),
    ] = None,
    train_years: Annotated[
        int,
        typer.Option(
            "--train-years",
            min=1,
            help="Calendar years in the first training window (in every one, with --rolling).",
        ),
    ] = 5,
    test_years: Annotated[
        int,
        typer.Option("--test-years", min=1, help="Calendar years in each test window."),
    ] = 1,
    rolling: Annotated[
        bool,
        typer.Option(
            "--rolling",
            help="Keep every training window at --train-years instead of growing it.",
        ),
    ] = False,
    sweep: Annotated[
        str | None,
        typer.Option(
            "--sweep",
            help=(
                "A sweep in config/sweeps/: run every combination on each training "
                "window, and test the one with the highest Sharpe ratio."
            ),
            show_default=False,
        ),
    ] = None,
    home: HomeOption = None,
) -> None:
    """Walk forward: backtest each training window and the test window after it.

    Cuts the range into folds of whole calendar years. Each window is a backtest of
    its own, from the starting cash, on cached history. In-sample (training) and
    out-of-sample (test) results are reported separately, and the test windows are
    joined into one out-of-sample result against the benchmark. With --sweep, each
    training window picks the parameters its test window runs. The record and its
    report go to reports/walk_forward/ in the workspace.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        config = load_config(workspace)
        spec = load_sweep(config, sweep) if sweep is not None else None
        scheme = FoldScheme(train_years, test_years, anchored=not rolling)
        typer.echo(f"Walk-forward, {scheme}")
        if spec is not None:
            typer.echo(f"  Train step: sweep {spec.name} ({spec.source}), highest Sharpe ratio")
        outcome = run_configured_walk_forward(
            config,
            first.date(),
            last.date() if last is not None else None,
            scheme,
            progress=_describe_window,
            sweep=spec,
        )
    except (
        WorkspaceError,
        ConfigError,
        BacktestRequestError,
        HoldoutError,
        BacktestError,
        WalkForwardError,
        TrialCountError,
        DataError,
    ) as error:
        _fail(str(error))

    for line in _describe_walk_forward(outcome):
        typer.echo(line)
    if outcome.metrics is not None:
        try:
            typer.echo(f"  Report:        {write_walk_forward_report(outcome.record_dir)}")
        except ReportError as error:
            typer.echo(f"  Report:        not written: {error}")
    if not outcome.completed:
        typer.echo(f"Error: the walk-forward stopped: {outcome.failure}", err=True)
        raise typer.Exit(code=1)


@app.command()
def sweep(
    name: Annotated[
        str,
        typer.Argument(
            help="The sweep's name: config/sweeps/<name>.toml in the workspace.",
            show_default=False,
        ),
    ],
    first: Annotated[
        datetime,
        typer.Option(
            "--from",
            formats=["%Y-%m-%d"],
            help="First session date to trade. History before it is used to warm up.",
            show_default=False,
        ),
    ],
    last: Annotated[
        datetime | None,
        typer.Option(
            "--to",
            formats=["%Y-%m-%d"],
            help="Last session date to trade. Defaults to the day before the holdout.",
            show_default=False,
        ),
    ] = None,
    home: HomeOption = None,
) -> None:
    """Run every combination of a parameter sweep, and pick the highest Sharpe ratio.

    Each combination is a backtest over the same days, on cached history. The pick is
    reported with a deflated Sharpe ratio, which discounts it for every distinct trial
    of the plugin recorded in the workspace, and with warnings about overfitting. The
    pick is in-sample: for an out-of-sample result, use `tyche walk-forward --sweep`.
    The record and its report go to reports/sweeps/ in the workspace.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        config = load_config(workspace)
        spec = load_sweep(config, name)
        outcome = run_configured_sweep(
            config,
            spec,
            first.date(),
            last.date() if last is not None else None,
            progress=_describe_trial,
            planned=_describe_plan,
        )
    except (
        WorkspaceError,
        ConfigError,
        BacktestRequestError,
        HoldoutError,
        BacktestError,
        TrialCountError,
        DataError,
    ) as error:
        _fail(str(error))

    for line in _describe_sweep(outcome):
        typer.echo(line)
    if outcome.pick is not None:
        try:
            typer.echo(f"  Report:        {write_sweep_report(outcome.record_dir)}")
        except ReportError as error:
            typer.echo(f"  Report:        not written: {error}")
    else:
        typer.echo("Error: no trial has a Sharpe ratio, so nothing was picked", err=True)
        raise typer.Exit(code=1)


@app.command()
def report(
    run_id: Annotated[
        str,
        typer.Argument(
            help="The backtest's, walk-forward's or sweep's id, as Tyche printed it.",
            show_default=False,
        ),
    ],
    home: HomeOption = None,
) -> None:
    """Write report.html for a recorded backtest, walk-forward or sweep, from its record.

    `tyche backtest`, `tyche walk-forward` and `tyche sweep` write the report
    themselves; this rebuilds it, for a run recorded before reports existed or after
    the report changed. It reads only the record folder in reports/backtests/,
    reports/walk_forward/ or reports/sweeps/, never the cache.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
    except WorkspaceError as error:
        _fail(str(error))
    folders = [
        workspace.reports_dir / "backtests",
        workspace.reports_dir / "walk_forward",
        workspace.reports_dir / "sweeps",
    ]
    found = [f / run_id for f in folders if (f / run_id).is_dir()]
    if not run_id or Path(run_id).name != run_id or not found:
        _fail(
            f"no backtest, walk-forward or sweep record named {run_id!r} in {workspace.reports_dir}"
        )
    folder = found[0]
    try:
        if is_walk_forward(folder):
            path = write_walk_forward_report(folder)
        elif is_sweep(folder):
            path = write_sweep_report(folder)
        else:
            path = write_report(folder)
    except ReportError as error:
        _fail(str(error))
    typer.echo(f"Report: {path}")


def _describe_backtest(outcome: BacktestOutcome, starting: Money) -> list[str]:
    result = outcome.result
    record = outcome.record_dir / "run.json"
    sessions = sum(len(found) for found in result.sessions.values())
    warm_up = [s for found in result.warm_up.values() for s in found]
    currency = starting.currency
    lines = [
        f"Backtest {outcome.run_id}: {'completed' if result.run.completed else 'halted'}",
        f"  Range:         {outcome.first} to {outcome.last}, {_count(sessions, 'session')}",
    ]
    if warm_up:
        lines.append(
            f"  Warm-up:       {_count(len(warm_up), 'session')} from {warm_up[0].day} "
            f"({result.warm_up_needed} needed)"
        )
    else:
        lines.append(f"  Warm-up:       none ({result.warm_up_needed} needed)")
    equity = result.account.equity(currency).amount
    change = ((equity - starting.amount) / starting.amount * 100).quantize(Decimal("0.01"))
    lines.append(f"  Starting cash: {starting}")
    lines.append(f"  Final equity:  {equity.quantize(Decimal('0.01'))} {currency} ({change:+}%)")
    lines.append(
        f"  Fills:         {len(result.fills)}; free-riding violations: {len(result.free_riding)}"
    )
    issues = sum(len(h.issues) for h in result.histories)
    if issues:
        lines.append(f"  Data issues:   {issues}, listed by `tyche data fetch`")
    if outcome.metrics is not None:
        lines.extend(_describe_metrics(outcome.metrics))
    else:
        lines.append(f"  Metrics:       not measured: {outcome.metrics_error}")
    lines.append(f"  Code:          {outcome.code}")
    lines.append(f"  Record:        {record}")
    if outcome.code.dirty:
        lines.append(
            "Warning: the code had uncommitted changes, so its commit alone does not "
            "reproduce this run."
        )
    return lines


def _describe_metrics(metrics: BacktestMetrics) -> list[str]:
    """The run beside its benchmark's total return, one figure per line."""
    strategy, bench = metrics.strategy, metrics.benchmark
    benchmark = f"{metrics.benchmark_instrument} total return"
    rows = [
        ("CAGR", _percent(strategy.cagr), _percent(bench.cagr)),
        ("Volatility", _percent(strategy.volatility), _percent(bench.volatility)),
        ("Sharpe (rf 0)", _ratio(strategy.sharpe), _ratio(bench.sharpe)),
        ("Sortino (rf 0)", _ratio(strategy.sortino), _ratio(bench.sortino)),
        ("Max drawdown", _percent(_depth(strategy)), _percent(_depth(bench))),
        ("Exposure", _percent(strategy.exposure), _percent(bench.exposure)),
    ]
    lines = [f"  {'Metrics':<16}{'strategy':>10}  {benchmark}"]
    lines.extend(f"    {name:<14}{mine:>10}  {theirs:>10}" for name, mine, theirs in rows)
    trades = metrics.trades
    win_rate = _percent(trades.win_rate)
    lines.append(
        f"  Turnover:      {_ratio(metrics.turnover)} a year; costs {metrics.costs.round_to(2)}"
    )
    lines.append(
        f"  Trades:        {len(trades.closed)} closed, win rate {win_rate}; "
        f"{trades.still_open} still open"
    )
    return lines


def _describe_window(
    fold: Fold, kind: WindowKind, outcome: BacktestOutcome, picked: Mapping[str, Any] | None
) -> None:
    """One line per window, printed as soon as it is recorded, and the training
    window's pick when a sweep chose it."""
    window = fold.train if kind is WindowKind.TRAIN else fold.test
    head = f"  Fold {fold.number:>2} {kind.value:<5} {window.first} to {window.last}"
    if picked is not None:
        typer.echo(f"{head}  picked {_parameters(picked)}")
    metrics = outcome.metrics
    if not outcome.result.run.completed:
        typer.echo(f"{head}  halted")
    elif metrics is None:
        typer.echo(f"{head}  not measured")
    elif kind is WindowKind.TRAIN:
        typer.echo(
            f"{head}  CAGR {_percent(metrics.strategy.cagr):>8}  "
            f"benchmark {_percent(metrics.benchmark.cagr):>8}"
        )
    else:
        typer.echo(
            f"{head}  return {_percent(metrics.strategy.total_return):>8}  "
            f"benchmark {_percent(metrics.benchmark.total_return):>8}"
        )


def _describe_plan(plan: SweepPlan) -> None:
    """Printed before the first trial runs."""
    counted = plan.trials_counted
    typer.echo(
        f"Sweep {plan.sweep.name}: {len(plan.combinations)} combinations of "
        f"{plan.strategy_id} ({plan.plugin}); {counted} trials counted with the "
        f"{plan.earlier_trials} already recorded"
    )


def _describe_trial(plan: SweepPlan, trial: Trial) -> None:
    """One line per trial, printed as soon as it is measured."""
    number = trial.combination.number
    head = f"  Trial {number:>3}/{len(plan.combinations)}  {_parameters(trial.combination.values)}"
    metrics = trial.metrics
    if metrics is None:
        typer.echo(f"{head}  {trial.failure}")
        return
    sharpe, cagr = _ratio(metrics.strategy.sharpe), _percent(metrics.strategy.cagr)
    typer.echo(f"{head}  Sharpe {sharpe:>6}  CAGR {cagr:>8}")


def _describe_sweep(outcome: SweepOutcome) -> list[str]:
    result: SweepResult = outcome.result
    best = result.best
    measured = sum(1 for t in result.trials if t.metrics is not None)
    lines = [
        f"Sweep {outcome.sweep_id}: {len(result.trials)} trials, {measured} measured",
    ]
    if best is not None and best.metrics is not None:
        lines.append(
            f"  Pick:          trial {best.combination.number}, "
            f"{_parameters(best.combination.values)} (in-sample)"
        )
        lines.extend(_describe_metrics(best.metrics))
    deflated = result.deflated
    if deflated is not None:
        verdict = "significant" if deflated.significant else "not significant"
        lines.append(
            f"  Deflated Sharpe ratio: {deflated.probability:.1%} after "
            f"{deflated.trials} trials ({verdict} at 95%)"
        )
    elif result.deflation_error is not None:
        lines.append(f"  Deflated Sharpe ratio: not computed: {result.deflation_error}")
    for warning in result.warnings:
        lines.append(f"Warning: {warning}")
    lines.append(f"  Code:          {outcome.code}")
    lines.append(f"  Record:        {outcome.record_dir}")
    if outcome.code.dirty:
        lines.append(
            "Warning: the code had uncommitted changes, so its commit alone does not "
            "reproduce this sweep."
        )
    return lines


def _parameters(values: Mapping[str, Any]) -> str:
    return " ".join(f"{name}={value}" for name, value in values.items())


def _describe_walk_forward(outcome: WalkForwardOutcome) -> list[str]:
    finished, planned = len(outcome.finished), len(outcome.folds)
    state = "completed" if outcome.completed else "stopped"
    lines = [f"Walk-forward {outcome.walk_forward_id}: {state}, {finished} of {planned} folds"]
    if outcome.metrics is not None:
        lines.extend(_describe_out_of_sample(outcome.metrics))
    lines.append(f"  Code:          {outcome.code}")
    lines.append(f"  Record:        {outcome.record_dir / WALK_FORWARD_FILE}")
    if outcome.code.dirty:
        lines.append(
            "Warning: the code had uncommitted changes, so its commit alone does not "
            "reproduce this walk-forward."
        )
    return lines


def _describe_out_of_sample(metrics: WalkForwardMetrics) -> list[str]:
    """The test windows joined, beside the benchmark joined the same way."""
    mine, bench = metrics.out_of_sample, metrics.benchmark
    first = metrics.folds[0].fold.test.first
    last = metrics.folds[-1].fold.test.last
    benchmark = f"{metrics.folds[0].test.benchmark_instrument} total return"
    rows = [
        ("CAGR", _percent(mine.cagr), _percent(bench.cagr)),
        ("Volatility", _percent(mine.volatility), _percent(bench.volatility)),
        ("Sharpe (rf 0)", _ratio(mine.sharpe), _ratio(bench.sharpe)),
        ("Max drawdown", _percent(_depth(mine)), _percent(_depth(bench))),
        ("Exposure", _percent(mine.exposure), _percent(bench.exposure)),
    ]
    lines = [
        f"  Out of sample: {first} to {last}, the test windows joined",
        f"  {'Metrics':<16}{'strategy':>10}  {benchmark}",
    ]
    lines.extend(f"    {name:<14}{ours:>10}  {theirs:>10}" for name, ours, theirs in rows)
    lines.append(
        f"  Ahead of the benchmark in {metrics.tests_ahead} of {len(metrics.folds)} test windows"
    )
    return lines


def _percent(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{(value * 100).quantize(Decimal('0.01'))}%"


def _ratio(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value.quantize(Decimal('0.01'))}"


def _depth(series: SeriesMetrics) -> Decimal:
    return series.max_drawdown.depth if series.max_drawdown is not None else Decimal(0)


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}{'' if number == 1 else 's'}"


def main() -> None:
    """Entry point for the ``tyche`` console script and ``python -m tyche``."""
    app(prog_name="tyche")
