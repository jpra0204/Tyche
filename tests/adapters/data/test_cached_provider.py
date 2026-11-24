"""The read-through cached provider: fetch only what is missing, audit every answer."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tests.support.market import JANUARY_2024, SPY, bar, close_of, dividend, split
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import (
    BarSource,
    CachedDataProvider,
    CacheOnlySource,
    NotCachedError,
    ParquetBarCache,
    SourceData,
)
from tyche.core.domain import (
    AssetClass,
    Bar,
    CashDistribution,
    Currency,
    DataIssue,
    DataIssueKind,
    Instrument,
    PriceAdjustment,
    Split,
)
from tyche.core.ports import Calendar, DataError, DataProvider
from tyche.core.sim import SimClock

AFTER_JANUARY_16 = datetime(2024, 1, 17, 12, 0, tzinfo=UTC)


class FakeSource:
    """Serves bars from a dictionary and records every request."""

    name = "test"

    def __init__(
        self, closes: dict[date, float], *, adjustment: PriceAdjustment = PriceAdjustment.SPLITS
    ) -> None:
        self.closes = dict(closes)
        self.adjustment = adjustment
        self.extra: list[Bar] = []
        self.distributions: list[CashDistribution] = []
        self.splits: list[Split] = []
        self.issues: list[DataIssue] = []
        self.failure: DataError | None = None
        self.requests: list[tuple[date, date]] = []

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        self.requests.append((first, last))
        if self.failure is not None:
            raise self.failure
        found = [
            bar(day, close, instrument=instrument, adjustment=self.adjustment)
            for day, close in self.closes.items()
            if first <= day <= last
        ]
        return SourceData(
            bars=(*found, *self.extra),
            distributions=tuple(d for d in self.distributions if first <= d.ex_date <= last),
            splits=tuple(s for s in self.splits if first <= s.ex_date <= last),
            issues=tuple(self.issues),
        )


@pytest.fixture(scope="module")
def nyse() -> Calendar:
    return ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))


@pytest.fixture
def clock() -> SimClock:
    return SimClock(AFTER_JANUARY_16)


@pytest.fixture
def cache(tmp_path: Path) -> ParquetBarCache:
    return ParquetBarCache(tmp_path / "data", source="test")


def every_session(close: float = 100.0) -> dict[date, float]:
    return dict.fromkeys(JANUARY_2024, close)


def provider(
    source: BarSource, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
) -> CachedDataProvider:
    return CachedDataProvider(source, cache, {"XNYS": nyse}, clock)


class TestReadThrough:
    def test_the_first_request_fetches_caches_and_returns_audited_bars(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())

        history = provider(source, cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 1), date(2024, 1, 16)
        )

        assert source.requests == [(date(2024, 1, 2), date(2024, 1, 16))]
        assert [b.timestamp for b in history.bars] == [close_of(day) for day in JANUARY_2024]
        assert not history.has_issues
        assert history.fetched == (AFTER_JANUARY_16, AFTER_JANUARY_16)
        assert cache.path_for(SPY, history.bars[0].timeframe).is_file()

    def test_a_repeated_request_is_served_from_the_cache(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        data = provider(source, cache, nyse, clock)
        first = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        second = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert len(source.requests) == 1
        assert second == first

    def test_the_cache_survives_a_new_provider(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        provider(FakeSource(every_session()), cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 2), date(2024, 1, 16)
        )
        offline = FakeSource({})

        history = provider(offline, cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 2), date(2024, 1, 16)
        )

        assert offline.requests == []
        assert len(history.bars) == len(JANUARY_2024)

    def test_extending_the_range_fetches_only_the_new_sessions(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        data = provider(source, cache, nyse, clock)
        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))

        history = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert source.requests == [
            (date(2024, 1, 2), date(2024, 1, 5)),
            (date(2024, 1, 8), date(2024, 1, 16)),
        ]
        assert len(history.bars) == len(JANUARY_2024)

    def test_a_request_with_no_sessions_asks_nothing(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())

        history = provider(source, cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 13), date(2024, 1, 15)
        )

        assert history.bars == ()
        assert source.requests == []


class TestTheClockDecidesWhatShouldExist:
    def test_a_session_that_has_not_closed_is_not_expected(
        self, cache: ParquetBarCache, nyse: Calendar
    ) -> None:
        mid_session = SimClock(close_of(date(2024, 1, 16)) - timedelta(hours=2))
        source = FakeSource(every_session())

        history = provider(source, cache, nyse, mid_session).daily_bars(
            SPY, date(2024, 1, 2), date(2024, 1, 16)
        )

        assert source.requests == [(date(2024, 1, 2), date(2024, 1, 12))]
        assert history.bars[-1].timestamp == close_of(date(2024, 1, 12))
        assert not history.has_issues

    def test_a_session_closes_exactly_at_its_closing_time(
        self, cache: ParquetBarCache, nyse: Calendar
    ) -> None:
        at_close = SimClock(close_of(date(2024, 1, 16)))
        source = FakeSource(every_session())

        provider(source, cache, nyse, at_close).daily_bars(
            SPY, date(2024, 1, 16), date(2024, 1, 16)
        )

        assert source.requests == [(date(2024, 1, 16), date(2024, 1, 16))]

    def test_a_session_is_not_final_until_the_wait_after_its_close(
        self, cache: ParquetBarCache, nyse: Calendar
    ) -> None:
        # ADR-0043: a bar fetched too soon after the close may be provisional, and a
        # cached bar is never fetched again, so the session waits two hours.
        wait = timedelta(hours=2)
        just_before = SimClock(close_of(date(2024, 1, 16)) + wait - timedelta(seconds=1))
        source = FakeSource(every_session())
        data = CachedDataProvider(source, cache, {"XNYS": nyse}, just_before, after_close=wait)

        history = data.daily_bars(SPY, date(2024, 1, 12), date(2024, 1, 16))

        assert source.requests == [(date(2024, 1, 12), date(2024, 1, 12))]
        assert history.bars[-1].timestamp == close_of(date(2024, 1, 12))
        assert not history.has_issues  # the waiting session is not expected yet

    def test_a_session_is_final_exactly_when_the_wait_ends(
        self, cache: ParquetBarCache, nyse: Calendar
    ) -> None:
        wait = timedelta(hours=2)
        at_the_end = SimClock(close_of(date(2024, 1, 16)) + wait)
        source = FakeSource(every_session())
        data = CachedDataProvider(source, cache, {"XNYS": nyse}, at_the_end, after_close=wait)

        data.daily_bars(SPY, date(2024, 1, 16), date(2024, 1, 16))

        assert source.requests == [(date(2024, 1, 16), date(2024, 1, 16))]

    def test_a_negative_wait_is_refused(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        with pytest.raises(ValueError, match="after_close"):
            CachedDataProvider(
                FakeSource({}), cache, {"XNYS": nyse}, clock, after_close=timedelta(minutes=-1)
            )


class TestCoverage:
    def test_sessions_the_source_has_not_published_yet_are_asked_for_again(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource({day: 100.0 for day in JANUARY_2024 if day <= date(2024, 1, 11)})
        data = provider(source, cache, nyse, clock)

        first = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))
        source.closes.update({date(2024, 1, 12): 100.0, date(2024, 1, 16): 100.0})
        second = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert [i.session_day for i in first.issues] == [date(2024, 1, 12), date(2024, 1, 16)]
        assert source.requests[1] == (date(2024, 1, 12), date(2024, 1, 16))
        assert not second.has_issues

    def test_a_gap_in_the_middle_is_reported_once_and_not_fetched_again(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        closes = every_session()
        del closes[date(2024, 1, 9)]
        source = FakeSource(closes)
        data = provider(source, cache, nyse, clock)

        first = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))
        second = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert len(source.requests) == 1
        for history in (first, second):
            assert [(i.kind, i.session_day) for i in history.issues] == [
                (DataIssueKind.MISSING_SESSION, date(2024, 1, 9))
            ]

    def test_an_empty_answer_covers_nothing(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource({})
        data = provider(source, cache, nyse, clock)

        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))
        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))

        assert len(source.requests) == 2
        assert not cache.path_for(SPY, bar(date(2024, 1, 2)).timeframe).exists()

    def test_an_empty_answer_after_the_last_cached_bar_is_asked_for_again(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource({day: 100.0 for day in JANUARY_2024 if day <= date(2024, 1, 5)})
        data = provider(source, cache, nyse, clock)
        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))

        data.daily_bars(SPY, date(2024, 1, 8), date(2024, 1, 16))
        data.daily_bars(SPY, date(2024, 1, 8), date(2024, 1, 16))

        assert source.requests[1:] == [(date(2024, 1, 8), date(2024, 1, 16))] * 2


GLD = Instrument("GLD", "ARCX", Currency.USD, "XNYS", AssetClass.ETF)
GLD_FIRST_BAR = date(2004, 11, 18)


@pytest.fixture(scope="module")
def calendar_2004() -> Calendar:
    return ExchangeCalendarsCalendar("XNYS", first=date(2003, 12, 1), last=date(2004, 12, 31))


class TestBeforeTheInstrumentExisted:
    """GLD's first bar is 2004-11-18; Yahoo has nothing for it before that."""

    @pytest.fixture
    def gld_source(self, calendar_2004: Calendar) -> FakeSource:
        days = calendar_2004.sessions_between(GLD_FIRST_BAR, date(2004, 11, 30))
        return FakeSource({s.day: 45.0 for s in days})

    @staticmethod
    def gld_provider(
        source: BarSource, cache: ParquetBarCache, calendar: Calendar
    ) -> CachedDataProvider:
        clock = SimClock(datetime(2004, 12, 1, 12, 0, tzinfo=UTC))
        return CachedDataProvider(source, cache, {"XNYS": calendar}, clock)

    def test_an_empty_answer_before_the_first_cached_bar_is_covered(
        self, cache: ParquetBarCache, calendar_2004: Calendar, gld_source: FakeSource
    ) -> None:
        data = self.gld_provider(gld_source, cache, calendar_2004)
        data.daily_bars(GLD, date(2004, 1, 2), date(2004, 11, 30))

        first = data.daily_bars(GLD, date(2003, 12, 31), date(2004, 11, 30))
        second = data.daily_bars(GLD, date(2003, 12, 31), date(2004, 11, 30))

        assert gld_source.requests == [
            (date(2004, 1, 2), date(2004, 11, 30)),
            (date(2003, 12, 31), date(2003, 12, 31)),
        ]
        for history in (first, second):
            missing = [i.session_day for i in history.issues]
            assert missing[0] == date(2003, 12, 31)
            assert all(i.kind is DataIssueKind.MISSING_SESSION for i in history.issues)
            assert history.bars[0].timestamp == close_of(GLD_FIRST_BAR)
        assert second == first

    def test_a_cache_only_run_no_longer_asks_for_those_sessions(
        self, cache: ParquetBarCache, calendar_2004: Calendar, gld_source: FakeSource
    ) -> None:
        data = self.gld_provider(gld_source, cache, calendar_2004)
        data.daily_bars(GLD, date(2004, 1, 2), date(2004, 11, 30))
        offline = self.gld_provider(
            CacheOnlySource("test", PriceAdjustment.SPLITS), cache, calendar_2004
        )
        with pytest.raises(NotCachedError):
            offline.daily_bars(GLD, date(2003, 12, 31), date(2004, 11, 30))

        data.daily_bars(GLD, date(2003, 12, 31), date(2003, 12, 31))
        history = offline.daily_bars(GLD, date(2003, 12, 31), date(2004, 11, 30))

        assert history.bars[0].timestamp == close_of(GLD_FIRST_BAR)

    def test_bars_the_source_sent_but_could_not_be_used_still_cover_nothing(
        self, cache: ParquetBarCache, calendar_2004: Calendar, gld_source: FakeSource
    ) -> None:
        data = self.gld_provider(gld_source, cache, calendar_2004)
        data.daily_bars(GLD, date(2004, 1, 2), date(2004, 11, 30))
        gld_source.extra = [
            bar(date(2003, 12, 31), instrument=GLD, timestamp=close_of(date(2003, 12, 27)))
        ]

        data.daily_bars(GLD, date(2003, 12, 31), date(2003, 12, 31))
        data.daily_bars(GLD, date(2003, 12, 31), date(2003, 12, 31))

        assert gld_source.requests[1:] == [(date(2003, 12, 31), date(2003, 12, 31))] * 2


