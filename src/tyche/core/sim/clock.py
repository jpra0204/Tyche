"""SimClock: a clock that only moves when it is told to."""

from datetime import datetime

from tyche.core.domain.validation import require_utc


class SimClock:
    """Simulated time for backtests and tests. Implements the ``Clock`` port.

    The clock stands still until ``advance_to`` is called. In a backtest the engine
    moves it to each input's timestamp before publishing that input, so everything the
    input causes is stamped with the moment it would have happened.

    Time never goes backwards. An attempt to move it back is a bug in whatever is
    feeding the engine, and raises.
    """

    def __init__(self, start: datetime) -> None:
        require_utc(start, "SimClock start")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance_to(self, moment: datetime) -> None:
        """Move the clock forward to ``moment``. Staying at the same instant is allowed."""
        require_utc(moment, "SimClock time")
        if moment < self._now:
            raise ValueError(
                f"SimClock cannot go backwards: it is {self._now.isoformat()}, "
                f"asked to move to {moment.isoformat()}"
            )
        self._now = moment
