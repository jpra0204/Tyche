"""Timeframe: how much time one bar covers."""

from datetime import timedelta
from enum import StrEnum


class Timeframe(StrEnum):
    """The period one bar covers.

    Daily and intraday bars are the same kind of object with a different timeframe.
    Phases 1 to 5 only produce ``D1`` bars; the intraday members exist so that nothing
    in the core can quietly assume one bar per day.
    """

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"

    @property
    def is_intraday(self) -> bool:
        return self is not Timeframe.D1

    @property
    def duration(self) -> timedelta | None:
        """Fixed length of one bar, or ``None`` for a daily bar.

        A daily bar covers one trading session, and a session's length depends on the
        exchange and the date (half days). Only the ``Calendar`` port can answer that.
        """
        return _DURATIONS.get(self)


_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}
