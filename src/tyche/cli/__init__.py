"""The ``tyche`` command-line interface, built with Typer (ADR-0016).

Commands are thin: they parse options, call one function elsewhere in Tyche, and turn
its result or error into text and an exit code. No logic lives here.
"""

import os
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
    except (WorkspaceError, ConfigError) as error:
        _fail(str(error))

    typer.echo(f"Configuration is valid: {workspace.root}")
    typer.echo(f"  Market profile: {config.market_profile}")
    typer.echo(f"  Config hash:    {config.config_hash}")


def main() -> None:
    """Entry point for the ``tyche`` console script and ``python -m tyche``."""
    app(prog_name="tyche")
