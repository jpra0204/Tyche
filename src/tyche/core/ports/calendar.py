"""The Calendar port: when a market is open."""

from datetime import date
from typing import Protocol

from tyche.core.domain.session import Session


class CalendarError(Exception):
    """A calendar could not answer the question."""


class OutOfCalendarRangeError(CalendarError):
    """The date asked about is outside the range the calendar was loaded for.

    Raised instead of guessing: "is this a trading day?" has no safe default.
    """


class Calendar(Protocol):
    """Trading sessions for one market: holidays, half days and opening hours.

    A calendar covers a fixed range of dates, chosen when it is created. Every method
    raises ``OutOfCalendarRangeError`` when a question falls outside that range.
    """

    @property
    def mic(self) -> str:
        """The calendar's market identifier code, e.g. ``XNYS``."""
        ...

    def session_on(self, day: date) -> Session | None:
        """Return the session on ``day``, or ``None`` if the market is closed that day."""
        ...

    def sessions_between(self, first: date, last: date) -> tuple[Session, ...]:
        """Return every session from ``first`` to ``last`` inclusive, oldest first."""
        ...

    def next_session(self, after: date) -> Session:
        """Return the first session on a date later than ``after``."""
        ...

    def previous_session(self, before: date) -> Session:
        """Return the last session on a date earlier than ``before``."""
        ...
