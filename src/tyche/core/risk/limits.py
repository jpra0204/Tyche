"""Risk limits in three layers: guardrails, named profiles, strategy overrides (ADR-0032).

Each layer may only be stricter than the one above it:

1. ``Guardrails``: absolute ceilings, one set per workspace, edited only by Pablo.
   Every profile limit has a ceiling here, so no profile can switch a protection off.
   Money caps are stated per cash currency until currency conversion exists.
2. ``RiskProfile``: a named set of limits (``default``, ``safecash``, ...), chosen per
   run. Every value must be within the guardrails.
3. ``StrategyRiskLimits``: optional per-strategy position limits. Each value given
   must be at least as strict as the active profile's.

This module only describes the limits and checks that the layers fit together. It
applies nothing: the gate applies the position rules from Phase 2's PR 2, and the
account rules from PR 4. A check returns every ``LimitBreach`` at once, as plain data,
so that the config layer can name the file each one came from.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from tyche.core.domain import Currency, Money

_PROFILE_NAME = re.compile(r"[a-z][a-z0-9_-]*")

DEFAULT_RISK_PROFILE = "default"
"""The profile a run uses when none is chosen."""


def require_risk_profile_name(name: str) -> None:
    """Raise ``ValueError`` unless ``name`` is a valid risk profile name.

    A profile's name is its file name in ``config/risk/``, so it is checked before it
    becomes part of a path: a name such as ``../secrets`` never reaches the file system.
    """
    if not _PROFILE_NAME.fullmatch(name):
        raise ValueError(
            f"invalid risk profile name {name!r}: expected lower-case letters, digits, "
            "'_' or '-', starting with a letter, such as 'default' or 'test-a'"
        )


def _require_fraction(name: str, value: Decimal, *, below_one: bool) -> None:
    """A fraction of equity: above 0, and at most 1 (or below 1)."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {value!r}")
    if below_one:
        if not 0 < value < 1:
            raise ValueError(f"{name} must be above 0 and below 1, got {value}")
    elif not 0 < value <= 1:
        raise ValueError(f"{name} must be above 0 and at most 1, got {value}")


def _require_count(name: str, value: int) -> None:
    # bool is an int in Python; a limit of True positions is a mistake, not a 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a whole number of at least 1, got {value!r}")


@dataclass(frozen=True, slots=True)
class LimitBreach:
    """One value that is looser than the limit above it.

    Attributes:
        key: The key that breaks the limit, as written in its file.
        value: Its value.
        limit_key: The key of the limit it breaks, as written in the layer above.
        limit: That limit's value.
    """

    key: str
    value: str
    limit_key: str
    limit: str


@dataclass(frozen=True, slots=True)
class RiskProfile:
    """A named set of risk limits, chosen per run (brief §7.1).

    Every fraction is of account equity: 0.01 is 1%.

    Attributes:
        name: The profile's name, which is its file name in ``config/risk/``.
        risk_per_trade: The most one position may lose before its stop triggers. Applies
            only to targets that carry a stop (ADR-0006).
        max_open_positions: How many instruments may be held at once.
        max_position_size: The largest position, at the price it is sized at.
        daily_loss_limit: A loss from one close to the next of at least this much
            blocks new entries and additions at that close (ADR-0015).
        drawdown_kill: A fall of at least this much from peak equity halts everything
            until a manual restart.
    """

    name: str
    risk_per_trade: Decimal
    max_open_positions: int
    max_position_size: Decimal
    daily_loss_limit: Decimal
    drawdown_kill: Decimal

    def __post_init__(self) -> None:
        require_risk_profile_name(self.name)
        _require_fraction("risk_per_trade", self.risk_per_trade, below_one=False)
        _require_count("max_open_positions", self.max_open_positions)
        _require_fraction("max_position_size", self.max_position_size, below_one=False)
        # A limit of 100% could never trigger: it would switch the protection off.
        _require_fraction("daily_loss_limit", self.daily_loss_limit, below_one=True)
        _require_fraction("drawdown_kill", self.drawdown_kill, below_one=True)


@dataclass(frozen=True, slots=True)
class StrategyRiskLimits:
    """Position limits for one strategy, each stricter than the active profile's or absent.

    Only position rules can be set per strategy: the daily loss limit and the drawdown
    kill are measured on the whole account (ADR-0032). Fractions are of account equity,
    like the profile's; ``max_open_positions`` counts the strategy's own sleeve.

    Attributes:
        risk_per_trade: Overrides the profile's, or ``None`` to use it.
        max_open_positions: Overrides the profile's, or ``None`` to use it.
        max_position_size: Overrides the profile's, or ``None`` to use it.
    """

    risk_per_trade: Decimal | None = None
    max_open_positions: int | None = None
    max_position_size: Decimal | None = None

    def __post_init__(self) -> None:
        if self.risk_per_trade is not None:
            _require_fraction("risk_per_trade", self.risk_per_trade, below_one=False)
        if self.max_open_positions is not None:
            _require_count("max_open_positions", self.max_open_positions)
        if self.max_position_size is not None:
            _require_fraction("max_position_size", self.max_position_size, below_one=False)

    def breaches(self, profile: RiskProfile) -> tuple[LimitBreach, ...]:
        """Every override looser than ``profile``. Equal to the profile's is allowed."""
        pairs: list[tuple[str, Decimal | int | None, Decimal | int]] = [
            ("risk_per_trade", self.risk_per_trade, profile.risk_per_trade),
            ("max_open_positions", self.max_open_positions, profile.max_open_positions),
            ("max_position_size", self.max_position_size, profile.max_position_size),
        ]
        return tuple(
            LimitBreach(key, str(value), key, str(limit))
            for key, value, limit in pairs
            if value is not None and value > limit
        )


