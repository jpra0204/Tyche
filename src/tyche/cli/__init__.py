"""The ``tyche`` command-line interface, built with Typer (ADR-0016).

Commands are thin: they parse options, call one function elsewhere in Tyche, and turn
its result or error into text and an exit code. No logic lives here.
"""

import logging
import os
import webbrowser
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from tyche import __version__
from tyche.api import DEFAULT_PORT, HOST, create_app, default_app_dir, new_token, serve
from tyche.config import (
    HOME_ENV_VAR,
    ConfigError,
    EnvFileError,
    Workspace,
    WorkspaceError,
    ibkr_connection,
    init_workspace,
    load_config,
    load_secrets,
    load_sweep,
    readable_by_others,
    resolve_home,
)
from tyche.core.backtest import (
    BacktestError,
    BacktestMetrics,
    BacktestResult,
    CapitalError,
    Fold,
    FoldScheme,
    HoldoutError,
    SeriesMetrics,
    Trial,
    WalkForwardError,
    WalkForwardMetrics,
)
from tyche.core.domain import (
    ORDER_RULES,
    AssetClass,
    Instrument,
    Kill,
    MarketProfile,
    Money,
    RiskRule,
    WorkingOrder,
)
from tyche.core.ports import DataError
from tyche.core.risk import DEFAULT_RISK_PROFILE
from tyche.runtime.backtest import (
    BacktestOutcome,
    BacktestRequestError,
    adjustments_record,
    current_code_version,
    run_configured_backtest,
)
from tyche.runtime.capital import (
    DEFAULT_AMOUNTS,
    DEFAULT_POSITIONS,
    DEFAULT_REFERENCE,
    DEFAULT_TOLERANCE,
    CapitalOutcome,
    CapitalRequest,
    SizedRun,
    run_configured_capital,
)
from tyche.runtime.capital_report import PLAN_NAMES, is_capital, write_capital_report
from tyche.runtime.data import (
    DEFAULT_FIRST,
    FetchOutcome,
    FetchRequestError,
    fetch_daily_histories,
    followed_instruments,
    instrument_for,
)
from tyche.runtime.kill_switch import (
    KillSwitchError,
    TradingStatus,
    engage_kill,
    resume,
    status,
)
from tyche.runtime.logs import open_logs
from tyche.runtime.notify import (
    ChannelCheckError,
    Delivery,
    check_channel,
    notify_kill,
    notify_resume,
)
from tyche.runtime.paper import PaperOutcome, PaperRunError, run_paper
from tyche.runtime.profiles import (
    PROFILES_FILE,
    ProfileRun,
    chosen_profiles,
    is_profile_comparison,
    run_profile_comparison,
)
from tyche.runtime.profiles_report import write_profiles_report
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

notify_app = typer.Typer(
    help="Check the Discord channel that receives alerts.",
    no_args_is_help=True,
)
app.add_typer(notify_app, name="notify")

data_app = typer.Typer(
    help="Fetch market data into the workspace.",
    no_args_is_help=True,
)
app.add_typer(data_app, name="data")

paper_app = typer.Typer(
    help="Trade on the IBKR paper account.",
    no_args_is_help=True,
)
app.add_typer(paper_app, name="paper")

MAX_ISSUES_SHOWN = 10

_log = logging.getLogger("tyche.cli")

RiskProfileOption = Annotated[
    str,
    typer.Option(
        "--risk-profile",
        help="Risk profile the risk gate applies: a file in config/risk/.",
    ),
]

HomeOption = Annotated[
    Path | None,
    typer.Option(
        "--home",
        help=f"Workspace folder. Defaults to ${HOME_ENV_VAR}, then ~/tyche-workspace.",
        show_default=False,
    ),
]


