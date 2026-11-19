"""CacheOnlySource: the provider answers from the cache, and never goes online."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.support.market import JANUARY_2024, SPY, bar
from tyche.adapters.calendars import ExchangeCalendarsCalendar
from tyche.adapters.data import (
    CachedDataProvider,
    CacheOnlySource,
    NotCachedError,
    ParquetBarCache,
    SourceData,
)
from tyche.core.domain import Instrument, PriceAdjustment
from tyche.core.ports import Calendar, DataError
from tyche.core.sim import SimClock

LATER = SimClock(datetime(2024, 2, 1, tzinfo=UTC))
CALENDARS: dict[str, Calendar] = {
    "XNYS": ExchangeCalendarsCalendar("XNYS", first=date(2023, 12, 1), last=date(2024, 3, 31))
}


class FirstWeek:
    """A source that has the first five January sessions."""

    name = "yfinance"
    adjustment = PriceAdjustment.SPLITS

    def fetch_daily(self, instrument: Instrument, first: date, last: date) -> SourceData:
        return SourceData(bars=tuple(bar(d) for d in JANUARY_2024[:5]))


def test_never_fetches() -> None:
    source = CacheOnlySource("yfinance", PriceAdjustment.SPLITS)

    with pytest.raises(NotCachedError) as caught:
        source.fetch_daily(SPY, date(2024, 1, 2), date(2024, 1, 5))

    error = caught.value
    assert isinstance(error, DataError)
    assert (error.instrument, error.first, error.last) == (SPY, date(2024, 1, 2), date(2024, 1, 5))
    assert str(error) == "SPY@ARCX: sessions from 2024-01-02 to 2024-01-05 are not in the cache yet"


def test_behind_a_provider_it_serves_the_cache_and_names_what_is_missing(tmp_path: Path) -> None:
    cache = ParquetBarCache(tmp_path / "bars", source="yfinance")
    CachedDataProvider(FirstWeek(), cache, CALENDARS, LATER).daily_bars(
        SPY, JANUARY_2024[0], JANUARY_2024[4]
    )
    offline = CachedDataProvider(
        CacheOnlySource("yfinance", PriceAdjustment.SPLITS), cache, CALENDARS, LATER
    )

    assert len(offline.daily_bars(SPY, JANUARY_2024[0], JANUARY_2024[4]).bars) == 5
    with pytest.raises(NotCachedError) as caught:
        offline.daily_bars(SPY, JANUARY_2024[0], JANUARY_2024[-1])
    assert (caught.value.first, caught.value.last) == (JANUARY_2024[5], JANUARY_2024[-1])
