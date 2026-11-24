"""When a daily decision cycle may run, and until when its decision may trade (ADR-0043).

``DailyCycleRules`` belong to a market profile (``[daily_cycle]`` in
``config/markets/<NAME>.toml``). Both values were chosen by Pablo on 2026-11-24:

* **After the close.** A session's bars are fetched, and its decision made, only once
  ``after_close`` has passed since the session's close. Yahoo documents no time at which
  its daily bar becomes final, and a bar cached too early is never fetched again, so it
  would stay in every later backtest too. The wait costs nothing: orders go to the next
  open (ADR-0041).
* **Before the next open.** A decision at a session's close sends orders for the next
  session's open. It may trade until ``before_next_open`` before that open. Later, the
  next session's open is too close or already past, the signal is stale, and the cycle
  is skipped and reported, never traded. Measured to the next open rather than as an
  age, so a Saturday catch-up of Friday's close still trades at Monday's open, exactly
  as Friday evening would have.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from tyche.core.domain.session import Session


@dataclass(frozen=True, slots=True)
class DailyCycleRules:
    """When a session's decision may be made and until when it may trade.

    Attributes:
        after_close: Time after a session's close before its bars count as final.
        before_next_open: How long before the next session's open a decision stops
            being tradable.
    """

    after_close: timedelta
    before_next_open: timedelta

    def __post_init__(self) -> None:
        for name in ("after_close", "before_next_open"):
            value = getattr(self, name)
            if not isinstance(value, timedelta):
                raise ValueError(f"{name} must be a timedelta, got {value!r}")
            if value < timedelta(0):
                raise ValueError(f"{name} must not be negative, got {value}")

    def ready_at(self, session: Session) -> datetime:
        """The moment ``session``'s bars count as final and may be fetched."""
        return session.closes_at + self.after_close

    def trade_until(self, next_session: Session) -> datetime:
        """The last moment a decision made before ``next_session`` may still trade."""
        return next_session.opens_at - self.before_next_open
