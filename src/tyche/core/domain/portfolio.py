"""The portfolio types: the combined target of every strategy, sleeve by sleeve (ADR-0022).

Weights here are fractions of account equity, exact ``Decimal``. A strategy's own
weights (fractions of its budget) become ``Contribution``s by multiplying by its
budget. An ``InstrumentTarget`` adds up the contributions to one instrument; a
``Sleeve`` says, for one strategy, what it decided on this cycle.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tyche.core.domain.instrument import Instrument
from tyche.core.domain.money import Money
from tyche.core.domain.signals import require_strategy_id


def require_budgets(budgets: Mapping[str, Decimal]) -> None:
    """Raise ``ValueError`` unless ``budgets`` is a valid set of strategy budgets.

    Each budget is a fraction of account equity above 0 and at most 1, and together
    they add up to at most 1; whatever is left is held as cash.
    """
    if not budgets:
        raise ValueError("budgets: need at least one strategy")
    for strategy_id, budget in budgets.items():
        require_strategy_id(strategy_id)
        if not isinstance(budget, Decimal) or not budget.is_finite():
            raise ValueError(f"budget of {strategy_id}: must be a finite Decimal, got {budget!r}")
        if not 0 < budget <= 1:
            raise ValueError(
                f"budget of {strategy_id}: must be above 0 and at most 1, got {budget}"
            )
    total = sum(budgets.values(), start=Decimal(0))
    if total > 1:
        raise ValueError(f"budgets add up to {total}, more than 1")


class SleeveStatus(StrEnum):
    """What a strategy did at one decision cycle."""

    DECIDED = "decided"
    """It published targets for the instruments it was offered."""

    FAILED = "failed"
    """It could not decide. Everything its sleeve holds is kept."""


@dataclass(frozen=True, slots=True)
class Sleeve:
    """One strategy's share of the account at one decision cycle.

    Attributes:
        strategy_id: The strategy instance.
        budget: Its fraction of account equity.
        status: Whether it decided or failed this cycle.
        decided_on: The instruments it was offered, and so decided on. An instrument
            here without a contribution from this sleeve has a target of zero; anything
            the sleeve holds that is not here is kept (ADR-0022).
        strategy_version: The version of its code, when it decided.
        error: Why it failed, when it failed.
    """

    strategy_id: str
    budget: Decimal
    status: SleeveStatus
    decided_on: tuple[Instrument, ...] = ()
    strategy_version: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        require_budgets({self.strategy_id: self.budget})
        if len(set(self.decided_on)) != len(self.decided_on):
            raise ValueError(f"sleeve {self.strategy_id}: an instrument is repeated")
        if self.status is SleeveStatus.DECIDED:
            if not self.strategy_version or self.error is not None:
                raise ValueError(
                    f"sleeve {self.strategy_id}: a decided sleeve has a version and no error"
                )
        elif self.decided_on or not self.error:
            raise ValueError(
                f"sleeve {self.strategy_id}: a failed sleeve has an error and decided on nothing"
            )


@dataclass(frozen=True, slots=True)
class Contribution:
    """What one strategy wants of one instrument, as a fraction of account equity.

    Attributes:
        strategy_id: The strategy that wants it.
        weight: Its budget times its own weight. Zero means "sell this sleeve's shares".
        reason: The strategy's reason, for the journal.
        stop_price: The strategy's stop for its own shares, or ``None``.
    """

    strategy_id: str
    weight: Decimal
    reason: str
    stop_price: Money | None = None

    def __post_init__(self) -> None:
        require_strategy_id(self.strategy_id)
        if not isinstance(self.weight, Decimal) or not self.weight.is_finite():
            raise ValueError(f"contribution of {self.strategy_id}: weight must be a Decimal")
        if not 0 <= self.weight <= 1:
            raise ValueError(
                f"contribution of {self.strategy_id}: weight must be between 0 and 1, "
                f"got {self.weight}"
            )
        if self.stop_price is not None and not self.stop_price.is_positive:
            raise ValueError(f"contribution of {self.strategy_id}: stop price must be positive")


@dataclass(frozen=True, slots=True)
class InstrumentTarget:
    """The combined target for one instrument: every sleeve's contribution to it.

    Attributes:
        instrument: The instrument.
        contributions: One per strategy that targeted it, ordered by strategy id.
    """

    instrument: Instrument
    contributions: tuple[Contribution, ...]

    def __post_init__(self) -> None:
        label = f"target for {self.instrument}"
        if not self.contributions:
            raise ValueError(f"{label}: needs at least one contribution")
        ids = [c.strategy_id for c in self.contributions]
        if ids != sorted(set(ids)):
            raise ValueError(f"{label}: contributions must be one per strategy, by strategy id")
        for contribution in self.contributions:
            stop = contribution.stop_price
            if stop is not None and stop.currency is not self.instrument.currency:
                raise ValueError(
                    f"{label}: {contribution.strategy_id}'s stop is in {stop.currency}, "
                    f"{self.instrument} trades in {self.instrument.currency}"
                )
        if self.weight > 1:
            raise ValueError(f"{label}: contributions add up to {self.weight}, more than 1")

    @property
    def weight(self) -> Decimal:
        """The instrument's total weight of account equity."""
        return sum((c.weight for c in self.contributions), start=Decimal(0))

    def contribution_of(self, strategy_id: str) -> Contribution | None:
        for contribution in self.contributions:
            if contribution.strategy_id == strategy_id:
                return contribution
        return None
