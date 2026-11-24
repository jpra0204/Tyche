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
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal

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
    Commission,
    CommissionSchedule,
    Currency,
    DailyCycleRules,
    ExecutionRules,
    Instrument,
    MarketProfile,
    Money,
    RegulatoryFees,
    TieredSchedule,
    TradingCosts,
    UniverseRules,
    require_budgets,
    require_profile_name,
    require_strategy_id,
)
from tyche.core.risk import (
    DEFAULT_RISK_PROFILE,
    Guardrails,
    LimitBreach,
    RiskLimits,
    RiskProfile,
    StrategyRiskLimits,
    require_risk_profile_name,
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


class StrategyRiskFile(_ConfigFile):
    """The optional ``[risk]`` table of a strategy file: stricter position limits (ADR-0032)."""

    risk_per_trade: ExactDecimal | None = None
    max_open_positions: StrictInt | None = None
    max_position_size: ExactDecimal | None = None

    def to_domain(self) -> StrategyRiskLimits:
        return StrategyRiskLimits(
            risk_per_trade=self.risk_per_trade,
            max_open_positions=self.max_open_positions,
            max_position_size=self.max_position_size,
        )


class StrategyFile(_ConfigFile):
    """``config/strategies/<id>.toml``: which plugin a strategy instance uses, and how.

    The parameters are checked here only as a TOML table; the plugin's own model
    checks their names and types when the runtime builds the strategy (ADR-0022).
    """

    plugin: StrictStr
    parameters: dict[StrictStr, Any] = {}
    risk: StrategyRiskFile | None = None


class MoneyFile(_ConfigFile):
    """An amount with its currency, such as ``{ amount = "700", currency = "USD" }``."""

    amount: ExactDecimal
    currency: Currency

    def to_domain(self) -> Money:
        return Money(self.amount, self.currency)


class GuardrailsFile(_ConfigFile):
    """``config/guardrails.toml``: the absolute limits. Only Pablo edits it (ADR-0032)."""

    long_only: Literal[True]
    """Tyche cannot sell short (brief §2); only ``true`` is accepted."""
    allow_leverage: Literal[False]
    """Tyche trades a cash account without margin (brief §2); only ``false`` is accepted."""
    max_risk_per_trade: ExactDecimal
    max_open_positions: StrictInt
    max_position_size: ExactDecimal
    max_daily_loss_limit: ExactDecimal
    max_drawdown_kill: ExactDecimal
    max_total_capital: tuple[MoneyFile, ...]
    max_order_value: tuple[MoneyFile, ...]

    def to_domain(self) -> Guardrails:
        return Guardrails(
            max_risk_per_trade=self.max_risk_per_trade,
            max_open_positions=self.max_open_positions,
            max_position_size=self.max_position_size,
            max_daily_loss_limit=self.max_daily_loss_limit,
            max_drawdown_kill=self.max_drawdown_kill,
            max_total_capital=tuple(cap.to_domain() for cap in self.max_total_capital),
            max_order_value=tuple(cap.to_domain() for cap in self.max_order_value),
        )


class RiskProfileFile(_ConfigFile):
    """``config/risk/<name>.toml``: one named risk profile (ADR-0032).

    The file name is the profile's name, so the file has no ``name`` key.
    """

    risk_per_trade: ExactDecimal
    max_open_positions: StrictInt
    max_position_size: ExactDecimal
    daily_loss_limit: ExactDecimal
    drawdown_kill: ExactDecimal

    def to_domain(self, name: str) -> RiskProfile:
        return RiskProfile(
            name=name,
            risk_per_trade=self.risk_per_trade,
            max_open_positions=self.max_open_positions,
            max_position_size=self.max_position_size,
            daily_loss_limit=self.daily_loss_limit,
            drawdown_kill=self.drawdown_kill,
        )


class SweepFile(_ConfigFile):
    """``config/sweeps/<name>.toml``: a parameter sweep over one strategy (ADR-0030).

    The values are checked here only as TOML lists; the plugin's own model checks
    every combination when the runtime builds it, before any trial runs.
    """

    strategy: StrictStr
    grid: dict[StrictStr, list[Any]]


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


class DailyCycleFile(_ConfigFile):
    """The ``[daily_cycle]`` table of a market profile file (ADR-0043)."""

    after_close_minutes: StrictInt
    before_next_open_minutes: StrictInt

    def to_domain(self) -> DailyCycleRules:
        for name in ("after_close_minutes", "before_next_open_minutes"):
            if getattr(self, name) < 0:
                raise ValueError(f"daily_cycle.{name} must not be negative")
        return DailyCycleRules(
            after_close=timedelta(minutes=self.after_close_minutes),
            before_next_open=timedelta(minutes=self.before_next_open_minutes),
        )


class MarketProfileFile(_ConfigFile):
    """``config/markets/<NAME>.toml``."""

    name: StrictStr
    cash_currencies: tuple[Currency, ...]
    calendars: tuple[StrictStr, ...]
    universe: UniverseFile
    execution: ExecutionFile
    benchmark: InstrumentFile
    daily_cycle: DailyCycleFile

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
            daily_cycle=self.daily_cycle.to_domain(),
        )


