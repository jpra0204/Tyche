"""Wiring for strategies: build each configured instance from its plugin (ADR-0022).

Composition-root code (ADR-0004). The config layer reads the strategy files; the
plugins live in ``tyche.strategies``; this module is where the two meet, because
neither may import the other.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

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
    """

    strategies: tuple[Strategy, ...]
    budgets: Mapping[str, Decimal]


def build_strategies(config: TycheConfig) -> ConfiguredStrategies:
    """Build every configured strategy, or raise ``ConfigError`` naming the file and key."""
    strategies = tuple(_build(spec, config) for spec in config.strategies)
    return ConfiguredStrategies(strategies, config.budgets)


def _build(spec: StrategySpec, config: TycheConfig) -> Strategy:
    plugin = PLUGINS.get(spec.plugin)
    if plugin is None:
        known = ", ".join(sorted(PLUGINS))
        raise ConfigError(f"{spec.source}: plugin: unknown plugin {spec.plugin!r}; known: {known}")

    def lookup(symbol: str, exchange: str, asset_class: AssetClass) -> Instrument:
        try:
            return instrument_for(symbol, exchange, asset_class, config.market_profile)
        except FetchRequestError as error:
            raise ConfigError(f"{spec.source}: parameters: {error}") from None

    try:
        strategy = plugin.create(spec.strategy_id, spec.parameters, lookup)
    except ValidationError as error:
        raise ConfigError(_describe(spec.source, error)) from None
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