def _fail(message: str) -> NoReturn:
    _log.error("command failed: %s", message)
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
def config_check(
    home: HomeOption = None,
    risk_profile: Annotated[
        str,
        typer.Option(
            "--risk-profile",
            help="Risk profile to check the strategies' own limits against.",
        ),
    ] = DEFAULT_RISK_PROFILE,
) -> None:
    """Validate the workspace configuration and show its fingerprint."""
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "config check")
        config = load_config(workspace, risk_profile)
        configured = build_strategies(config)
        secrets = load_secrets(workspace.env_file, os.environ)
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
    profile = config.risk_profile
    typer.echo(
        f"  Risk profile:   {profile.name}: risk per trade {profile.risk_per_trade}, "
        f"{profile.max_open_positions} positions, position size {profile.max_position_size}, "
        f"daily loss {profile.daily_loss_limit}, drawdown kill {profile.drawdown_kill}"
    )
    others = [name for name in config.risk_profiles if name != profile.name]
    if others:
        typer.echo(f"                  also within the guardrails: {', '.join(others)}")
    guardrails = config.guardrails
    caps = ", ".join(
        f"capital {capital}, order {guardrails.order_cap(capital.currency)}"
        for capital in guardrails.max_total_capital
    )
    typer.echo(f"  Guardrails:     long only, no leverage; {caps}")
    typer.echo(
        "                  (applied: risk per trade, positions, position size, the daily "
        "loss limit and the drawdown kill in every run; long only and no leverage in every "
        "run; the money caps in paper and live)"
    )
    typer.echo("  Strategies:")
    for spec in config.strategies:
        typer.echo(f"    {spec.strategy_id} ({spec.plugin}), budget {spec.budget}")
        limits = [
            f"{key} {value}"
            for key, value in (
                ("risk per trade", spec.risk.risk_per_trade),
                ("positions", spec.risk.max_open_positions),
                ("position size", spec.risk.max_position_size),
            )
            if value is not None
        ]
        if limits:
            typer.echo(f"      own limits: {', '.join(limits)}")
    cash = 1 - sum(configured.budgets.values())
    if cash:
        typer.echo(f"    cash: {cash}")
    typer.echo(f"  Config hash:    {config.config_hash}")
    webhook = (
        "set (`tyche notify test` checks it)"
        if secrets.discord_webhook_url is not None
        else "not set: alerts are not sent"
    )
    typer.echo(f"  Secrets:        Discord webhook {webhook}")
    try:
        gateway = ibkr_connection(secrets)
    except EnvFileError as missing:
        ibkr = f"not set, needed from the first paper run: {missing}"
    else:
        ibkr = (
            f"{gateway.host}:{gateway.port}, client id {gateway.client_id}, "
            "account id set (checked against the gateway at every connection)"
        )
    typer.echo(f"                  IB Gateway {ibkr}")
    if readable_by_others(workspace.env_file):
        typer.echo(
            f"  Warning: other users can read {workspace.relative(workspace.env_file)}; "
            f"make it private with: chmod 600 {workspace.env_file}"
        )


@data_app.command("fetch")
def data_fetch(
    symbols: Annotated[
        list[str] | None,
        typer.Argument(
            help="Symbols as the exchange lists them, e.g. SPY or BRK.B. Not with --all.",
            show_default=False,
        ),
    ] = None,
    exchange: Annotated[
        str | None,
        typer.Option(
            "--exchange",
            help=(
                "Listing exchange of the symbols, as a market identifier code: ARCX, XNAS, "
                "XNYS, BATS or XASE."
            ),
            show_default=False,
        ),
    ] = None,
    every_candidate: Annotated[
        bool,
        typer.Option(
            "--all",
            help=(
                "Every candidate in the market profile, and its benchmark: exactly what a "
                "backtest replays and a paper run trades from."
            ),
        ),
    ] = False,
    asset_class: Annotated[
        AssetClass | None,
        typer.Option(
            "--asset-class",
            help="Stock or ETF, for the symbols. Defaults to ETF.",
            show_default=False,
        ),
    ] = None,
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

    Name symbols with their --exchange, or give --all for the market profile's whole
    list. Only sessions not already cached are downloaded, and a session only once the
    market profile's wait after its close has passed. Every answer is checked against
    the trading calendar, and any problem found is listed. Yahoo's data is for personal
    use only.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "data fetch")
        config = load_config(workspace)
        instruments = _instruments_to_fetch(
            config.market_profile, symbols or [], exchange, asset_class, every=every_candidate
        )
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


