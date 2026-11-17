"""A ``Calendar`` backed by the ``exchange_calendars`` library.

The library computes sessions from holiday rules offline; it makes no network calls.
It is untyped, so every value that comes back from it is converted to one of our own
types before leaving this module.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import exchange_calendars as xcals

from tyche.core.domain.session import Session
from tyche.core.domain.validation import require_mic
from tyche.core.ports.calendar import CalendarError, OutOfCalendarRangeError

_ONE_DAY = timedelta(days=1)


class ExchangeCalendarsCalendar:
    """Trading sessions for one market, from ``exchange_calendars``.

    Implements the ``Calendar`` port.

    Args:
        mic: Canonical calendar code, e.g. ``XNYS``. Aliases are rejected with the name
            to use instead: every US exchange shares the ``XNYS`` calendar.
        first: First date the calendar must cover.
        last: Last date the calendar must cover.

    Sessions in the future are projections from the holiday rules. An unscheduled
    closure (a storm, a day of mourning) only appears after the library is updated.
    """

    def __init__(self, mic: str, *, first: date, last: date) -> None:
        require_mic(mic, "calendar")
        if first > last:
            raise ValueError(f"calendar range is empty: {first} is after {last}")
        if mic not in xcals.get_calendar_names(include_aliases=False):
            raise CalendarError(_unknown_calendar_message(mic))

        self._mic = mic
        self._first = first
        self._last = last
        self._calendar: Any = xcals.get_calendar(mic, start=first, end=last)
        # The library trims the range to real sessions, so these can sit inside it.
        self._first_session: date = self._calendar.first_session.date()
        self._last_session: date = self._calendar.last_session.date()
        self._half_days: frozenset[date] = frozenset(
            stamp.date() for stamp in self._calendar.early_closes
        )

    @property
    def mic(self) -> str:
        return self._mic

    def session_on(self, day: date) -> Session | None:
        self._require_in_range(day)
        if not self._first_session <= day <= self._last_session:
            return None
        if not self._calendar.is_session(day):
            return None
        return self._build(day)

    def sessions_between(self, first: date, last: date) -> tuple[Session, ...]:
        if first > last:
            raise ValueError(f"empty range: {first} is after {last}")
        self._require_in_range(first)
        self._require_in_range(last)
        start = max(first, self._first_session)
        end = min(last, self._last_session)
        if start > end:
            return ()
        days = self._calendar.sessions_in_range(start, end)
        return tuple(self._build(stamp.date()) for stamp in days)

    def next_session(self, after: date) -> Session:
        candidate = max(after + _ONE_DAY, self._first_session)
        self._require_in_range(after)
        if candidate > self._last_session:
            raise OutOfCalendarRangeError(
                f"{self._mic}: no session after {after} within the loaded range, "
                f"which ends {self._last}"
            )
        found: date = self._calendar.date_to_session(candidate, direction="next").date()
        return self._build(found)

    def previous_session(self, before: date) -> Session:
        candidate = min(before - _ONE_DAY, self._last_session)
        self._require_in_range(before)
        if candidate < self._first_session:
            raise OutOfCalendarRangeError(
                f"{self._mic}: no session before {before} within the loaded range, "
                f"which starts {self._first}"
            )
        found: date = self._calendar.date_to_session(candidate, direction="previous").date()
        return self._build(found)

    def _require_in_range(self, day: date) -> None:
        if not self._first <= day <= self._last:
            raise OutOfCalendarRangeError(
                f"{self._mic}: {day} is outside the loaded range {self._first} to {self._last}"
            )

    def _build(self, day: date) -> Session:
        opens_at: datetime = self._calendar.session_open(day).to_pydatetime()
        closes_at: datetime = self._calendar.session_close(day).to_pydatetime()
        return Session(
            calendar=self._mic,
            day=day,
            opens_at=opens_at.astimezone(UTC),
            closes_at=closes_at.astimezone(UTC),
            is_half_day=day in self._half_days,
        )


def _unknown_calendar_message(mic: str) -> str:
    try:
        canonical: str = xcals.resolve_alias(mic)
    except xcals.errors.InvalidCalendarName:
        return f"unknown calendar {mic!r}"
    return f"{mic!r} is an alias; use the calendar it points to, {canonical!r}"
