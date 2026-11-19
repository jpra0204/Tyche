"""Load, validate and fingerprint the workspace configuration (ADR-0010).

Two layers, deliberately separate:

* **File schemas** (the pydantic models here) say what a config file may contain:
  which keys exist and what type each value has. They reject unknown keys and refuse
  to convert between types, so ``"1"`` is not accepted where a number is expected.
* **Domain objects** (in ``tyche.core.domain``) hold the rules that make a value
  meaningful, such as "a market profile needs at least one calendar". The core only
  ever receives domain objects and never imports pydantic.

Loading either returns a complete, valid ``TycheConfig`` or raises ``ConfigError``
naming the file and the key. There is no partial result.
"""

import hashlib
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
)
from pydantic.types import Strict

from tyche.config.exchanges import KNOWN_EXCHANGES
from tyche.config.workspace import Workspace
from tyche.core.backtest.settings import BacktestSettings
from tyche.core.domain import (
    AssetClass,
    CommissionSchedule,
    Currency,
    ExecutionRules,
    Instrument,
    MarketProfile,
    Money,
    RegulatoryFees,
    TradingCosts,
    UniverseRules,
    require_budgets,
    require_profile_name,
    require_strategy_id,
)

SCHEMA_VERSION = 1

# Changing how the hash is computed must change every hash, so the scheme is part of
# what is hashed. Bump this if the payload's shape changes.
HASH_SCHEME = "tyche-config-v1"


class ConfigError(Exception):
    """The configuration is missing or invalid. Tyche must not start."""


# --- file schemas -----------------------------------------------------------------