def _instruments_to_fetch(
    profile: MarketProfile,
    symbols: list[str],
    exchange: str | None,
    asset_class: AssetClass | None,
    *,
    every: bool,
) -> list[Instrument]:
    """The symbols asked for on ``exchange``, or with ``every`` the profile's whole list."""
    if every:
        if symbols or exchange is not None or asset_class is not None:
            raise FetchRequestError(
                "--all fetches the market profile's own list; give no symbols, --exchange "
                "or --asset-class with it"
            )
        return list(followed_instruments(profile))
    if not symbols:
        raise FetchRequestError("name the symbols to fetch, or give --all")
    if exchange is None:
        raise FetchRequestError("--exchange is needed with symbols")
    return [
        instrument_for(symbol, exchange, asset_class or AssetClass.ETF, profile)
        for symbol in symbols
    ]


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
    risk_profile: RiskProfileOption = DEFAULT_RISK_PROFILE,
) -> None:
    """Backtest the configured strategies on cached history, and record the run.

    Replays the instruments listed in the market profile, from the cache only: fetch
    them first with `tyche data fetch`. A range that reaches the holdout is refused.
    The record goes to reports/backtests/ in the workspace.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "backtest")
        config = load_config(workspace, risk_profile)
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

    for line in _describe_backtest(
        outcome, config.backtest.starting_cash, config.risk_profile.name
    ):
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
    risk_profile: RiskProfileOption = DEFAULT_RISK_PROFILE,
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
        _open_logs(workspace, "walk-forward")
        config = load_config(workspace, risk_profile)
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
    risk_profile: RiskProfileOption = DEFAULT_RISK_PROFILE,
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
        _open_logs(workspace, "sweep")
        config = load_config(workspace, risk_profile)
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
def capital(
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
    amounts: Annotated[
        str,
        typer.Option(
            "--amounts",
            help="Starting cash to test, comma-separated, smallest first, in the "
            "profile's currency.",
        ),
    ] = ",".join(str(a) for a in DEFAULT_AMOUNTS),
    reference: Annotated[
        str,
        typer.Option("--reference", help="The large account every amount is compared with."),
    ] = str(DEFAULT_REFERENCE),
    tolerance: Annotated[
        str,
        typer.Option(
            "--tolerance",
            help="The most CAGR an amount may lose to its size and be viable, in points a year.",
        ),
    ] = str(DEFAULT_TOLERANCE * 100),
    positions: Annotated[
        int,
        typer.Option(
            "--positions", help="The most positions the round-trip arithmetic splits into."
        ),
    ] = DEFAULT_POSITIONS,
    home: HomeOption = None,
    risk_profile: RiskProfileOption = DEFAULT_RISK_PROFILE,
) -> None:
    """Find the smallest account at which each strategy's edge survives costs.

    Each configured strategy runs alone, with the whole account, as a backtest over
    the same days at every amount and on the reference account, under IBKR Pro Fixed
    and, if the costs file has a [tiered] table, under Tiered too. An amount is viable
    when its CAGR is within the tolerance of the reference account's; the minimum
    viable capital is the smallest amount from which every larger one is viable. Also
    shows what one round trip costs per position, and how many whole shares of each
    candidate one position buys at today's prices. The record and its report go to
    reports/capital/ in the workspace.
    """
    try:
        request = CapitalRequest(
            amounts=tuple(_decimal(a, "--amounts") for a in amounts.split(",")),
            reference=_decimal(reference, "--reference"),
            tolerance=_decimal(tolerance, "--tolerance") / 100,
            positions=positions,
        )
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "capital")
        config = load_config(workspace, risk_profile)
        outcome = run_configured_capital(
            config,
            request,
            first.date(),
            last.date() if last is not None else None,
            progress=_describe_sized,
        )
    except (
        CapitalError,
        WorkspaceError,
        ConfigError,
        BacktestRequestError,
        HoldoutError,
        BacktestError,
        DataError,
    ) as error:
        _fail(str(error))

    for line in _describe_capital(outcome):
        typer.echo(line)
    try:
        typer.echo(f"  Report:        {write_capital_report(outcome.record_dir)}")
    except ReportError as error:
        typer.echo(f"  Report:        not written: {error}")


@app.command("compare-profiles")
def compare_profiles(
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
    risk_profiles: Annotated[
        list[str] | None,
        typer.Option(
            "--risk-profile",
            help="A risk profile to compare: a file in config/risk/. Repeat it for each "
            "one; without it, every profile in config/risk/ is compared.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Backtest the configured strategies under several risk profiles, side by side.

    Runs one backtest per profile over the same days, with the same strategies and
    parameters, so only the risk limits differ. Names no best profile, and adds no
    trial to any strategy's count. The runs and the report go to reports/profiles/ in
    the workspace.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "compare-profiles")
        configs = chosen_profiles(workspace, tuple(risk_profiles or ()))
        typer.echo(
            f"Comparing {len(configs)} risk profiles: "
            + ", ".join(c.risk_profile.name for c in configs)
        )
        outcome = run_profile_comparison(
            configs,
            first.date(),
            last.date() if last is not None else None,
            progress=_describe_profile_run,
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

    typer.echo(f"Comparison {outcome.comparison_id}: {len(outcome.runs)} profiles")
    typer.echo(
        "  Choosing a profile by these in-sample results is a selection too; the "
        "report names no best one."
    )
    typer.echo(f"  Record:        {outcome.folder / PROFILES_FILE}")
    try:
        typer.echo(f"  Report:        {write_profiles_report(outcome.folder)}")
    except ReportError as error:
        typer.echo(f"  Report:        not written: {error}")


def _describe_profile_run(run: ProfileRun) -> None:
    outcome = run.outcome
    if outcome.metrics is None:
        typer.echo(f"  {run.profile}: not measured: {outcome.metrics_error}")
        return
    mine = outcome.metrics.strategy
    typer.echo(
        f"  {run.profile}: CAGR {_percent(mine.cagr)}, Sharpe {_ratio(mine.sharpe)}, "
        f"max drawdown {_percent(_depth(mine))}; {_describe_account_rules(outcome.result)}"
    )


@app.command()
def report(
    run_id: Annotated[
        str,
        typer.Argument(
            help="The id of a backtest, walk-forward, sweep, capital analysis or profile "
            "comparison, as Tyche printed it.",
            show_default=False,
        ),
    ],
    home: HomeOption = None,
) -> None:
    """Write report.html for a recorded study, from its record alone.

    `tyche backtest`, `tyche walk-forward`, `tyche sweep`, `tyche capital` and
    `tyche compare-profiles` write the report themselves; this rebuilds it, for a run
    recorded before reports existed or after the report changed. It reads only the
    record folder in reports/backtests/, reports/walk_forward/, reports/sweeps/,
    reports/capital/ or reports/profiles/, never the cache.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "report")
    except WorkspaceError as error:
        _fail(str(error))
    folders = [
        workspace.reports_dir / "backtests",
        workspace.reports_dir / "walk_forward",
        workspace.reports_dir / "sweeps",
        workspace.reports_dir / "capital",
        workspace.reports_dir / "profiles",
    ]
    found = [f / run_id for f in folders if (f / run_id).is_dir()]
    if not run_id or Path(run_id).name != run_id or not found:
        _fail(
            f"no backtest, walk-forward, sweep, capital or profile comparison record named "
            f"{run_id!r} in "
            f"{workspace.reports_dir}"
        )
    folder = found[0]
    try:
        if is_walk_forward(folder):
            path = write_walk_forward_report(folder)
        elif is_sweep(folder):
            path = write_sweep_report(folder)
        elif is_capital(folder):
            path = write_capital_report(folder)
        elif is_profile_comparison(folder):
            path = write_profiles_report(folder)
        else:
            path = write_report(folder)
    except ReportError as error:
        _fail(str(error))
    typer.echo(f"Report: {path}")