class CommissionFile(_ConfigFile):
    """The ``[commission]`` table of a costs file."""

    per_share: ExactDecimal
    minimum: ExactDecimal
    maximum_rate: ExactDecimal


class TieredFile(_ConfigFile):
    """The optional ``[tiered]`` table of a costs file: IBKR Pro Tiered, for comparison.

    Backtests always use ``[commission]``. ``tyche capital`` runs each amount under
    both plans when this table is present (ADR-0031).
    """

    per_share: ExactDecimal
    minimum: ExactDecimal
    maximum_rate: ExactDecimal
    clearing_per_share: ExactDecimal
    clearing_maximum_rate: ExactDecimal
    nyse_pass_through_rate: ExactDecimal
    finra_pass_through_rate: ExactDecimal
    exchange_fee_per_share: ExactDecimal


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
    tiered: TieredFile | None = None

    def _money(self, amount: Decimal) -> Money:
        return Money(amount, self.currency)

    def to_domain(self) -> TradingCosts:
        """The costs backtests use: the ``[commission]`` plan."""
        return self._costs(
            CommissionSchedule(
                per_share=self._money(self.commission.per_share),
                minimum=self._money(self.commission.minimum),
                maximum_rate=self.commission.maximum_rate,
            )
        )

    def tiered_domain(self) -> TradingCosts | None:
        """The same costs under the ``[tiered]`` plan, or ``None`` without that table."""
        tiered = self.tiered
        if tiered is None:
            return None
        return self._costs(
            TieredSchedule(
                per_share=self._money(tiered.per_share),
                minimum=self._money(tiered.minimum),
                maximum_rate=tiered.maximum_rate,
                clearing_per_share=self._money(tiered.clearing_per_share),
                clearing_maximum_rate=tiered.clearing_maximum_rate,
                nyse_pass_through_rate=tiered.nyse_pass_through_rate,
                finra_pass_through_rate=tiered.finra_pass_through_rate,
                exchange_fee_per_share=self._money(tiered.exchange_fee_per_share),
            )
        )

    def _costs(self, commission: Commission) -> TradingCosts:
        money = self._money
        return TradingCosts(
            commission=commission,
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
        risk: Its own position limits from the file's ``[risk]`` table, each at least
            as strict as the active risk profile's; empty without the table.
    """

    strategy_id: str
    budget: Decimal
    plugin: str
    parameters: Mapping[str, Any]
    source: str
    risk: StrategyRiskLimits = field(default_factory=StrategyRiskLimits)


@dataclass(frozen=True, slots=True)
class TycheConfig:
    """The validated configuration of one workspace.

    Attributes:
        workspace: Where the configuration was loaded from.
        market_profile: The active market profile.
        costs: What trading costs under that profile, and when trades settle.
        tiered_costs: The same under IBKR Pro Tiered, from the costs file's optional
            ``[tiered]`` table, for ``tyche capital`` to compare; ``None`` without it.
            Backtests never use it.
        strategies: The configured strategy instances, ordered by id.
        backtest: The starting cash and the reserved holdout (ADR-0024).
        guardrails: The absolute limits, from ``config/guardrails.toml`` (ADR-0032).
        risk_profile: The active risk profile, from ``config/risk/<name>.toml``.
        risk_profiles: The name of every profile in ``config/risk/``, sorted. Each was
            checked against the guardrails; only the active one is in the hash.
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
    guardrails: Guardrails
    risk_profile: RiskProfile
    risk_profiles: tuple[str, ...]
    tiered_costs: TradingCosts | None = None

    @property
    def budgets(self) -> dict[str, Decimal]:
        """Each strategy's budget, by id."""
        return {spec.strategy_id: spec.budget for spec in self.strategies}

    @property
    def risk_limits(self) -> RiskLimits:
        """The guardrails, the active risk profile and each strategy's own limits."""
        return RiskLimits(
            self.guardrails,
            self.risk_profile,
            {spec.strategy_id: spec.risk for spec in self.strategies},
        )


def load_config(workspace: Workspace, risk_profile: str = DEFAULT_RISK_PROFILE) -> TycheConfig:
    """Load and validate the workspace configuration, or raise ``ConfigError``.

    Args:
        workspace: The workspace to read.
        risk_profile: The risk profile to make active. Every profile in
            ``config/risk/`` is checked against the guardrails whichever is chosen, so
            that switching to any of them later cannot fail on a limit.
    """
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
        tiered_costs = costs_file.tiered_domain()
    except ValueError as error:
        raise ConfigError(f"{costs_name}: {error}") from None
    if costs.currency not in profile.cash_currencies:
        raise ConfigError(
            f"{costs_name}: costs are in {costs.currency}, but market profile "
            f"{profile.name} holds cash in {', '.join(profile.cash_currencies)}"
        )

    guardrails_name = workspace.relative(workspace.guardrails)
    guardrails_file, guardrails = _load_guardrails(workspace)
    uncapped = guardrails.uncapped(profile.cash_currencies)
    if uncapped:
        raise ConfigError(
            f"{guardrails_name}: market profile {profile.name} holds cash in "
            f"{', '.join(uncapped)}, but max_total_capital and max_order_value need a cap "
            "in each such currency; Tyche cannot convert between currencies yet"
        )
    profiles, profile_files = _load_risk_profiles(workspace, guardrails)
    try:
        require_risk_profile_name(risk_profile)
    except ValueError as error:
        raise ConfigError(f"risk profile: {error}") from None
    active = profiles.get(risk_profile)
    if active is None:
        missing = workspace.relative(workspace.risk_dir / f"{risk_profile}.toml")
        if profiles:
            hint = f"available: {', '.join(sorted(profiles))}"
        else:
            hint = "there are none; `tyche init` on a scratch folder writes `default` to copy"
        raise ConfigError(
            f"no risk profile named {risk_profile!r}: {missing} does not exist; {hint}"
        )
    active_name = workspace.relative(workspace.risk_dir / f"{risk_profile}.toml")

    strategies, strategy_files = _load_strategies(workspace, tyche, tyche_name)
    for spec in strategies:
        breaches = spec.risk.breaches(active)
        if breaches:
            raise ConfigError(
                _describe_breaches(
                    f"{spec.source}: [risk] may only be stricter than the active risk "
                    f"profile {risk_profile!r} ({active_name})",
                    breaches,
                    "risk.",
                )
            )

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
        guardrails_name: guardrails_file,
        active_name: profile_files[risk_profile],
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
        guardrails=guardrails,
        risk_profile=active,
        risk_profiles=tuple(sorted(profiles)),
        tiered_costs=tiered_costs,
    )


