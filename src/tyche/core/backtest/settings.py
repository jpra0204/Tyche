"""What a backtest may use: the starting cash and the reserved holdout (ADR-0024).

The holdout is the most recent slice of history. No backtest may replay it, so that
when the Phase 3 gate finally uses it, once, for the check before a promotion, nothing
has been tuned on it. Its start is a fixed date in the workspace, not "the last N
years": a sliding start would hand last year's holdout to this year's experiments.
"""

from dataclasses import dataclass
from datetime import date

from tyche.core.domain import Money


class HoldoutError(ValueError):
    """A backtest asked for history inside the reserved holdout."""


@dataclass(frozen=True, slots=True)
class BacktestSettings:
    """Backtest settings from the workspace.

    Attributes:
        holdout_starts: The first day of the holdout. Every backtest must end before it.
        starting_cash: The deposit every backtest starts from, settled, in the market
            profile's cash currency.
    """

    holdout_starts: date
    starting_cash: Money

    def __post_init__(self) -> None:
        if not self.starting_cash.is_positive:
            raise ValueError(f"starting cash must be positive, got {self.starting_cash}")

    def require_before_holdout(self, last: date) -> None:
        """Raise ``HoldoutError`` unless a run ending on ``last`` stays out of the holdout."""
        if last >= self.holdout_starts:
            raise HoldoutError(
                f"the backtest would reach {last.isoformat()}, but history from "
                f"{self.holdout_starts.isoformat()} on is the reserved holdout; end the "
                f"backtest before {self.holdout_starts.isoformat()}"
            )