class _ConfigFile(BaseModel):
    """Base for every config file: immutable, and unknown keys are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _exact_decimal(value: object) -> Decimal:
    """Accept a decimal written as a string, and nothing else.

    TOML reads ``0.005`` without quotes as a binary float, which cannot hold most
    decimal fractions exactly (ADR-0012). Asking for ``"0.005"`` keeps every rate exact
    from the file to the ledger.
    """
    if not isinstance(value, str):
        raise ValueError('write decimals as strings, such as "0.005", so they stay exact')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"not a decimal number: {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"must be a finite number, got {value!r}")
    return number


ExactDecimal = Annotated[Decimal, BeforeValidator(_exact_decimal)]
StrictDate = Annotated[date, Strict()]


class BacktestFile(_ConfigFile):
    """The ``[backtest]`` table of ``tyche.toml`` (ADR-0024)."""

    holdout_starts: StrictDate
    starting_cash: ExactDecimal


class TycheFile(_ConfigFile):
    """``config/tyche.toml``."""

    schema_version: StrictInt
    market_profile: StrictStr
    strategies: dict[StrictStr, ExactDecimal]
    """Strategy id to budget, a fraction of account equity (ADR-0022)."""
    backtest: BacktestFile


class StrategyFile(_ConfigFile):
    """``config/strategies/<id>.toml``: which plugin a strategy instance uses, and how.

    The parameters are checked here only as a TOML table; the plugin's own model
    checks their names and types when the runtime builds the strategy (ADR-0022).
    """

    plugin: StrictStr
    parameters: dict[StrictStr, Any] = {}


class InstrumentFile(_ConfigFile):
    """One entry of ``instruments`` in the ``[universe]`` table."""

    symbol: StrictStr
    exchange: StrictStr
    asset_class: AssetClass

    def to_domain(self) -> Instrument:
        info = KNOWN_EXCHANGES.get(self.exchange)
        if info is None:
            known = ", ".join(sorted(KNOWN_EXCHANGES))
            raise ValueError(
                f"{self.symbol}: unknown exchange {self.exchange!r}; known exchanges: {known}"
            )
        return Instrument(
            self.symbol, self.exchange, info.currency, info.calendar, self.asset_class
        )


class UniverseFile(_ConfigFile):
    """The ``[universe]`` table of a market profile file."""

    asset_classes: tuple[AssetClass, ...]
    currency: Currency
    min_price: ExactDecimal
    min_average_dollar_volume: ExactDecimal
    liquidity_sessions: StrictInt
    quality_sessions: StrictInt
    instruments: tuple[InstrumentFile, ...]

    def to_domain(self) -> UniverseRules:
        if not self.instruments:
            raise ValueError("universe.instruments: list at least one instrument")
        try:
            instruments = tuple(entry.to_domain() for entry in self.instruments)
        except ValueError as error:
            raise ValueError(f"universe.instruments: {error}") from None
        return UniverseRules(
            asset_classes=self.asset_classes,
            min_price=Money(self.min_price, self.currency),
            min_average_dollar_volume=Money(self.min_average_dollar_volume, self.currency),
            liquidity_sessions=self.liquidity_sessions,
            quality_sessions=self.quality_sessions,
            instruments=instruments,
        )


class ExecutionFile(_ConfigFile):
    """The ``[execution]`` table of a market profile file (ADR-0023)."""

    rebalance_band: ExactDecimal
    price_buffer: ExactDecimal

    def to_domain(self) -> ExecutionRules:
        return ExecutionRules(rebalance_band=self.rebalance_band, price_buffer=self.price_buffer)


class MarketProfileFile(_ConfigFile):
    """``config/markets/<NAME>.toml``."""

    name: StrictStr
    cash_currencies: tuple[Currency, ...]
    calendars: tuple[StrictStr, ...]
    universe: UniverseFile
    execution: ExecutionFile
    benchmark: InstrumentFile

    def to_domain(self) -> MarketProfile:
        try:
            benchmark = self.benchmark.to_domain()
        except ValueError as error:
            raise ValueError(f"benchmark: {error}") from None
        return MarketProfile(
            name=self.name,
            cash_currencies=self.cash_currencies,
            calendars=self.calendars,
            universe=self.universe.to_domain(),
            execution=self.execution.to_domain(),
            benchmark=benchmark,
        )


class CommissionFile(_ConfigFile):
    """The ``[commission]`` table of a costs file."""

    per_share: ExactDecimal
    minimum: ExactDecimal
    maximum_rate: ExactDecimal


class RegulatoryFeesFile(_ConfigFile):
    """The ``[regulatory_fees]`` table of a costs file."""

    sec_fee_rate: ExactDecimal
    taf_per_share_sold: ExactDecimal
    cat_per_share: ExactDecimal


class CostsFile(_ConfigFile):
    """``config/costs/<NAME>.toml``: trading costs and settlement for one profile."""

    checked_on: StrictDate
    currency: Currency
    settlement_days: StrictInt
    slippage_bps: ExactDecimal
    commission: CommissionFile
    regulatory_fees: RegulatoryFeesFile

    def to_domain(self) -> TradingCosts:
        def money(amount: Decimal) -> Money:
            return Money(amount, self.currency)

        return TradingCosts(
            commission=CommissionSchedule(
                per_share=money(self.commission.per_share),
                minimum=money(self.commission.minimum),
                maximum_rate=self.commission.maximum_rate,
            ),
            regulatory_fees=RegulatoryFees(
                sec_fee_rate=self.regulatory_fees.sec_fee_rate,
                taf_per_share_sold=money(self.regulatory_fees.taf_per_share_sold),
                cat_per_share=money(self.regulatory_fees.cat_per_share),
            ),
            slippage_bps=self.slippage_bps,
            settlement_days=self.settlement_days,
            checked_on=self.checked_on,
        )


# --- the result -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """One configured strategy instance, before its plugin builds it.

    Attributes:
        strategy_id: The instance's identifier, from ``[strategies]`` in ``tyche.toml``.
        budget: Its fraction of account equity.
        plugin: The built-in plugin it uses.
        parameters: The plugin's parameters, as read from the file.
        source: The strategy file, relative to the workspace, for messages.
    """

    strategy_id: str
    budget: Decimal
    plugin: str
    parameters: Mapping[str, Any]
    source: str


@dataclass(frozen=True, slots=True)
class TycheConfig:
    """The validated configuration of one workspace.

    Attributes:
        workspace: Where the configuration was loaded from.
        market_profile: The active market profile.
        costs: What trading costs under that profile, and when trades settle.
        strategies: The configured strategy instances, ordered by id.
        backtest: The starting cash and the reserved holdout (ADR-0024).
        config_hash: Fingerprint of every loaded setting. Two runs with the same hash
            used the same configuration. Comments, blank lines and key order do not
            affect it; any change of value does.
        snapshot: Every loaded setting, by file, exactly as hashed: what a run record
            stores so that the run can be reproduced.
    """

    workspace: Workspace
    market_profile: MarketProfile
    costs: TradingCosts
    strategies: tuple[StrategySpec, ...]
    backtest: BacktestSettings
    config_hash: str
    snapshot: Mapping[str, Any]

    @property
    def budgets(self) -> dict[str, Decimal]:
        """Each strategy's budget, by id."""
        return {spec.strategy_id: spec.budget for spec in self.strategies}


