"""The Config page's data: the workspace's configuration, read-only (ADR-0046, U5).

The same reads as ``tyche config check``: the configuration loaded and checked, and the
strategies built from it. Then what the check does not print: every risk profile checked
on its own, each strategy's parameters, the sweeps, and every loaded file as parsed and
hashed (``TycheConfig.snapshot``, what a run record stores). Nothing here writes, and
``.env`` is never read beyond whether other users can read it.

Editing comes later, with its own ADR.
"""

from math import prod
from typing import Any

from tyche.api.models import (
    ConfigFileView,
    GuardrailsView,
    MarketView,
    ProfileCheckView,
    StrategyDetailView,
    SweepView,
    WorkspaceConfigView,
)
from tyche.api.status import money_caps_view, risk_profile_view
from tyche.config import (
    ConfigError,
    TycheConfig,
    Workspace,
    load_config,
    load_sweep,
    readable_by_others,
)
from tyche.core.risk import DEFAULT_RISK_PROFILE
from tyche.runtime.strategies import build_strategies


def read_workspace_config(workspace: Workspace) -> WorkspaceConfigView:
    """The configuration, as the Config page shows it."""
    base = WorkspaceConfigView(
        workspace=str(workspace.root),
        valid=False,
        env_readable_by_others=readable_by_others(workspace.env_file),
        profiles=_profiles(workspace),
    )
    try:
        config = load_config(workspace, DEFAULT_RISK_PROFILE)
        build_strategies(config)
    except ConfigError as error:
        return base.model_copy(update={"error": str(error)})
    return base.model_copy(
        update={
            "valid": True,
            "config_hash": config.config_hash,
            "guardrails": _guardrails(config),
            "strategies": _strategies(config),
            "cash_budget": _cash(config),
            "sweeps": _sweeps(config),
            "market": _market(config),
            "files": [
                ConfigFileView(path=path, settings=_plain(dict(settings)))
                for path, settings in sorted(config.snapshot.items())
            ],
        }
    )


def _profiles(workspace: Workspace) -> list[ProfileCheckView]:
    """Every file in ``config/risk/``, each checked as the active profile."""
    folder = workspace.root / "config" / "risk"
    names = sorted(p.stem for p in folder.glob("*.toml")) if folder.is_dir() else []
    found = []
    for name in names:
        try:
            config = load_config(workspace, name)
        except ConfigError as error:
            found.append(ProfileCheckView(name=name, valid=False, error=str(error)))
        else:
            found.append(
                ProfileCheckView(
                    name=name, valid=True, profile=risk_profile_view(config.risk_profile)
                )
            )
    return found


def _guardrails(config: TycheConfig) -> GuardrailsView:
    guardrails = config.guardrails
    return GuardrailsView(
        max_risk_per_trade=str(guardrails.max_risk_per_trade),
        max_open_positions=guardrails.max_open_positions,
        max_position_size=str(guardrails.max_position_size),
        max_daily_loss_limit=str(guardrails.max_daily_loss_limit),
        max_drawdown_kill=str(guardrails.max_drawdown_kill),
        money_caps=money_caps_view(guardrails),
    )


def _strategies(config: TycheConfig) -> list[StrategyDetailView]:
    return [
        StrategyDetailView(
            strategy_id=spec.strategy_id,
            plugin=spec.plugin,
            budget=str(spec.budget),
            source=spec.source,
            parameters=_plain(dict(spec.parameters)),
            risk_per_trade=_text(spec.risk.risk_per_trade),
            max_open_positions=spec.risk.max_open_positions,
            max_position_size=_text(spec.risk.max_position_size),
        )
        for spec in config.strategies
    ]


def _cash(config: TycheConfig) -> str | None:
    cash = 1 - sum(config.budgets.values())
    return str(cash) if cash else None


def _sweeps(config: TycheConfig) -> list[SweepView]:
    folder = config.workspace.sweeps_dir
    names = sorted(p.stem for p in folder.glob("*.toml")) if folder.is_dir() else []
    found = []
    for name in names:
        try:
            spec = load_sweep(config, name)
        except ConfigError as error:
            found.append(SweepView(name=name, error=str(error)))
        else:
            grid = {key: list(values) for key, values in spec.grid.items()}
            found.append(
                SweepView(
                    name=name,
                    strategy_id=spec.strategy_id,
                    grid=_plain(grid),
                    combinations=prod(len(values) for values in grid.values()),
                )
            )
    return found


def _market(config: TycheConfig) -> MarketView:
    profile = config.market_profile
    return MarketView(
        name=profile.name,
        cash_currencies=[str(c) for c in profile.cash_currencies],
        calendars=list(profile.calendars),
        candidates=[str(i) for i in profile.universe.instruments],
        benchmark=str(profile.benchmark),
        rebalance_band=str(profile.execution.rebalance_band),
        price_buffer=str(profile.execution.price_buffer),
        starting_cash=str(config.backtest.starting_cash),
        holdout_starts=config.backtest.holdout_starts,
        costs_checked_on=config.costs.checked_on,
    )


def _text(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _plain(value: Any) -> Any:
    """``value`` with every value JSON has no type for (``Decimal``, a date) as text."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)
