"""The Clock port: the only way the core learns what time it is."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Tells the time.

    Nothing in the core may call ``datetime.now()``. In a backtest the clock is a
    ``SimClock`` that the engine moves through history; in paper and live it is the
    wall clock. Code that asks this port cannot tell the difference, which is what lets
    one engine serve all three modes (ADR-0005).
    """

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime.

        Successive calls never go backwards.
        """
        ...


class PacedClock(Clock, Protocol):
    """A clock the engine can wait on.

    The engine never sleeps or jumps time itself: it asks the clock to reach the moment
    of the next input. A simulated clock jumps there; a real clock (Phase 2) sleeps
    until then. Either way the engine's loop is the same (ADR-0005).
    """

    def wait_until(self, moment: datetime) -> None:
        """Return once the clock reads ``moment``. ``moment`` is never in the past."""
        ...
