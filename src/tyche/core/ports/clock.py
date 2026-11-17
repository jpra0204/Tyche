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
