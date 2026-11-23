"""Risk types: what the risk layer changed, and why (ADR-0033, ADR-0034, ADR-0035).

A ``RiskAdjustment`` records one change the risk gate made to one sleeve's
contribution to one instrument: which rule, measured over what (``RiskScope``), what
it did (``RiskAction``), the weight before and after, and the limit. The gate
publishes each as a ``RiskEvent`` and lists them all on the ``ApprovedPortfolioEvent``,
so the journal can say why a target was not approved as proposed.

``MoneyLimits`` are the guardrails' money caps in one currency, in the form execution
and the gate use them. An ``OrderAdjustment`` records one purchase execution cut, in
shares, to fit them; it is published as a ``RiskEvent`` too.

An ``AccountTrigger`` records one of the two account rules reaching its limit at a
session close: the daily loss limit (no entries or additions at that close) or the
drawdown kill (a halt that lasts until a manual restart). It is published as a
``RiskEvent``, and the halt is carried on every ``ApprovedPortfolioEvent`` after it.

A ``Kill`` is the kill switch, engaged by hand (ADR-0039): no new orders from the next
decision on, and with ``flatten``, every holding sold. It is carried on every
``ApprovedPortfolioEvent`` while it stays engaged.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.signals import require_strategy_id
from tyche.core.domain.validation import require_utc


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

    DAILY_LOSS_LIMIT = "daily_loss_limit"
    """The account lost at least this much since the previous close: no entries or
    additions at this close (ADR-0015)."""

    DRAWDOWN_KILL = "drawdown_kill"
    """The account fell at least this much below its peak: trading halts until a manual
    restart."""


ORDER_RULES = frozenset({RiskRule.MAX_ORDER_VALUE, RiskRule.MAX_TOTAL_CAPITAL})
"""The rules execution's order check applies; the gate applies the others."""

ACCOUNT_RULES = frozenset({RiskRule.DAILY_LOSS_LIMIT, RiskRule.DRAWDOWN_KILL})
"""The rules measured on the account's equity, recorded as an ``AccountTrigger``."""


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
        if self.rule is RiskRule.DRAWDOWN_KILL:
            raise ValueError(f"{label}: the drawdown kill halts; it adjusts nothing")
        if self.rule is RiskRule.DAILY_LOSS_LIMIT and self.scope is not RiskScope.ACCOUNT:
            raise ValueError(f"{label}: the daily loss limit is measured on the account")
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


@dataclass(frozen=True, slots=True)
class AccountTrigger:
    """An account rule that reached its limit at one session close (ADR-0015, ADR-0035).

    Both rules compare two equity values of the same currency: the daily loss limit
    this close's with the previous close's, the drawdown kill this close's with the
    highest close so far. ``loss`` is the fall as a fraction of the reference.

    Attributes:
        rule: ``daily_loss_limit`` or ``drawdown_kill``.
        at: The session close it was measured at.
        reference: The previous close's equity, or the peak equity.
        equity: The equity at ``at``.
        limit: The profile's limit, a fraction of ``reference``.
        reason: The gate's explanation, for the journal.
    """

    rule: RiskRule
    at: datetime
    reference: Money
    equity: Money
    limit: Decimal
    reason: str

    @property
    def scope(self) -> RiskScope:
        return RiskScope.ACCOUNT

    @property
    def loss(self) -> Decimal:
        """The fall from ``reference`` to ``equity``, as a fraction of ``reference``."""
        return (self.reference.amount - self.equity.amount) / self.reference.amount

    def __post_init__(self) -> None:
        label = f"{self.rule} trigger"
        if self.rule not in ACCOUNT_RULES:
            raise ValueError(f"{label}: {self.rule} is not an account rule")
        require_utc(self.at, f"{label} at")
        if self.reference.currency is not self.equity.currency:
            raise ValueError(
                f"{label}: the reference is in {self.reference.currency}, the equity in "
                f"{self.equity.currency}"
            )
        if not self.reference.is_positive:
            raise ValueError(f"{label}: the reference equity must be above 0")
        if not isinstance(self.limit, Decimal) or not 0 < self.limit < 1:
            raise ValueError(f"{label}: the limit must be above 0 and below 1, got {self.limit}")
        if self.loss < self.limit:
            raise ValueError(
                f"{label}: a fall of {self.loss} from {self.reference} to {self.equity} is "
                f"below the limit {self.limit}"
            )
        if not self.reason.strip():
            raise ValueError(f"{label}: needs a reason")


@dataclass(frozen=True, slots=True)
class Kill:
    """The kill switch, engaged by hand (ADR-0039).

    While it is engaged, the risk gate approves nothing at every decision. Without
    ``flatten``, execution keeps every holding and sends no order, as under the drawdown
    halt; protective stops already resting stay. With ``flatten``, every holding of every
    sleeve is approved at zero: execution cancels each resting stop, then sells.

    It never reaches the broker by any other path: an order already working when it is
    engaged is left to fill or expire.

    Attributes:
        reason: Why it was engaged, as given; for a flag file with nothing readable in
            it, what was found.
        flatten: Sell every holding at the next decision, rather than keep them.
        engaged_at: When it was engaged, or ``None`` when the flag does not say.
    """

    reason: str
    flatten: bool = False
    engaged_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("kill switch: needs a reason")
        if not isinstance(self.flatten, bool):
            raise ValueError(f"kill switch: flatten must be true or false, got {self.flatten!r}")
        if self.engaged_at is not None:
            require_utc(self.engaged_at, "kill switch engaged_at")