class TestBadSourceData:
    def test_dropped_bars_are_reported_and_not_cached(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        source.extra = [
            bar(date(2024, 1, 6), timestamp=datetime(2024, 1, 6, 21, 0, tzinfo=UTC))
        ]  # a Saturday
        data = provider(source, cache, nyse, clock)

        first = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))
        second = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert [i.kind for i in first.issues] == [DataIssueKind.OFF_SESSION]
        assert not second.has_issues  # served from the cache, which never held the bad bar
        assert len(cache.load(SPY, first.bars[0].timeframe).rows) == len(JANUARY_2024)

    def test_a_suspect_move_is_flagged_on_every_answer(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        closes = every_session()
        closes[date(2024, 1, 10)] = 300.0
        data = provider(FakeSource(closes), cache, nyse, clock)

        for _ in range(2):
            history = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))
            assert [i.kind for i in history.issues] == [
                DataIssueKind.SUSPECT_MOVE,
                DataIssueKind.SUSPECT_MOVE,
            ]

    def test_a_source_failure_is_passed_on(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        source.failure = DataError("source unreachable")

        with pytest.raises(DataError, match="source unreachable"):
            provider(source, cache, nyse, clock).daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))

    def test_switching_to_a_source_with_the_other_adjustment_is_refused(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        provider(FakeSource(every_session()), cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 2), date(2024, 1, 5)
        )
        unadjusted = FakeSource(every_session(), adjustment=PriceAdjustment.NONE)

        with pytest.raises(DataError, match="refusing to mix"):
            provider(unadjusted, cache, nyse, clock).daily_bars(
                SPY, date(2024, 1, 2), date(2024, 1, 16)
            )


