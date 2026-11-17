"""The exchange_calendars adapter, checked against known New York trading days.

These tests use the real library. It computes sessions from holiday rules offline, so
they are deterministic and need no network. Each date below is a fact about the New
York Stock Exchange in 2024 that can be checked independently of the library.
"""

from datetime import UTC, date, datetime

import pytest

from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.ports import Calendar, CalendarError, OutOfCalendarRangeError


@pytest.fixture(scope="module")
def nyse() -> Calendar:
    # Typed as the port: mypy checks that the adapter has the right shape.
    return ExchangeCalendarsCalendar("XNYS", first=date(2024, 1, 1), last=date(2024, 12, 31))


def utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2024, month, day, hour, minute, tzinfo=UTC)


class TestSessionOn:
    def test_a_winter_session_runs_0930_to_1600_new_york_time(self, nyse: Calendar) -> None:
        session = nyse.session_on(date(2024, 1, 2))

        assert session is not None
        assert session.calendar == "XNYS"
        assert session.day == date(2024, 1, 2)
        assert session.opens_at == utc(1, 2, 14, 30)  # UTC-5 in winter
        assert session.closes_at == utc(1, 2, 21, 0)
        assert not session.is_half_day

    def test_a_summer_session_is_an_hour_earlier_in_utc(self, nyse: Calendar) -> None:
        session = nyse.session_on(date(2024, 7, 1))

        assert session is not None
        assert session.opens_at == utc(7, 1, 13, 30)  # UTC-4 in summer
        assert session.closes_at == utc(7, 1, 20, 0)

    @pytest.mark.parametrize(
        ("day", "closes_at"),
        [
            (date(2024, 7, 3), utc(7, 3, 17, 0)),  # day before Independence Day
            (date(2024, 11, 29), utc(11, 29, 18, 0)),  # day after Thanksgiving
            (date(2024, 12, 24), utc(12, 24, 18, 0)),  # Christmas Eve
        ],
    )
    def test_half_days_close_at_1300_new_york_time(
        self, nyse: Calendar, day: date, closes_at: datetime
    ) -> None:
        session = nyse.session_on(day)

        assert session is not None
        assert session.is_half_day
        assert session.closes_at == closes_at

    @pytest.mark.parametrize(
        "day",
        [
            date(2024, 1, 1),  # New Year's Day
            date(2024, 1, 15),  # Martin Luther King Jr. Day
            date(2024, 3, 29),  # Good Friday
            date(2024, 7, 4),  # Independence Day
            date(2024, 11, 28),  # Thanksgiving
            date(2024, 12, 25),  # Christmas
            date(2024, 7, 6),  # a Saturday
            date(2024, 7, 7),  # a Sunday
        ],
    )
    def test_holidays_and_weekends_have_no_session(self, nyse: Calendar, day: date) -> None:
        assert nyse.session_on(day) is None

    def test_times_are_utc(self, nyse: Calendar) -> None:
        session = nyse.session_on(date(2024, 1, 2))

        assert session is not None
        assert session.opens_at.tzinfo is UTC
        assert session.closes_at.tzinfo is UTC


class TestSessionsBetween:
    def test_skips_the_holiday_and_the_weekend(self, nyse: Calendar) -> None:
        sessions = nyse.sessions_between(date(2024, 7, 1), date(2024, 7, 8))

        assert [s.day.day for s in sessions] == [1, 2, 3, 5, 8]

    def test_bounds_are_inclusive_and_need_not_be_sessions(self, nyse: Calendar) -> None:
        sessions = nyse.sessions_between(date(2024, 7, 4), date(2024, 7, 7))

        assert [s.day for s in sessions] == [date(2024, 7, 5)]

    def test_a_range_with_no_sessions_is_empty(self, nyse: Calendar) -> None:
        assert nyse.sessions_between(date(2024, 7, 6), date(2024, 7, 7)) == ()

    def test_a_range_before_the_first_session_of_the_calendar_is_empty(
        self, nyse: Calendar
    ) -> None:
        # 1 January is inside the loaded range but before its first session.
        assert nyse.sessions_between(date(2024, 1, 1), date(2024, 1, 1)) == ()

    def test_a_full_year_has_252_sessions(self, nyse: Calendar) -> None:
        assert len(nyse.sessions_between(date(2024, 1, 1), date(2024, 12, 31))) == 252

    def test_a_backwards_range_is_an_error(self, nyse: Calendar) -> None:
        with pytest.raises(ValueError, match="empty range"):
            nyse.sessions_between(date(2024, 7, 8), date(2024, 7, 1))


