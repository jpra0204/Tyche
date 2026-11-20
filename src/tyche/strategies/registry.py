"""The registry of built-in strategy plugins, and how one is built from config (ADR-0022).

A workspace names a plugin in ``config/strategies/<id>.toml`` and gives its
parameters. Each plugin declares those parameters as a strict pydantic model, so a
typo or a wrong type is refused with the file and key named, before any run starts.

A plugin builds instruments through an ``InstrumentLookup`` handed in by the runtime,
which checks them against the market profile; a strategy never imports the config.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictStr

from tyche.core.domain import AssetClass, Instrument
from tyche.core.pipeline.signals import Strategy


class InstrumentLookup(Protocol):
    """Builds an instrument from a symbol and an exchange, checked against the profile."""

    def __call__(self, symbol: str, exchange: str, asset_class: AssetClass) -> Instrument: ...


class Parameters(BaseModel):
    """Base for a plugin's parameters: immutable, and unknown keys are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _exact_decimal(value: object) -> Decimal:
    """Accept a decimal written as a string, and nothing else.

    The same rule as the workspace files (ADR-0012): TOML reads ``2.5`` without quotes
    as a binary float, so a decimal parameter is written ``"2.5"``.
    """
    if not isinstance(value, str):
        raise ValueError('write decimals as strings, such as "2.5", so they stay exact')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"not a decimal number: {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"must be a finite number, got {value!r}")
    return number


ExactDecimal = Annotated[Decimal, BeforeValidator(_exact_decimal)]
"""A decimal parameter, written as a string in the strategy file."""


class InstrumentParameters(Parameters):
    """One instrument in a strategy's parameters: ``{ symbol, exchange, asset_class }``."""

    symbol: StrictStr
    exchange: StrictStr
    asset_class: AssetClass

    def build(self, lookup: InstrumentLookup) -> Instrument:
        """The instrument, checked against the market profile by ``lookup``."""
        return lookup(self.symbol, self.exchange, self.asset_class)


@dataclass(frozen=True, slots=True)
class Plugin[P: Parameters]:
    """A built-in strategy that config can name.

    Attributes:
        name: What ``plugin =`` says in a strategy file.
        parameters: The model its ``[parameters]`` table must match.
        build: Makes a strategy instance from its id and validated parameters.
    """

    name: str
    parameters: type[P]
    build: Callable[[str, P, InstrumentLookup], Strategy]

    def create(
        self, strategy_id: str, raw: Mapping[str, Any], lookup: InstrumentLookup
    ) -> Strategy:
        """Validate ``raw`` and build the instance. Raises pydantic's ``ValidationError``."""
        return self.build(strategy_id, self.parameters.model_validate(dict(raw)), lookup)