class TestConfiguration:
    def test_an_instrument_on_an_unloaded_calendar_is_an_error(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        toronto = Instrument("XIU", "XTSE", Currency.CAD, "XTSE", AssetClass.ETF)

        with pytest.raises(DataError, match="no calendar 'XTSE' loaded"):
            provider(FakeSource({}), cache, nyse, clock).daily_bars(
                toronto, date(2024, 1, 2), date(2024, 1, 5)
            )

    def test_the_cache_must_belong_to_the_same_source(
        self, tmp_path: Path, nyse: Calendar, clock: SimClock
    ) -> None:
        other = ParquetBarCache(tmp_path, source="other")

        with pytest.raises(
            ValueError, match="cache is for source 'other' but the source is 'test'"
        ):
            CachedDataProvider(FakeSource({}), other, {"XNYS": nyse}, clock)

    def test_it_satisfies_the_data_provider_port(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        port: DataProvider = provider(FakeSource(every_session()), cache, nyse, clock)

        assert len(port.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5)).bars) == 4


class TestCorporateActions:
    def test_distributions_and_splits_in_the_window_are_returned(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        source.distributions = [
            dividend(date(2024, 1, 4), "1.5"),
            dividend(date(2024, 1, 11), "0.5"),
        ]
        data = provider(source, cache, nyse, clock)

        whole = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))
        part = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))

        assert [d.ex_date for d in whole.distributions] == [date(2024, 1, 4), date(2024, 1, 11)]
        assert [d.ex_date for d in part.distributions] == [date(2024, 1, 4)]
        assert len(source.requests) == 1  # the second answer came from the cache, actions included

    def test_issues_the_source_found_are_passed_on(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        source.issues = [
            DataIssue(DataIssueKind.INVALID_BAR, SPY, date(2024, 1, 9), "high below close")
        ]

        history = provider(source, cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 2), date(2024, 1, 16)
        )

        assert [i.kind for i in history.issues] == [DataIssueKind.INVALID_BAR]


