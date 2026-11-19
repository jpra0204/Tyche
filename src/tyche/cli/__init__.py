"""The ``tyche`` command-line interface, built with Typer (ADR-0016).

Commands are thin: they parse options, call one function elsewhere in Tyche, and turn
its result or error into text and an exit code. No logic lives here.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from tyche import __version__
from tyche.config import (
    HOME_ENV_VAR,
    ConfigError,
    Workspace,
    WorkspaceError,
    init_workspace,
    load_config,
    resolve_home,
)
from tyche.core.domain import AssetClass
from tyche.runtime.data import (
    DEFAULT_FIRST,
    FetchOutcome,
    FetchRequestError,
    fetch_daily_histories,
    instrument_for,
)
from tyche.runtime.strategies import build_strategies

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


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}{'' if number == 1 else 's'}"


def main() -> None:
    """Entry point for the ``tyche`` console script and ``python -m tyche``."""
    app(prog_name="tyche")