def _load_guardrails(workspace: Workspace) -> tuple[GuardrailsFile, Guardrails]:
    name = workspace.relative(workspace.guardrails)
    if not workspace.guardrails.is_file():
        raise ConfigError(
            f"{name} is missing: Tyche refuses to start without its hard limits. "
            "`tyche init` on a scratch folder writes an example to copy; the values are "
            "yours to set"
        )
    guardrails_file = _read(workspace, workspace.guardrails, GuardrailsFile)
    try:
        return guardrails_file, guardrails_file.to_domain()
    except ValueError as error:
        raise ConfigError(f"{name}: {error}") from None


def _load_risk_profiles(
    workspace: Workspace, guardrails: Guardrails
) -> tuple[dict[str, RiskProfile], dict[str, RiskProfileFile]]:
    """Every profile in ``config/risk/``, each checked against the guardrails."""
    guardrails_name = workspace.relative(workspace.guardrails)
    profiles: dict[str, RiskProfile] = {}
    files: dict[str, RiskProfileFile] = {}
    paths = sorted(workspace.risk_dir.glob("*.toml")) if workspace.risk_dir.is_dir() else []
    for path in paths:
        name = workspace.relative(path)
        try:
            require_risk_profile_name(path.stem)
        except ValueError as error:
            raise ConfigError(f"{name}: {error}") from None
        risk_file = _read(workspace, path, RiskProfileFile)
        try:
            profile = risk_file.to_domain(path.stem)
        except ValueError as error:
            raise ConfigError(f"{name}: {error}") from None
        breaches = guardrails.breaches(profile)
        if breaches:
            raise ConfigError(
                _describe_breaches(
                    f"{name}: a risk profile may not exceed the guardrails ({guardrails_name})",
                    breaches,
                    "",
                )
            )
        profiles[path.stem] = profile
        files[path.stem] = risk_file
    return profiles, files