@app.command()
def kill(
    reason: Annotated[
        str | None,
        typer.Option(
            "--reason",
            help="Why, for the journal and for you later. Adding --flatten without it "
            "keeps the reason already given.",
            show_default=False,
        ),
    ] = None,
    flatten: Annotated[
        bool,
        typer.Option(
            "--flatten",
            help="Also sell every holding at the next decision, after cancelling its stop.",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask before a flatten.")] = False,
    home: HomeOption = None,
) -> None:
    """Engage the kill switch: no new orders from the next decision on.

    Writes the KILL file in the workspace; the risk gate reads it at every decision.
    Holdings are kept and stops already resting stay, unless --flatten. Orders already
    working at the broker are listed, not cancelled. Only `tyche resume` releases it.
    """
    workspace = _existing_workspace(home)
    if flatten and not yes:
        typer.confirm(
            "Sell every holding at the next decision, cancelling each stop first?", abort=True
        )
    outcome = engage_kill(workspace, reason, flatten=flatten)
    _open_logs(workspace, "kill", flatten=flatten)  # after the flag: nothing may delay it
    current = outcome.status
    if current.kill is None:  # cannot happen: the flag was just written or was there
        _fail(f"the kill switch at {workspace.kill_file} does not read as engaged")
    _log.warning(
        "kill switch %s",
        "engaged" if outcome.changed else "already engaged",
        extra={"fields": {"reason": current.kill.reason, "flatten": current.kill.flatten}},
    )
    verb = "engaged" if outcome.changed else "was already engaged"
    typer.echo(f"Kill switch {verb}: {workspace.kill_file}")
    for line in _describe_kill(current.kill):
        typer.echo(f"  {line}")
    if not outcome.changed and flatten is False and current.kill.flatten:
        typer.echo("  It already flattens; only `tyche resume` releases it.")
    for line in _describe_status(current, workspace.relative(workspace.state_database)):
        typer.echo(line)
    if outcome.changed:
        _said(notify_kill(workspace, current.kill, environ=os.environ, code_version=__version__))


@app.command("resume")
def resume_trading(
    reason: Annotated[
        str,
        typer.Option("--reason", help="Why trading may start again, for the journal."),
    ],
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask before lifting.")] = False,
    home: HomeOption = None,
) -> None:
    """Lift the kill switch and the halts: the manual restart.

    Shows what it would lift and asks first. A drawdown halt is lifted in the state
    database, with a new peak from the next close. A reconciliation halt is lifted there
    too, applying the fills it explained. The KILL file is removed last.
    """
    workspace = _existing_workspace(home)
    _open_logs(workspace, "resume")
    current = status(workspace)
    if current.kill is not None:
        typer.echo(f"Kill switch engaged: {workspace.kill_file}")
        for line in _describe_kill(current.kill):
            typer.echo(f"  {line}")
    if current.halt is not None:
        typer.echo(f"Drawdown halt since {current.halt.at:%Y-%m-%d}: {current.halt.reason}")
        typer.echo("  Resuming forgets the peak: the next close becomes the new peak.")
    if current.unreconciled is not None:
        for line in _describe_unreconciled(current):
            typer.echo(line)
    if current.unreadable is not None:
        _fail(
            "the state database cannot be read, so a halt cannot be ruled out: "
            f"{current.unreadable}"
        )
    if not current.stopped:
        typer.echo("Nothing to resume: the kill switch is off and trading is not halted.")
        return
    if not yes:
        typer.confirm("Lift it and let the next decision trade again?", abort=True)
    try:
        outcome = resume(
            workspace,
            reason,
            code_version=__version__,
            expected=current,
        )
    except KillSwitchError as error:
        _fail(str(error))
    lifted = [
        "the kill switch" if outcome.released else "",
        "the drawdown halt" if outcome.lifted else "",
        "the reconciliation halt" if outcome.unreconciled else "",
    ]
    typer.echo(f"Lifted {' and '.join(x for x in lifted if x)}.")
    if outcome.applied and outcome.unreconciled is not None:
        for fill in outcome.unreconciled.inferred:
            typer.echo(f"Applied: {fill}.")
        typer.echo("Took the broker's cash as the halt recorded it.")
    if outcome.run_id is not None:
        typer.echo(f"Recorded as run {outcome.run_id} in the state database.")
    typer.echo("The next decision trades normally.")
    _log.warning(
        "trading resumed",
        extra={
            "fields": {
                "reason": reason,
                "kill_released": outcome.released is not None,
                "halt_lifted": outcome.lifted is not None,
                "reconciliation_lifted": outcome.unreconciled is not None,
                "reconciliation_applied": outcome.applied,
                "run_id": outcome.run_id,
            }
        },
    )
    delivery = notify_resume(
        workspace,
        reason,
        released=outcome.released,
        lifted=outcome.lifted,
        unreconciled=outcome.unreconciled,
        applied=outcome.applied,
        environ=os.environ,
        code_version=__version__,
    )
    _said(delivery)


@paper_app.command("run")
def paper_run(
    home: HomeOption = None,
    risk_profile: RiskProfileOption = DEFAULT_RISK_PROFILE,
) -> None:
    """Run one decision cycle on the IBKR paper account, after a session's close.

    Reads IBKR's fills, reconciles, decides on every session closed since the last
    decision, sends the orders for the next open, reconciles again, saves the state
    and sends the alerts. Needs IB Gateway logged in to the paper account named in
    .env. A run with no new session still reads and reconciles the account.
    """
    try:
        workspace = Workspace(resolve_home(home, os.environ))
        _open_logs(workspace, "paper run", risk_profile=risk_profile)
        config = load_config(workspace, risk_profile)
        outcome = run_paper(config, environ=os.environ, code_version=str(current_code_version()))
    except (WorkspaceError, ConfigError, PaperRunError) as error:
        _fail(str(error))
    for line in _describe_paper(outcome):
        typer.echo(line)
    _said(outcome.delivery)
    if not outcome.completed:
        typer.echo(f"Error: the paper run failed: {outcome.failure}", err=True)
        raise typer.Exit(code=1)


def _describe_paper(outcome: PaperOutcome) -> list[str]:
    lines = []
    if outcome.first_run:
        lines.append("First paper run: Tyche started from IBKR's cash.")
    if outcome.startup is not None:
        lines.append(f"Check {outcome.check_run}: reconciliation {outcome.startup.status}.")
    if outcome.decision_run is None:
        if outcome.completed:
            lines.append("No session has closed since the last decision: nothing to decide.")
    else:
        lines.append(f"Decision {outcome.decision_run}:")
        if outcome.sessions:
            first, last = outcome.sessions[0].day, outcome.sessions[-1].day
            span = f"{first}" if first == last else f"{first} to {last}"
            lines.append(f"  Sessions read: {span}")
        if outcome.traded is not None:
            lines.append(f"  Decided at the close of {outcome.traded.day}")
        for skipped in outcome.skipped:
            lines.append(f"  Skipped {skipped.as_of:%Y-%m-%d}: {skipped.reason}")
        if outcome.after is not None:
            lines.append(f"  Reconciliation after the run: {outcome.after.status}")
    for order_id in outcome.lost:
        lines.append(f"Lost while sending, never resent: {order_id}")
    for order_id in outcome.not_sent:
        lines.append(f"Not sent (stop cancellation not confirmed): {order_id}")
    for found in (outcome.startup, outcome.after):
        if found is not None:
            lines.extend(f"  {difference}" for difference in found.differences)
    if outcome.checkpoint is not None:
        lines.append(f"Saved: checkpoint of run {outcome.checkpoint.run_id}.")
    return lines


@app.command()
def ui(
    home: HomeOption = None,
    port: Annotated[int, typer.Option("--port", help="Port on 127.0.0.1.")] = DEFAULT_PORT,
    browser: Annotated[
        bool, typer.Option("--browser/--no-browser", help="Open the console in the browser.")
    ] = True,
) -> None:
    """Open the console: a page to see the workspace and, later, run Tyche from it.

    Serves the built React app (`make ui` builds it) and its API on 127.0.0.1 only,
    locked with a new token at every launch. Stop it with Ctrl+C.
    """
    workspace = _existing_workspace(home)
    _open_logs(workspace, "ui", port=port)
    app_dir = default_app_dir()
    if not (app_dir / "index.html").is_file():
        _fail(f"the console's page is not built ({app_dir} has no index.html); run `make ui`")
    token = new_token()
    console = create_app(workspace, token, environ=os.environ, app_dir=app_dir)
    address = f"http://{HOST}:{port}/#token={token}"
    typer.echo(f"Tyche console for {workspace.root}")
    typer.echo(f"  Open: {address}")
    typer.echo("  The address holds this launch's key: do not share it. Ctrl+C stops the console.")
    if browser:
        webbrowser.open(address)
    serve(console, port)


@notify_app.command("test")
def notify_test(home: HomeOption = None) -> None:
    """Send a test message to the Discord channel in DISCORD_WEBHOOK_URL.

    Use it after creating or changing the webhook. Nothing happens in trading.
    """
    workspace = _existing_workspace(home)
    _open_logs(workspace, "notify test")
    try:
        check_channel(workspace, environ=os.environ, code_version=__version__)
    except ChannelCheckError as error:
        _fail(str(error))
    typer.echo("Discord: test message sent. Check the channel.")


def _open_logs(workspace: Workspace, command: str, **fields: object) -> None:
    """Send this command's logs to the workspace's daily file. Never fails the command."""
    off = open_logs(workspace, command, environ=os.environ, code_version=__version__, **fields)
    if off is not None and off != "no workspace":
        typer.echo(f"Warning: {off}", err=True)


def _said(delivery: Delivery) -> None:
    """Say what became of an alert. A failure is a warning: the command still worked."""
    typer.echo(delivery.describe(), err=bool(delivery.failures))


def _existing_workspace(home: Path | None) -> Workspace:
    """The workspace, refused unless it exists: a KILL file elsewhere protects nothing."""
    try:
        workspace = Workspace(resolve_home(home, os.environ))
    except WorkspaceError as error:
        _fail(str(error))
    if not workspace.tyche_config.is_file():
        _fail(
            f"no workspace at {workspace.root} (no {workspace.relative(workspace.tyche_config)}); "
            "give --home or set TYCHE_HOME"
        )
    return workspace


def _describe_kill(kill: Kill) -> list[str]:
    when = f"{kill.engaged_at:%Y-%m-%d %H:%M} UTC" if kill.engaged_at else "not recorded"
    effect = (
        "every holding is sold at the next decision, each stop cancelled first"
        if kill.flatten
        else "holdings are kept; stops already resting stay"
    )
    return [f"Engaged at: {when}", f"Reason: {kill.reason}", f"Flatten: {effect}"]


def _describe_unreconciled(current: TradingStatus) -> list[str]:
    halt = current.unreconciled
    if halt is None:
        return []
    lines = [f"Reconciliation halt since {halt.at:%Y-%m-%d %H:%M} UTC:"]
    lines.extend(f"  {difference}" for difference in halt.differences)
    if not current.applies:
        lines.append("  A later check agreed with the broker: resuming applies nothing.")
        return lines
    lines.extend(f"  Resuming applies: {fill}." for fill in halt.inferred)
    lines.extend(f"  Resuming drops: {ended}." for ended in halt.ended)
    lines.append("  Resuming takes the broker's cash as this check recorded it.")
    if halt.differences:
        lines.append("  Fix the differences above in the account first; the next run checks again.")
    return lines


def _describe_status(current: TradingStatus, database: str) -> list[str]:
    if current.unreadable is not None:
        return [f"Could not read {database}, so working orders are unknown: {current.unreadable}"]
    if current.checkpoint is None:
        return ["No paper or live run has saved state yet, so no order is known to be working."]
    lines = []
    if current.halt is not None:
        lines.append(
            f"Trading is also halted by the drawdown kill since {current.halt.at:%Y-%m-%d}."
        )
    if current.unreconciled is not None:
        lines.append(
            f"Trading is also halted by reconciliation since {current.unreconciled.at:%Y-%m-%d}: "
            "a flatten waits until it is lifted; flatten in IBKR's own apps if you must."
        )
    working = current.working
    if not working:
        lines.append(f"Run {current.checkpoint.run_id} left no order working at the broker.")
        return lines
    lines.append(f"Orders run {current.checkpoint.run_id} left working at the broker:")
    lines.extend(f"  {_describe_working(order)}" for order in working)
    lines.append(
        "  They are not cancelled. Market orders fill or expire at the next session; "
        "to cancel one, use IBKR's own app (docs/runbooks/kill-switch.md)."
    )
    return lines


def _describe_working(working: WorkingOrder) -> str:
    order = working.state.order
    price = f" at {order.stop_price}" if order.stop_price is not None else ""
    return (
        f"{order.client_order_id}: {order.side} {working.state.remaining} "
        f"{order.instrument.symbol}.{order.instrument.exchange} {order.order_type}{price}, "
        f"{order.time_in_force}"
    )


def _describe_backtest(outcome: BacktestOutcome, starting: Money, risk_profile: str) -> list[str]:
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
    lines.append(f"  Risk profile:  {risk_profile}; {_describe_adjustments(result)}")
    lines.append(f"  Account rules: {_describe_account_rules(result)}")
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


def _describe_adjustments(result: BacktestResult) -> str:
    counts = adjustments_record(result)
    orders = {k: n for k, n in counts.items() if k.split(".")[0] in ORDER_RULES}
    gate = {k: n for k, n in counts.items() if k not in orders}
    if not counts:
        return "nothing cut by the risk gate"
    shrunk = sum(n for key, n in gate.items() if key.endswith(".shrink"))
    blocked = sum(n for key, n in gate.items() if key.endswith(".block"))
    text = (
        f"the risk gate shrank {_count(shrunk, 'contribution')} and blocked "
        f"{blocked:,} {'entry' if blocked == 1 else 'entries'}"
    )
    if orders:
        text += f"; the money caps cut {_count(sum(orders.values()), 'purchase')}"
    return text


def _describe_account_rules(result: BacktestResult) -> str:
    daily = sum(1 for t in result.triggers if t.rule is RiskRule.DAILY_LOSS_LIMIT)
    text = f"daily loss limit hit after {_count(daily, 'session')}; "
    halt = result.halt
    if halt is None:
        return text + "drawdown kill never hit"
    return text + (
        f"HALTED by the drawdown kill on {halt.at.date()}, "
        f"{(halt.loss * 100).quantize(Decimal('0.01'))}% below the peak of "
        f"{halt.reference.amount.quantize(Decimal('0.01'))} {halt.reference.currency}; "
        "no order after that"
    )


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


def _decimal(text: str, option: str) -> Decimal:
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        raise CapitalError(f"{option}: not a number: {text.strip()!r}") from None
    if not value.is_finite():
        raise CapitalError(f"{option}: not a finite number: {text.strip()!r}")
    return value


def _describe_sized(run: SizedRun, reference: SizedRun | None) -> None:
    """One line per run, printed as soon as it is measured."""
    plan = PLAN_NAMES.get(run.plan, run.plan)
    head = f"  {run.strategy_id:<16} {plan:<16} {run.amount:>10,}"
    if run.metrics is None or run.drag is None:
        typer.echo(f"{head}  {run.failure}")
        return
    line = f"{head}  CAGR {_percent(run.cagr):>8}  costs {_percent(run.drag.per_year):>7} a year"
    if reference is None:
        line += "  (reference)"
    elif reference.cagr is not None and run.cagr is not None:
        line += f"  penalty {_points(reference.cagr - run.cagr):>11}"
    typer.echo(line)


def _describe_capital(outcome: CapitalOutcome) -> list[str]:
    result = outcome.result
    currency = result.plans[next(iter(result.plans))].currency
    lines = [f"Capital {outcome.capital_id}: minimum viable capital, by strategy and plan"]
    for study in result.studies:
        for verdict in study.verdicts:
            plan = PLAN_NAMES.get(verdict.plan, verdict.plan)
            minimum = (
                f"{verdict.minimum:,} {currency}"
                if verdict.minimum is not None
                else "none of the amounts tested"
            )
            measured = verdict.reference.metrics
            edge = ""
            if measured is not None:
                edge = (
                    f"; reference Sharpe {_ratio(measured.strategy.sharpe)}, benchmark "
                    f"{_ratio(measured.benchmark.sharpe)}"
                )
            if verdict.reference_too_large:
                minimum, edge = "not judged: the reference account is too large", ""
            lines.append(f"  {study.strategy_id:<16} {plan:<16} {minimum}{edge}")
            if verdict.reference_too_large:
                lines.append(
                    f"Warning: the volume cap cut {verdict.reference.cut_short:,} of the "
                    f"reference account's orders short for {study.strategy_id}; run again "
                    "with a smaller --reference."
                )
    lines.append(f"  Code:          {outcome.code}")
    lines.append(f"  Record:        {outcome.record_dir}")
    if outcome.code.dirty:
        lines.append(
            "Warning: the code had uncommitted changes, so its commit alone does not "
            "reproduce this analysis."
        )
    return lines


def _points(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.01')):+} pts"


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
    try:
        app(prog_name="tyche")
    except Exception:
        _log.exception("command crashed")
        raise