class TestNewSplit:
    """A split rewrites every earlier price, so older cached bars must be fetched again."""

    def test_a_new_split_refetches_the_whole_history(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session(100.0))
        data = provider(source, cache, nyse, clock)
        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))
        # A 2-for-1 split on 9 January: the source now reports every price halved.
        source.closes = every_session(50.0)
        source.splits = [split(date(2024, 1, 9), "2")]

        history = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert source.requests == [
            (date(2024, 1, 2), date(2024, 1, 5)),
            (date(2024, 1, 8), date(2024, 1, 16)),
            (date(2024, 1, 2), date(2024, 1, 16)),
        ]
        assert {b.close for b in history.bars} == {50.0}
        assert history.splits == (split(date(2024, 1, 9), "2"),)
        assert not history.has_issues
        assert {row.bar.close for row in cache.load(SPY, history.bars[0].timeframe).rows} == {50.0}

    def test_a_split_already_known_does_not_refetch(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        # The source announces a split on the 12th before publishing that day's bar, so the
        # 12th stays uncovered and is asked for again, and the same split comes back.
        source = FakeSource({day: 100.0 for day in JANUARY_2024 if day <= date(2024, 1, 11)})
        source.splits = [split(date(2024, 1, 12), "2")]
        data = provider(source, cache, nyse, clock)
        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))
        source.closes = every_session(100.0)

        history = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert source.requests == [
            (date(2024, 1, 2), date(2024, 1, 16)),
            (date(2024, 1, 12), date(2024, 1, 16)),
        ]
        assert not history.has_issues

    def test_a_split_before_every_cached_bar_does_not_refetch(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session())
        data = provider(source, cache, nyse, clock)
        data.daily_bars(SPY, date(2024, 1, 10), date(2024, 1, 16))
        source.splits = [split(date(2024, 1, 3), "2")]  # older than anything cached

        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert source.requests == [
            (date(2024, 1, 10), date(2024, 1, 16)),
            (date(2024, 1, 2), date(2024, 1, 9)),
        ]

    def test_a_split_dated_on_a_closed_day_still_triggers_a_refetch(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        source = FakeSource(every_session(100.0))
        data = provider(source, cache, nyse, clock)
        data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 5))
        source.closes = every_session(50.0)
        source.splits = [split(date(2024, 1, 13), "2")]  # a Saturday, inside the new range

        history = data.daily_bars(SPY, date(2024, 1, 2), date(2024, 1, 16))

        assert source.requests[-1] == (date(2024, 1, 2), date(2024, 1, 16))
        assert {b.close for b in history.bars} == {50.0}

    def test_a_refetch_that_returns_nothing_is_an_error(
        self, cache: ParquetBarCache, nyse: Calendar, clock: SimClock
    ) -> None:
        provider(FakeSource(every_session()), cache, nyse, clock).daily_bars(
            SPY, date(2024, 1, 2), date(2024, 1, 5)
        )
        scripted = ScriptedSource(
            SourceData(bars=(bar(date(2024, 1, 9), 50.0),), splits=(split(date(2024, 1, 9), "2"),)),
            SourceData(),  # the full-history request comes back empty
        )

        with pytest.raises(DataError, match="new split, but the source returned no bars"):
            provider(scripted, cache, nyse, clock).daily_bars(
                SPY, date(2024, 1, 2), date(2024, 1, 16)
            )


class ScriptedSource:
    """Returns prepared answers in order, one per request."""

    name = "test"
    adjustment = PriceAdjustment.SPLITS

    def __init__(self, *answers: SourceData) -> None:
        self.answers = list(answers)

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        return self.answers.pop(0)