def _describe_breaches(heading: str, breaches: tuple[LimitBreach, ...], prefix: str) -> str:
    lines = [heading]
    for breach in breaches:
        lines.append(
            f"  {prefix}{breach.key} = {breach.value} is above {breach.limit_key} = {breach.limit}"
        )
    return "\n".join(lines)


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
        try:
            limits = (
                strategy_file.risk.to_domain()
                if strategy_file.risk is not None
                else StrategyRiskLimits()
            )
        except ValueError as error:
            raise ConfigError(f"{name}: risk: {error}") from None
        specs.append(
            StrategySpec(
                strategy_id,
                tyche.strategies[strategy_id],
                strategy_file.plugin,
                strategy_file.parameters,
                name,
                limits,
            )
        )
    return tuple(specs), files


@dataclass(frozen=True, slots=True)
class SweepSpec:
    """A parameter sweep, read from its file and checked against the configuration.

    Attributes:
        name: The file's name without ``.toml``.
        strategy_id: The configured strategy whose parameters are swept.
        grid: Each swept parameter's values, in the order written.
        source: The sweep file, relative to the workspace, for messages.
        snapshot: The file's values, as a run record stores them.
        sweep_hash: Fingerprint of ``snapshot``. The config hash does not cover sweep
            files, so a record states both.
    """

    name: str
    strategy_id: str
    grid: Mapping[str, tuple[Any, ...]]
    source: str
    snapshot: Mapping[str, Any]
    sweep_hash: str


def load_sweep(config: TycheConfig, name: str) -> SweepSpec:
    """Read ``config/sweeps/<name>.toml``, or raise ``ConfigError`` naming the problem.

    The strategy must be configured with a budget: a sweep varies one strategy of the
    configured set and runs the others as they are.
    """
    workspace = config.workspace
    try:
        require_strategy_id(name)
    except ValueError as error:
        raise ConfigError(f"sweep name: {error}") from None
    path = workspace.sweeps_dir / f"{name}.toml"
    source = workspace.relative(path)
    if not path.is_file():
        raise ConfigError(f"no sweep named {name!r}: {source} does not exist")
    sweep = _read(workspace, path, SweepFile)
    if sweep.strategy not in config.budgets:
        configured = ", ".join(sorted(config.budgets)) or "none"
        raise ConfigError(
            f"{source}: strategy: {sweep.strategy!r} has no budget under [strategies] in "
            f"config/tyche.toml; configured: {configured}"
        )
    if not sweep.grid:
        raise ConfigError(f"{source}: grid: name at least one parameter and its values")
    for key, values in sweep.grid.items():
        if not values:
            raise ConfigError(f"{source}: grid.{key}: list at least one value")
        canonical = [json.dumps(v, sort_keys=True) for v in values]
        if len(set(canonical)) != len(canonical):
            raise ConfigError(f"{source}: grid.{key}: a value is listed more than once")
    snapshot = sweep.model_dump(mode="json")
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return SweepSpec(
        name=name,
        strategy_id=sweep.strategy,
        grid={key: tuple(values) for key, values in sweep.grid.items()},
        source=source,
        snapshot=snapshot,
        sweep_hash="sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def config_snapshot(files: Mapping[str, BaseModel]) -> dict[str, Any]:
    """Validated config files as plain JSON values, keyed by their path in the workspace.

    An optional table that is absent (``None``) is left out, so that adding one to the
    schema does not change the hash of a workspace that does not use it. TOML has no
    null, so no value read from a file is ``None``.
    """
    return {path: model.model_dump(mode="json", exclude_none=True) for path, model in files.items()}


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