def load_config(workspace: Workspace) -> TycheConfig:
    """Load and validate the workspace configuration, or raise ``ConfigError``."""
    tyche = _read(workspace, workspace.tyche_config, TycheFile)
    tyche_name = workspace.relative(workspace.tyche_config)

    if tyche.schema_version != SCHEMA_VERSION:
        raise ConfigError(
            f"{tyche_name}: schema_version is {tyche.schema_version}, but this version of "
            f"Tyche reads version {SCHEMA_VERSION}"
        )

    try:
        require_profile_name(tyche.market_profile)
    except ValueError as error:
        raise ConfigError(f"{tyche_name}: market_profile: {error}") from None

    profile_path = workspace.markets_dir / f"{tyche.market_profile}.toml"
    profile_name = workspace.relative(profile_path)
    if not profile_path.is_file():
        raise ConfigError(
            f"{tyche_name} selects market profile {tyche.market_profile!r}, "
            f"but {profile_name} does not exist"
        )

    profile_file = _read(workspace, profile_path, MarketProfileFile)
    if profile_file.name != tyche.market_profile:
        raise ConfigError(
            f"{profile_name}: name is {profile_file.name!r}, but the file is for "
            f"{tyche.market_profile!r}; they must match"
        )
    try:
        profile = profile_file.to_domain()
    except ValueError as error:
        raise ConfigError(f"{profile_name}: {error}") from None

    costs_path = workspace.costs_dir / f"{tyche.market_profile}.toml"
    costs_name = workspace.relative(costs_path)
    if not costs_path.is_file():
        raise ConfigError(
            f"{costs_name} is missing: every market profile needs a costs file. "
            "`tyche init` on a scratch folder writes an example to copy"
        )
    costs_file = _read(workspace, costs_path, CostsFile)
    try:
        costs = costs_file.to_domain()
    except ValueError as error:
        raise ConfigError(f"{costs_name}: {error}") from None
    if costs.currency not in profile.cash_currencies:
        raise ConfigError(
            f"{costs_name}: costs are in {costs.currency}, but market profile "
            f"{profile.name} holds cash in {', '.join(profile.cash_currencies)}"
        )

    strategies, strategy_files = _load_strategies(workspace, tyche, tyche_name)

    try:
        backtest = BacktestSettings(
            holdout_starts=tyche.backtest.holdout_starts,
            starting_cash=Money(tyche.backtest.starting_cash, profile.cash_currencies[0]),
        )
    except ValueError as error:
        raise ConfigError(f"{tyche_name}: backtest: {error}") from None

    files = {
        tyche_name: tyche,
        profile_name: profile_file,
        costs_name: costs_file,
        **strategy_files,
    }
    return TycheConfig(
        workspace=workspace,
        market_profile=profile,
        costs=costs,
        strategies=strategies,
        backtest=backtest,
        config_hash=config_hash(files),
        snapshot=config_snapshot(files),
    )


def _load_strategies(
    workspace: Workspace, tyche: TycheFile, tyche_name: str
) -> tuple[tuple[StrategySpec, ...], dict[str, StrategyFile]]:
    for strategy_id in tyche.strategies:
        try:
            require_strategy_id(strategy_id)
        except ValueError as error:
            raise ConfigError(f"{tyche_name}: strategies: {error}") from None
    try:
        require_budgets(tyche.strategies)
    except ValueError as error:
        raise ConfigError(f"{tyche_name}: strategies: {error}") from None

    specs: list[StrategySpec] = []
    files: dict[str, StrategyFile] = {}
    for strategy_id in sorted(tyche.strategies):
        path = workspace.strategies_dir / f"{strategy_id}.toml"
        name = workspace.relative(path)
        if not path.is_file():
            raise ConfigError(
                f"{tyche_name} gives strategy {strategy_id!r} a budget, but {name} does not exist"
            )
        strategy_file = _read(workspace, path, StrategyFile)
        files[name] = strategy_file
        specs.append(
            StrategySpec(
                strategy_id,
                tyche.strategies[strategy_id],
                strategy_file.plugin,
                strategy_file.parameters,
                name,
            )
        )
    return tuple(specs), files


def config_snapshot(files: Mapping[str, BaseModel]) -> dict[str, Any]:
    """Validated config files as plain JSON values, keyed by their path in the workspace."""
    return {path: model.model_dump(mode="json") for path, model in files.items()}


def config_hash(files: Mapping[str, BaseModel]) -> str:
    """Fingerprint validated config files, keyed by their path in the workspace.

    The hash covers parsed values, not file text, so reformatting a file or editing a
    comment does not change it. Secrets in ``.env`` are never part of it.
    """
    payload = {"scheme": HASH_SCHEME, "files": config_snapshot(files)}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read[M: _ConfigFile](workspace: Workspace, path: Path, model: type[M]) -> M:
    name = workspace.relative(path)
    if not path.is_file():
        raise ConfigError(f"{name} is missing; is {workspace.root} a Tyche workspace?")
    try:
        data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{name}: not valid TOML: {error}") from None
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ConfigError(_describe(name, error)) from None


def _describe(name: str, error: ValidationError) -> str:
    lines = [f"{name}: {error.error_count()} invalid setting(s)"]
    for problem in error.errors():
        key = ".".join(str(part) for part in problem["loc"]) or "(file)"
        lines.append(f"  {key}: {problem['msg']}")
    return "\n".join(lines)
