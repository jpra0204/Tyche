"""Execution types: the rules for turning approved weights into shares, and the plan (ADR-0023).

``ExecutionRules`` belong to a market profile (``[execution]`` in
``config/markets/<NAME>.toml``). A ``PlanLine`` says, for one sleeve and one instrument
at one decision cycle, what execution aimed for and how it got there; the
``ExecutionPlanEvent`` carries one per sleeve and instrument, so the journal can say
why a target was not traded exactly.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.signals import require_strategy_id


def _require_whole(value: Decimal, what: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} must be a finite Decimal, got {value!r}")
    if value != value.to_integral_value():
        raise ValueError(f"{what} must be whole shares, got {value}")


@dataclass(frozen=True, slots=True)
class ExecutionRules:
    """How execution turns approved weights into orders, for one market profile.

    Attributes:
        rebalance_band: How far a held position may drift from its target before it
            is resized, as a fraction of the target (0.10 is 10%). A choice, not a
            market fact: inside the band, the minimum commission would cost more than
            the drift. Entries and full exits always trade. Zero trades to the exact
            target at every cycle.
        price_buffer: How far above the last close the next open may be and the cycle's
            purchases still be paid for from settled cash, as a fraction (0.02 is 2%).
            Purchases are sized at the close but fill at the open, and a purchase the
            cash cannot pay for at the open is cancelled whole. It binds only when cash
            is short; a larger gap still cancels, and the next cycle tries again.
    """

    rebalance_band: Decimal
    price_buffer: Decimal

    def __post_init__(self) -> None:
        for name in ("rebalance_band", "price_buffer"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be a finite Decimal, got {value!r}")
            if not 0 <= value < 1:
                raise ValueError(f"{name} must be at least 0 and below 1, got {value}")

    def within_band(self, held: Decimal, target: Decimal) -> bool:
        """True if a holding of ``held`` shares is close enough to ``target`` to keep.

        Only a resize can be inside the band: an entry (nothing held) or an exit (a
        target of zero) always trades.
        """
        if held <= 0 or target <= 0:
            return False
        return abs(target - held) <= self.rebalance_band * target


class PlanNote(StrEnum):
    """Why a sleeve's plan for an instrument is not simply "trade to its weight"."""

    KEEP = "keep"
    """The sleeve did not decide on the instrument this cycle: what it holds is kept."""

    WITHIN_BAND = "within_band"
    """The target moved less than the rebalance band: the holding is kept as it is."""

    BELOW_ONE_SHARE = "below_one_share"
    """The weight is worth less than one whole share, so the target is zero shares."""

    CASH_LIMITED = "cash_limited"
    """The purchase was cut to what settled cash pays for, costs included."""

    CAPPED = "capped"
    """The purchase was cut to fit the guardrails' money caps (ADR-0034)."""


@dataclass(frozen=True, slots=True)
class PlanLine:
    """One sleeve's plan for one instrument at one decision cycle.

    Attributes:
        strategy_id: The sleeve's strategy.
        instrument: The instrument.
        held: Shares the sleeve held before this cycle.
        target: Shares it aims for, after the band; ``held`` when kept.
        crossed: Shares moved to it (positive) or from it (negative) by another sleeve
            at the decision's close, without an order (ADR-0023).
        ordered: Shares it expects from this cycle's order for the instrument: positive
            for a purchase, negative for a sale.
        note: Why the plan is not simply its weight in whole shares, if it is not.
    """

    strategy_id: str
    instrument: Instrument
    held: Decimal
    target: Decimal
    crossed: Decimal = Decimal(0)
    ordered: Decimal = Decimal(0)
    note: PlanNote | None = None

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        label = f"plan of {self.strategy_id} for {self.instrument}"
        for value, what in (
            (self.held, "held"),
            (self.target, "target"),
            (self.crossed, "crossed"),
            (self.ordered, "ordered"),
        ):
            _require_whole(value, f"{label}: {what}")
        if self.held < 0 or self.target < 0:
            raise ValueError(f"{label}: held and target cannot be negative")
        if self.crossed and self.ordered and (self.crossed > 0) != (self.ordered > 0):
            raise ValueError(f"{label}: crossed and ordered go in opposite directions")
        planned = self.held + self.crossed + self.ordered
        if self.note in (PlanNote.CASH_LIMITED, PlanNote.CAPPED):
            if planned >= self.target:
                raise ValueError(f"{label}: a {self.note} plan ends below its target")
        elif planned != self.target:
            raise ValueError(
                f"{label}: held {self.held} + crossed {self.crossed} + ordered "
                f"{self.ordered} must equal the target {self.target}"
            )

    @property
    def planned(self) -> Decimal:
        """Shares the sleeve will hold if this cycle's order fills in full."""
        return self.held + self.crossed + self.ordered