class TestNeighbours:
    def test_next_session_skips_holiday_and_weekend(self, nyse: Calendar) -> None:
        assert nyse.next_session(date(2024, 7, 3)).day == date(2024, 7, 5)
        assert nyse.next_session(date(2024, 7, 5)).day == date(2024, 7, 8)

    def test_next_session_from_a_closed_day(self, nyse: Calendar) -> None:
        assert nyse.next_session(date(2024, 7, 4)).day == date(2024, 7, 5)
        assert nyse.next_session(date(2024, 1, 1)).day == date(2024, 1, 2)

    def test_previous_session_skips_holiday_and_weekend(self, nyse: Calendar) -> None:
        assert nyse.previous_session(date(2024, 7, 5)).day == date(2024, 7, 3)
        assert nyse.previous_session(date(2024, 7, 8)).day == date(2024, 7, 5)

    def test_previous_session_from_a_closed_day(self, nyse: Calendar) -> None:
        assert nyse.previous_session(date(2024, 7, 7)).day == date(2024, 7, 5)

    def test_next_session_is_strictly_later(self, nyse: Calendar) -> None:
        day = date(2024, 3, 12)

        assert nyse.next_session(day).day > day
        assert nyse.previous_session(day).day < day


class TestRange:
    """Outside the loaded range the calendar refuses to answer; it never guesses."""

    def test_session_on_outside_the_range(self, nyse: Calendar) -> None:
        with pytest.raises(OutOfCalendarRangeError, match="outside the loaded range"):
            nyse.session_on(date(2023, 12, 29))
        with pytest.raises(OutOfCalendarRangeError):
            nyse.session_on(date(2025, 1, 2))

    def test_sessions_between_outside_the_range(self, nyse: Calendar) -> None:
        with pytest.raises(OutOfCalendarRangeError):
            nyse.sessions_between(date(2023, 12, 1), date(2024, 1, 31))
        with pytest.raises(OutOfCalendarRangeError):
            nyse.sessions_between(date(2024, 12, 1), date(2025, 1, 31))

    def test_no_next_session_after_the_last_one(self, nyse: Calendar) -> None:
        with pytest.raises(OutOfCalendarRangeError, match="no session after 2024-12-31"):
            nyse.next_session(date(2024, 12, 31))

    def test_no_previous_session_before_the_first_one(self, nyse: Calendar) -> None:
        with pytest.raises(OutOfCalendarRangeError, match="no session before 2024-01-02"):
            nyse.previous_session(date(2024, 1, 2))

    def test_neighbours_of_a_date_outside_the_range(self, nyse: Calendar) -> None:
        with pytest.raises(OutOfCalendarRangeError):
            nyse.next_session(date(2023, 6, 1))
        with pytest.raises(OutOfCalendarRangeError):
            nyse.previous_session(date(2025, 6, 1))

    def test_the_last_session_of_the_range_is_reachable(self, nyse: Calendar) -> None:
        assert nyse.next_session(date(2024, 12, 30)).day == date(2024, 12, 31)
        assert nyse.previous_session(date(2024, 1, 3)).day == date(2024, 1, 2)


class TestConstruction:
    def test_reports_its_code(self, nyse: Calendar) -> None:
        assert nyse.mic == "XNYS"

    def test_a_long_history_can_be_loaded(self) -> None:
        calendar = ExchangeCalendarsCalendar(
            "XNYS", first=date(2000, 1, 1), last=date(2024, 12, 31)
        )

        first = calendar.next_session(date(2000, 1, 1))

        assert first.day == date(2000, 1, 3)

    def test_an_alias_is_rejected_with_the_name_to_use(self) -> None:
        with pytest.raises(CalendarError, match=r"'ARCX' is an alias.*'XNYS'"):
            ExchangeCalendarsCalendar("ARCX", first=date(2024, 1, 1), last=date(2024, 12, 31))

    def test_an_unknown_calendar_is_rejected(self) -> None:
        with pytest.raises(CalendarError, match="unknown calendar 'ZZZZ'"):
            ExchangeCalendarsCalendar("ZZZZ", first=date(2024, 1, 1), last=date(2024, 12, 31))

    def test_a_malformed_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid calendar"):
            ExchangeCalendarsCalendar("nyse", first=date(2024, 1, 1), last=date(2024, 12, 31))

    def test_an_empty_range_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="calendar range is empty"):
            ExchangeCalendarsCalendar("XNYS", first=date(2024, 12, 31), last=date(2024, 1, 1))
