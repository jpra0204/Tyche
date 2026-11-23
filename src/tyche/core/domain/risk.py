"""Risk types: what the risk layer changed, and why (ADR-0033, ADR-0034).

A ``RiskAdjustment`` records one change the risk gate made to one sleeve's
contribution to one instrument: which rule, measured over what (``RiskScope``), what
it did (``RiskAction``), the weight before and after, and the limit. The gate
publishes each as a ``RiskEvent`` and lists them all on the ``ApprovedPortfolioEvent``,
so the journal can say why a target was not approved as proposed.

``MoneyLimits`` are the guardrails' money caps in one currency, in the form execution
and the gate use them. An ``OrderAdjustment`` records one purchase execution cut, in
shares, to fit them; it is published as a ``RiskEvent`` too.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.signals import require_strategy_id


class RiskRule(StrEnum):
    """The limit of a risk profile, or of a strategy's ``[risk]`` table, that applied."""

    RISK_PER_TRADE = "risk_per_trade"
    """An entry or addition with a stop could lose more than this before the stop."""

    MAX_POSITION_SIZE = "max_position_size"
    """A position would be larger than this fraction of equity."""

    MAX_OPEN_POSITIONS = "max_open_positions"
    """An entry would hold more instruments than this."""

    MAX_ORDER_VALUE = "max_order_value"
    """A purchase would be worth more than the guardrails' order cap."""

    MAX_TOTAL_CAPITAL = "max_total_capital"
    """A purchase would take what is invested above the guardrails' capital cap."""


ORDER_RULES = frozenset({RiskRule.MAX_ORDER_VALUE, RiskRule.MAX_TOTAL_CAPITAL})
"""The rules execution's order check applies; the gate applies the others."""


class RiskScope(StrEnum):
    """What the limit was measured over."""

    STRATEGY = "strategy"
    """One sleeve: its own trade, its own position, or its own count of positions."""

    ACCOUNT = "account"
    """The whole account: an instrument across every sleeve, or every instrument held."""

    ORDER = "order"
    """One order, after execution sized it in shares."""


class RiskAction(StrEnum):
    """What the gate did to the contribution."""

    SHRINK = "shrink"
    """Approved with a smaller weight."""

    BLOCK = "block"
    """Not approved at all: the sleeve does not enter the instrument, or the purchase is
    not sent."""


@dataclass(frozen=True, slots=True)
class RiskAdjustment:
    """One change the risk gate made to one sleeve's contribution to one instrument.

    Attributes:
        rule: The limit that applied.
        scope: Whether it was measured on the sleeve alone or on the whole account.
        action: Shrunk or blocked.
        strategy_id: The sleeve whose contribution changed.
        instrument: The instrument.
        before: The contribution's weight of account equity when the rule applied.
        after: Its weight once the rule applied; zero when blocked.
        limit: The limit's value: a fraction of equity, or a number of positions.
        reason: The gate's explanation, for the journal.
    """

    rule: RiskRule
    scope: RiskScope
    action: RiskAction
    strategy_id: str
    instrument: Instrument
    before: Decimal
    after: Decimal
    limit: Decimal
    reason: str

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        label = f"risk adjustment of {self.strategy_id} in {self.instrument}"
        for name in ("before", "after", "limit"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{label}: {name} must be a Decimal of at least 0, got {value!r}")
        if not self.after < self.before:
            raise ValueError(
                f"{label}: an adjustment only lowers a weight, got {self.before} to {self.after}"
            )
        if (self.action is RiskAction.BLOCK) != (self.after == 0):
            raise ValueError(f"{label}: a block, and only a block, approves a weight of zero")
        if self.rule in ORDER_RULES or self.scope is RiskScope.ORDER:
            raise ValueError(f"{label}: order rules are recorded as an OrderAdjustment")
        if not self.reason.strip():
            raise ValueError(f"{label}: needs a reason")


@dataclass(frozen=True, slots=True)
class MoneyLimits:
    """The guardrails' money caps in one currency (ADR-0032, ADR-0034).

    Attributes:
        capital: The most Tyche may trade with. Execution sizes every position as if
            equity were at most this, and no purchase may take what is invested above it.
        order: The most one purchase may be worth.
    """

    capital: Money
    order: Money

    def __post_init__(self) -> None:
        if self.capital.currency is not self.order.currency:
            raise ValueError(
                f"money limits: the capital cap is in {self.capital.currency}, the order cap "
                f"in {self.order.currency}"
            )
        if not self.capital.is_positive or not self.order.is_positive:
            raise ValueError("money limits: both caps must be above 0")
        if self.capital < self.order:
            raise ValueError(
                f"money limits: the order cap {self.order} is above the capital cap {self.capital}"
            )

    def trading_equity(self, equity: Money) -> Money:
        """The equity Tyche sizes with: the account's, or the capital cap if that is lower."""
        return min(equity, self.capital)


@dataclass(frozen=True, slots=True)
class OrderAdjustment:
    """One purchase execution cut to fit the guardrails' money caps (ADR-0034).

    Purchases are netted across sleeves, so an order adjustment is per instrument, in
    shares; execution splits the cut between the sleeves the purchase serves, as it
    does a cut for cash.

    Attributes:
        rule: ``max_order_value`` or ``max_total_capital``.
        action: Shrunk, or blocked when not one share fits.
        instrument: What was to be bought.
        before: Shares before the rule applied.
        after: Shares after it; zero when blocked.
        limit: The cap.
        reason: Execution's explanation, for the journal.
    """

    rule: RiskRule
    action: RiskAction
    instrument: Instrument
    before: Decimal
    after: Decimal
    limit: Money
    reason: str

    @property
    def scope(self) -> RiskScope:
        return RiskScope.ORDER

    def __post_init__(self) -> None:
        label = f"order adjustment of {self.instrument}"
        if self.rule not in ORDER_RULES:
            raise ValueError(f"{label}: {self.rule} is not an order rule")
        for name in ("before", "after"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{label}: {name} must be a Decimal of at least 0, got {value!r}")
            if value != value.to_integral_value():
                raise ValueError(f"{label}: {name} must be whole shares, got {value}")
        if not self.after < self.before:
            raise ValueError(
                f"{label}: an adjustment only lowers a purchase, got {self.before} to {self.after}"
            )
        if (self.action is RiskAction.BLOCK) != (self.after == 0):
            raise ValueError(f"{label}: a block, and only a block, buys nothing")
        if self.limit.currency is not self.instrument.currency or not self.limit.is_positive:
            raise ValueError(
                f"{label}: the limit must be a positive {self.instrument.currency} amount"
            )
        if not self.reason.strip():
            raise ValueError(f"{label}: needs a reason")
