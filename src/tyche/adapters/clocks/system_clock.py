"""SystemClock: the real time, for anything that runs against the real world."""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from tyche.core.domain.validation import require_utc


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SystemClock:
    """Implements the ``PacedClock`` port with the operating system's clock, in UTC.

    Used wherever Tyche deals with the present: fetching data, and the paper and live
    engines. Backtests use ``SimClock`` instead.

    Args:
        now: Where the time comes from. Tests pass a fake; nothing else should.
        sleep: How to wait, in seconds. Tests pass a fake that moves their ``now``.
    """

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._now = now
        self._sleep = sleep
        self._latest: datetime | None = None

    def now(self) -> datetime:
        # The port promises that time never goes backwards; the operating system's
        # clock can (an NTP correction), so a step back reads as the latest time seen.
        current = self._now()
        if self._latest is not None and current < self._latest:
            return self._latest
        self._latest = current
        return current

    def wait_until(self, moment: datetime) -> None:
        """Sleep until ``moment``; return at once if it has already passed (ADR-0043)."""
        require_utc(moment, "SystemClock wait_until")
        while (remaining := (moment - self.now()).total_seconds()) > 0:
            self._sleep(remaining)
