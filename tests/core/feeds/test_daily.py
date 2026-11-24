"""The daily feed: the replay re-stamped with the wall clock, stale cycles skipped (ADR-0043).

January 2024, winter time: sessions close at 21:00 UTC and open at 14:30 UTC, so a
session's bars are final at 23:00 UTC and its decision trades until 14:00 UTC on the
next session day. 15 January was a holiday (Martin Luther King Jr. Day).
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.support.market import JANUARY_2024, QQQ, SPY, bar, close_of
from tests.support.profiles import US_DAILY_CYCLE
from tests.support.recording import Recorder
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.core.domain import AssetClass, BarHistory, Currency, Instrument
from tyche.core.engine import Engine
from tyche.core.events import (
    BarEvent,
    CycleSkippedEvent,
    DataReadyEvent,
    Event,
    EventBus,
    RunMode,
    SessionEvent,
    SkipReason,
)
from tyche.core.feeds import DailyFeed
from tyche.core.ports import Calendar, Feed
from tyche.core.sim import HistoricalReplay, cycle_id

FRI_12 = date(2024, 1, 12)
TUE_16 = date(2024, 1, 16)


class WallClock:
    """The wall clock in a test: set by hand, optionally moving on at every reading."""

    def __init__(self, current: datetime, *, step: timedelta = timedelta(0)) -> None:
        self.current = current
        self.step = step

    def now(self) -> datetime:
        reading = self.current
        self.current += self.step
        return reading

    def wait_until(self, moment: datetime) -> None:
        self.current = max(self.current, moment)


@pytest.fixture(scope="module")
def nyse() -> Calendar:
    return ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))


def history(instrument: Instrument, days: list[date] = JANUARY_2024) -> BarHistory:
    return BarHistory(instrument, tuple(bar(day, instrument=instrument) for day in days))


HISTORIES = (history(SPY), history(QQQ))


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def feed(
    nyse: Calendar,
    now: datetime,
    first: date,
    histories: tuple[BarHistory, ...] = HISTORIES,
    *,
    clock: WallClock | None = None,
) -> DailyFeed:
    return DailyFeed(histories, nyse, clock or WallClock(now), US_DAILY_CYCLE, first)


def events(source: Feed) -> list[Event]:
    return [item.event for item in source.inputs()]


class TestWhichSessions:
    def test_nothing_is_published_before_the_bars_are_final(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(FRI_12, 22, 59), FRI_12)

        assert daily.sessions == ()
        assert daily.starts_at is None
        assert events(daily) == []

    def test_a_session_is_published_once_two_hours_have_passed(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(FRI_12, 23, 0), FRI_12)

        assert [s.day for s in daily.sessions] == [FRI_12]
        assert daily.starts_at == at(FRI_12, 14, 30)

    def test_missed_sessions_are_all_published_oldest_first(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(FRI_12, 23, 30), date(2024, 1, 9))

        assert [s.day for s in daily.sessions] == [date(2024, 1, d) for d in (9, 10, 11, 12)]

    def test_a_first_day_after_the_latest_final_session_publishes_nothing(
        self, nyse: Calendar
    ) -> None:
        # The checkpoint already covers Friday; nothing has closed since.
        daily = feed(nyse, at(date(2024, 1, 13), 15, 0), TUE_16)

        assert daily.sessions == ()

    def test_a_candidate_on_another_calendar_is_refused(self, nyse: Calendar) -> None:
        xic = Instrument("XIC", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)

        with pytest.raises(ValueError, match=r"one calendar, XNYS; XIC.XTSE follow another"):
            feed(nyse, at(FRI_12, 23, 30), FRI_12, (*HISTORIES, history(xic, [])))


class TestParityWithTheReplay:
    def test_a_fresh_session_publishes_exactly_what_the_replay_does(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(FRI_12, 23, 30), FRI_12)
        replay = HistoricalReplay(HISTORIES, {"XNYS": nyse}, FRI_12, FRI_12)

        assert events(daily) == events(replay)
        assert daily.traded is not None
        assert daily.traded.day == FRI_12
        assert daily.skipped == ()

    def test_the_cycle_keeps_the_replays_cycle_id(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(FRI_12, 23, 30), FRI_12)

        ready = [i for i in daily.inputs() if isinstance(i.event, DataReadyEvent)]

        assert [i.cycle_id for i in ready] == [cycle_id(daily.sessions[0])]

    def test_a_catch_up_differs_from_the_replay_only_in_the_skipped_cycles(
        self, nyse: Calendar
    ) -> None:
        daily = feed(nyse, at(FRI_12, 23, 30), date(2024, 1, 9))
        replay = HistoricalReplay(HISTORIES, {"XNYS": nyse}, date(2024, 1, 9), FRI_12)

        published = events(daily)
        expected = events(replay)

        assert len(published) == len(expected)
        for got, wanted in zip(published, expected, strict=True):
            if isinstance(wanted, DataReadyEvent) and wanted.as_of != close_of(FRI_12):
                assert isinstance(got, CycleSkippedEvent)
                assert (got.as_of, got.delivered, got.missing) == (
                    wanted.as_of,
                    wanted.delivered,
                    wanted.missing,
                )
            else:
                assert got == wanted

    def test_every_input_is_stamped_with_the_wall_clock_in_order(self, nyse: Calendar) -> None:
        clock = WallClock(at(FRI_12, 23, 30), step=timedelta(milliseconds=5))
        daily = feed(nyse, clock.current, date(2024, 1, 9), clock=clock)

        stamps = [item.at for item in daily.inputs()]

        assert stamps == sorted(stamps)
        assert stamps[0] > at(FRI_12, 23, 30)  # never the market's own time

    def test_bars_come_from_the_daily_feed_and_sessions_from_the_calendar(
        self, nyse: Calendar
    ) -> None:
        daily = feed(nyse, at(FRI_12, 23, 30), FRI_12)

        sources = {type(i.event).__name__: i.source for i in daily.inputs()}

        assert sources["BarEvent"] == "daily_feed"
        assert sources["DataReadyEvent"] == "daily_feed"
        assert sources["SessionEvent"] == "calendar"


class TestFreshness:
    def test_missed_sessions_are_skipped_as_stale(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(FRI_12, 23, 30), date(2024, 1, 10))
        events(daily)

        assert [(s.as_of, s.reason, s.trade_until) for s in daily.skipped] == [
            (close_of(date(2024, 1, 10)), SkipReason.STALE, at(date(2024, 1, 11), 14, 0)),
            (close_of(date(2024, 1, 11)), SkipReason.STALE, at(FRI_12, 14, 0)),
        ]
        assert daily.traded is not None
        assert daily.traded.day == FRI_12

    def test_a_saturday_catch_up_of_friday_still_trades_at_the_next_open(
        self, nyse: Calendar
    ) -> None:
        daily = feed(nyse, at(date(2024, 1, 13), 15, 0), FRI_12)
        events(daily)

        assert daily.traded is not None
        assert daily.traded.day == FRI_12

    def test_a_holiday_monday_morning_still_trades_at_tuesdays_open(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(date(2024, 1, 15), 14, 30), FRI_12)
        events(daily)

        assert daily.traded is not None

    def test_one_minute_before_the_deadline_the_cycle_runs(self, nyse: Calendar) -> None:
        daily = feed(nyse, at(TUE_16, 13, 59), FRI_12)
        events(daily)

        assert daily.traded is not None

    def test_at_the_deadline_the_cycle_is_stale(self, nyse: Calendar) -> None:
        # 09:00 New York on Tuesday: thirty minutes before the open.
        daily = feed(nyse, at(TUE_16, 14, 0), FRI_12)
        published = events(daily)

        assert daily.traded is None
        assert [s.reason for s in daily.skipped] == [SkipReason.STALE]
        assert not [e for e in published if isinstance(e, DataReadyEvent)]
        assert [e.bar.instrument for e in published if isinstance(e, BarEvent)] == [SPY, QQQ]

    def test_freshness_is_judged_when_the_cycle_would_start(self, nyse: Calendar) -> None:
        # A slow run that crosses 09:00 New York before it reaches the decision: the
        # clock is read again, and the decision is not sent.
        clock = WallClock(at(TUE_16, 13, 59), step=timedelta(seconds=30))
        daily = feed(nyse, clock.current, FRI_12, clock=clock)
        events(daily)

        assert daily.traded is None
        assert [s.reason for s in daily.skipped] == [SkipReason.STALE]


class TestIncomplete:
    def test_a_candidate_without_a_bar_skips_the_cycle(self, nyse: Calendar) -> None:
        without_friday = history(QQQ, [d for d in JANUARY_2024 if d != FRI_12])
        daily = feed(nyse, at(FRI_12, 23, 30), FRI_12, (history(SPY), without_friday))
        published = events(daily)

        assert daily.traded is None
        (skipped,) = daily.skipped
        assert (skipped.reason, skipped.delivered, skipped.missing) == (
            SkipReason.INCOMPLETE,
            (SPY,),
            (QQQ,),
        )
        assert [e.bar.instrument for e in published if isinstance(e, BarEvent)] == [SPY]

    def test_a_stale_cycle_is_stale_even_when_incomplete(self, nyse: Calendar) -> None:
        without_friday = history(QQQ, [d for d in JANUARY_2024 if d != FRI_12])
        daily = feed(nyse, at(TUE_16, 14, 0), FRI_12, (history(SPY), without_friday))
        events(daily)

        assert [(s.reason, s.missing) for s in daily.skipped] == [(SkipReason.STALE, (QQQ,))]


class TestInTheEngine:
    def test_a_catch_up_runs_through_the_engine_on_the_wall_clock(self, nyse: Calendar) -> None:
        clock = WallClock(at(FRI_12, 23, 30), step=timedelta(milliseconds=1))
        bus = EventBus(clock.now)
        recorder = Recorder(bus)
        daily = feed(nyse, clock.current, date(2024, 1, 10), clock=clock)
        engine = Engine(bus, clock, run_id="paper-1", mode=RunMode.PAPER, code_version="0.1.0")

        run = engine.run(daily)

        assert run.completed, run.failure
        kinds = [type(e).__name__ for e in recorder.events]
        assert kinds.count("CycleSkippedEvent") == 2
        assert kinds.count("DataReadyEvent") == 1
        assert kinds.count("SessionEvent") == 6
        closes = [e for e in recorder.events if isinstance(e, SessionEvent)]
        assert closes[-1].session.day == FRI_12
