"""Wiring for strategies: build each configured instance from its plugin (ADR-0022).

Composition-root code (ADR-0004). The config layer reads the strategy files; the
plugins live in ``tyche.strategies``; this module is where the two meet, because
neither may import the other.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from tyche.config import ConfigError, StrategySpec, TycheConfig
from tyche.core.domain import AssetClass, Instrument
from tyche.core.pipeline.signals import Strategy
from tyche.runtime.data import FetchRequestError, instrument_for
from tyche.strategies import PLUGINS


@dataclass(frozen=True, slots=True)
class ConfiguredStrategies:
    """The strategy instances a run uses, and their budgets.

    Attributes:
        strategies: One per configured instance, ordered by id.
        budgets: Each one's fraction of account equity, by id.
        parameters: Each one's parameters as built, by id: the strategy file's, with
            any override applied. A run record states them, so that every trial can be
            counted (ADR-0030).
    """

    strategies: tuple[Strategy, ...]
    budgets: Mapping[str, Decimal]
    parameters: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


Overrides = Mapping[str, Mapping[str, Any]]
"""Parameters to replace, by strategy id: what a parameter sweep varies (ADR-0030)."""


def build_strategies(
    config: TycheConfig, overrides: Overrides | None = None, *, source: str | None = None
) -> ConfiguredStrategies:
    """Build every configured strategy, or raise ``ConfigError`` naming the file and key.

    ``overrides`` replaces some of a strategy's parameters, and keeps the others from
    its file. ``source`` names where the overrides came from, for messages (a sweep
    file); without it, the strategy file is named.
    """
    overrides = overrides or {}
    unknown = sorted(set(overrides) - {spec.strategy_id for spec in config.strategies})
    if unknown:
        raise ConfigError(f"{source or 'overrides'}: no configured strategy {unknown[0]!r}")
    parameters = {
        spec.strategy_id: {**spec.parameters, **overrides.get(spec.strategy_id, {})}
        for spec in config.strategies
    }
    strategies = tuple(
        _build(
            spec,
            config,
            parameters[spec.strategy_id],
            source if spec.strategy_id in overrides and source else spec.source,
        )
        for spec in config.strategies
    )
    return ConfiguredStrategies(strategies, config.budgets, parameters)


def _build(
    spec: StrategySpec, config: TycheConfig, parameters: Mapping[str, Any], source: str
) -> Strategy:
    plugin = PLUGINS.get(spec.plugin)
    if plugin is None:
        known = ", ".join(sorted(PLUGINS))
        raise ConfigError(f"{spec.source}: plugin: unknown plugin {spec.plugin!r}; known: {known}")
    where = source

    def lookup(symbol: str, exchange: str, asset_class: AssetClass) -> Instrument:
        try:
            return instrument_for(symbol, exchange, asset_class, config.market_profile)
        except FetchRequestError as error:
            raise ConfigError(f"{where}: parameters: {error}") from None

    try:
        strategy = plugin.create(spec.strategy_id, parameters, lookup)
    except ValidationError as error:
        raise ConfigError(_describe(where, error)) from None
    if strategy.strategy_id != spec.strategy_id:
        raise ConfigError(
            f"{spec.source}: plugin {spec.plugin!r} built a strategy named "
            f"{strategy.strategy_id!r}, not {spec.strategy_id!r}; this is a bug in the plugin"
        )
    return strategy


def _describe(source: str, error: ValidationError) -> str:
    lines = [f"{source}: {error.error_count()} invalid parameter(s)"]
    for problem in error.errors():
        key = ".".join(["parameters", *(str(part) for part in problem["loc"])])
        lines.append(f"  {key}: {problem['msg']}")
    return "\n".join(lines)
