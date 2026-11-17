"""Session: one trading day on one calendar."""

from dataclasses import dataclass
from datetime import date, datetime

from tyche.core.domain.validation import require_mic, require_utc


@dataclass(frozen=True, slots=True)
class Session:
    """One trading session: when a market opened and closed on a given day.

    The answer to "when did Tuesday's bar become known?" is this object's
    ``closes_at``. It differs between summer and winter, and on half days, which is why
    the core asks a calendar instead of assuming a fixed closing time.

    Attributes:
        calendar: MIC of the trading calendar, e.g. ``XNYS``.
        day: The session's date in the exchange's own timezone.
        opens_at: Opening time, timezone-aware UTC.
        closes_at: Closing time, timezone-aware UTC.
        is_half_day: True if the market closes earlier than usual.
    """

    calendar: str
    day: date
    opens_at: datetime
    closes_at: datetime
    is_half_day: bool

    def __post_init__(self) -> None:
        require_mic(self.calendar, "calendar")
        require_utc(self.opens_at, f"{self}: opens_at")
        require_utc(self.closes_at, f"{self}: closes_at")
        if self.opens_at >= self.closes_at:
            raise ValueError(f"{self}: must open before it closes")

    def __str__(self) -> str:
        return f"{self.calendar} session {self.day.isoformat()}"
