"""SystemClock: the real time, for anything that runs against the real world."""

from datetime import UTC, datetime


class SystemClock:
    """Implements the ``Clock`` port with the operating system's clock, in UTC.

    Used wherever Tyche deals with the present: fetching data, and from Phase 2 the
    paper and live engines. Backtests use ``SimClock`` instead.
    """

    def now(self) -> datetime:
        return datetime.now(UTC)
