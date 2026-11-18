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

from tyche.config.workspace import Workspace
from tyche.core.domain import (
    AssetClass,
    CommissionSchedule,
    Currency,
    MarketProfile,
    Money,
    RegulatoryFees,
    TradingCosts,
    UniverseRules,
    require_profile_name,
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


class TycheFile(_ConfigFile):
    """``config/tyche.toml``."""

    schema_version: StrictInt
    market_profile: StrictStr


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


class UniverseFile(_ConfigFile):
    """The ``[universe]`` table of a market profile file."""

    asset_classes: tuple[AssetClass, ...]
    currency: Currency
    min_price: ExactDecimal
    min_average_dollar_volume: ExactDecimal
    liquidity_sessions: StrictInt
    quality_sessions: StrictInt

    def to_domain(self) -> UniverseRules:
        return UniverseRules(
            asset_classes=self.asset_classes,
            min_price=Money(self.min_price, self.currency),
            min_average_dollar_volume=Money(self.min_average_dollar_volume, self.currency),
            liquidity_sessions=self.liquidity_sessions,
            quality_sessions=self.quality_sessions,
        )


class MarketProfileFile(_ConfigFile):
    """``config/markets/<NAME>.toml``."""

    name: StrictStr
    cash_currencies: tuple[Currency, ...]
    calendars: tuple[StrictStr, ...]
    universe: UniverseFile

    def to_domain(self) -> MarketProfile:
        return MarketProfile(
            name=self.name,
            cash_currencies=self.cash_currencies,
            calendars=self.calendars,
            universe=self.universe.to_domain(),
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
class TycheConfig:
    """The validated configuration of one workspace.

    Attributes:
        workspace: Where the configuration was loaded from.
        market_profile: The active market profile.
        costs: What trading costs under that profile, and when trades settle.
        config_hash: Fingerprint of every loaded setting. Two runs with the same hash
            used the same configuration. Comments, blank lines and key order do not
            affect it; any change of value does.
    """

    workspace: Workspace
    market_profile: MarketProfile
    costs: TradingCosts
    config_hash: str


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

    return TycheConfig(
        workspace=workspace,
        market_profile=profile,
        costs=costs,
        config_hash=config_hash(
            {tyche_name: tyche, profile_name: profile_file, costs_name: costs_file}
        ),
    )


def config_hash(files: Mapping[str, BaseModel]) -> str:
    """Fingerprint validated config files, keyed by their path in the workspace.

    The hash covers parsed values, not file text, so reformatting a file or editing a
    comment does not change it. Secrets in ``.env`` are never part of it.
    """
    payload = {
        "scheme": HASH_SCHEME,
        "files": {path: model.model_dump(mode="json") for path, model in files.items()},
    }
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
