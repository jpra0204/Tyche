"""Risk types: what the risk gate changed in a proposed portfolio, and why (ADR-0033).

A ``RiskAdjustment`` records one change the gate made to one sleeve's contribution to
one instrument: which rule, measured over what (``RiskScope``), what it did
(``RiskAction``), the weight before and after, and the limit. The gate publishes each
as a ``RiskEvent`` and lists them all on the ``ApprovedPortfolioEvent``, so the journal
can say why a target was not approved as proposed.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.signals import require_strategy_id


class RiskRule(StrEnum):
    """The limit of a risk profile, or of a strategy's ``[risk]`` table, that applied."""

    RISK_PER_TRADE = "risk_per_trade"
    """An entry or addition with a stop could lose more than this before the stop."""

    MAX_POSITION_SIZE = "max_position_size"
    """A position would be larger than this fraction of equity."""

    MAX_OPEN_POSITIONS = "max_open_positions"
    """An entry would hold more instruments than this."""


class RiskScope(StrEnum):
    """What the limit was measured over."""

    STRATEGY = "strategy"
    """One sleeve: its own trade, its own position, or its own count of positions."""

    ACCOUNT = "account"
    """The whole account: an instrument across every sleeve, or every instrument held."""


class RiskAction(StrEnum):
    """What the gate did to the contribution."""

    SHRINK = "shrink"
    """Approved with a smaller weight."""

    BLOCK = "block"
    """Not approved at all: the sleeve does not enter the instrument."""


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
        if not self.reason.strip():
            raise ValueError(f"{label}: needs a reason")
