"""The registry of built-in strategy plugins, and how one is built from config (ADR-0022).

A workspace names a plugin in ``config/strategies/<id>.toml`` and gives its
parameters. Each plugin declares those parameters as a strict pydantic model, so a
typo or a wrong type is refused with the file and key named, before any run starts.

A plugin builds instruments through an ``InstrumentLookup`` handed in by the runtime,
which checks them against the market profile; a strategy never imports the config.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from tyche.core.domain import AssetClass, Instrument
from tyche.core.pipeline.signals import Strategy


class InstrumentLookup(Protocol):
    """Builds an instrument from a symbol and an exchange, checked against the profile."""

    def __call__(self, symbol: str, exchange: str, asset_class: AssetClass) -> Instrument: ...


class Parameters(BaseModel):
    """Base for a plugin's parameters: immutable, and unknown keys are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


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