def _require_caps(name: str, caps: tuple[Money, ...]) -> None:
    if not caps:
        raise ValueError(f"{name}: give a cap for at least one currency")
    seen: set[Currency] = set()
    for cap in caps:
        if cap.amount <= 0:
            raise ValueError(f"{name}: the {cap.currency} cap must be above 0, got {cap.amount}")
        if cap.currency in seen:
            raise ValueError(f"{name}: {cap.currency} is listed more than once")
        seen.add(cap.currency)


@dataclass(frozen=True, slots=True)
class Guardrails:
    """Absolute limits that no risk profile may exceed (ADR-0010, ADR-0032).

    Long only and no leverage are not attributes: they are the only trading Tyche can
    do (brief §2), and the guardrails file states them so that changing that one day
    is a deliberate edit there.

    Attributes:
        max_risk_per_trade: Ceiling for every profile's ``risk_per_trade``.
        max_open_positions: Ceiling for every profile's ``max_open_positions``.
        max_position_size: Ceiling for every profile's ``max_position_size``.
        max_daily_loss_limit: Ceiling for every profile's ``daily_loss_limit``.
        max_drawdown_kill: Ceiling for every profile's ``drawdown_kill``.
        max_total_capital: The most capital Tyche may trade with, one cap per cash
            currency. Converting between currencies arrives in Phase 4; until then a
            market profile needs a cap in each currency it holds.
        max_order_value: The largest single order, one cap per cash currency, each at
            most that currency's capital cap.
    """

    max_risk_per_trade: Decimal
    max_open_positions: int
    max_position_size: Decimal
    max_daily_loss_limit: Decimal
    max_drawdown_kill: Decimal
    max_total_capital: tuple[Money, ...]
    max_order_value: tuple[Money, ...]

    def __post_init__(self) -> None:
        _require_fraction("max_risk_per_trade", self.max_risk_per_trade, below_one=False)
        _require_count("max_open_positions", self.max_open_positions)
        _require_fraction("max_position_size", self.max_position_size, below_one=False)
        _require_fraction("max_daily_loss_limit", self.max_daily_loss_limit, below_one=True)
        _require_fraction("max_drawdown_kill", self.max_drawdown_kill, below_one=True)
        _require_caps("max_total_capital", self.max_total_capital)
        _require_caps("max_order_value", self.max_order_value)
        for order_cap in self.max_order_value:
            capital_cap = self.capital_cap(order_cap.currency)
            if capital_cap is None:
                raise ValueError(
                    f"max_order_value: {order_cap.currency} has an order cap but no "
                    "max_total_capital cap"
                )
            if order_cap.amount > capital_cap.amount:
                raise ValueError(
                    f"max_order_value: the {order_cap.currency} cap {order_cap.amount} is "
                    f"above max_total_capital's {capital_cap.amount}"
                )

    def capital_cap(self, currency: Currency) -> Money | None:
        """The capital cap in ``currency``, or ``None`` if there is none."""
        return next((cap for cap in self.max_total_capital if cap.currency == currency), None)

    def order_cap(self, currency: Currency) -> Money | None:
        """The order-value cap in ``currency``, or ``None`` if there is none."""
        return next((cap for cap in self.max_order_value if cap.currency == currency), None)

    def uncapped(self, currencies: Iterable[Currency]) -> tuple[Currency, ...]:
        """The currencies among ``currencies`` that lack a capital or an order cap."""
        return tuple(
            currency
            for currency in currencies
            if self.capital_cap(currency) is None or self.order_cap(currency) is None
        )

    def breaches(self, profile: RiskProfile) -> tuple[LimitBreach, ...]:
        """Every value of ``profile`` above its ceiling. Equal to the ceiling is allowed."""
        pairs: list[tuple[str, Decimal | int, str, Decimal | int]] = [
            ("risk_per_trade", profile.risk_per_trade, "max_risk_per_trade",
             self.max_risk_per_trade),
            ("max_open_positions", profile.max_open_positions, "max_open_positions",
             self.max_open_positions),
            ("max_position_size", profile.max_position_size, "max_position_size",
             self.max_position_size),
            ("daily_loss_limit", profile.daily_loss_limit, "max_daily_loss_limit",
             self.max_daily_loss_limit),
            ("drawdown_kill", profile.drawdown_kill, "max_drawdown_kill",
             self.max_drawdown_kill),
        ]  # fmt: skip
        return tuple(
            LimitBreach(key, str(value), limit_key, str(limit))
            for key, value, limit_key, limit in pairs
            if value > limit
        )
